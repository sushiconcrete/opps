# src/core/competitor_finder.py
"""Competitor Finder Implementation.

This module implements a competitor finder that searches for competitors
using web search tools and LLM analysis in a compiled LangGraph.
"""

from dotenv import load_dotenv
load_dotenv()

from typing import List, Dict, Any, TypedDict, Annotated, Literal
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, BaseMessage
from langchain.chat_models import init_chat_model
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from ..models.schemas import SOCompetitorList, CompetitorState
from ..prompts.templates import COMPETITOR_FINDER_PROMPT, get_today_str
from ..core.rate_limiter import rate_limiter
import logging

logger = logging.getLogger(__name__)


# ===== CONFIGURATION =====

# Lazily initialize the model to avoid requiring OPENAI_API_KEY at import time
_llm = None
_model_with_tools = None
_compress_model = None
_tools = None
_tools_by_name = None

# Define tools
@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """
    Tool for strategic reflection on research progress and decision-making

    Args:
        reflection: Detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded
    """
    return f"Reflection recorded: {reflection}"

def _get_tools():
    global _tools, _tools_by_name
    if _tools is None:
        tavily_search = TavilySearch(max_results=3, search_depth="basic")
        _tools = [tavily_search, think_tool]
        _tools_by_name = {tool.name: tool for tool in _tools}
    return _tools, _tools_by_name

def _get_model():
    global _llm
    if _llm is None:
        _llm = init_chat_model(model="openai:gpt-4.1", temperature=0.0)
    return _llm

def _get_model_with_tools():
    global _model_with_tools
    if _model_with_tools is None:
        model = _get_model()
        tools, _ = _get_tools()
        _model_with_tools = model.bind_tools(tools)
    return _model_with_tools

def _get_compress_model():
    global _compress_model
    if _compress_model is None:
        _compress_model = init_chat_model(model="openai:gpt-4.1", max_tokens=32000)
    return _compress_model

# ===== AGENT NODES =====

model_with_tools = _get_model_with_tools()
compress_model = _get_compress_model()

async def llm_call(state: CompetitorState) -> Dict:
    """Analyze current state and decide on next actions.
    
    The model analyzes the current conversation state and decides whether to:
    1. Call search tools to gather more information
    2. Provide a final answer based on gathered information
    
    Returns updated state with the model's response.
    """
    tenant_info = state["tenant"].model_dump_json()
    tool_call_iterations = state.get("tool_call_iterations", 0)
        
    # Execute OpenAI call (rate limiting is handled by RateLimitedLLM wrapper)
    response = await model_with_tools.ainvoke(
        [SystemMessage(content=COMPETITOR_FINDER_PROMPT.format(
            date=get_today_str(), 
            tool_call_iterations=tool_call_iterations
        ))] + 
        state.get("messages", []) + 
        [HumanMessage(content=f"Find competitors for {tenant_info}")]
    )
    
    return {"messages": [response]}

async def tool_node(state: CompetitorState) -> Dict:
    """Execute all tool calls from the previous LLM response.
    
    Executes all tool calls from the previous LLM responses.
    Returns updated state with tool execution results.
    """
    tool_calls = state["messages"][-1].tool_calls
    _, tools_by_name = _get_tools()
    
    # Execute all tool calls
    observations = []
    for tool_call in tool_calls:
        tool = tools_by_name[tool_call["name"]]
        
        try:
            # Use rate limiter for Tavily search
            if tool_call["name"] == "tavily_search":
                observation = await rate_limiter.execute_with_limit(
                    "tavily",
                    tool.ainvoke,
                    tool_call["args"]
                )
            else:
                observation = await tool.ainvoke(tool_call["args"])
            
            observations.append(observation)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            observations.append(f"Tool execution failed: {str(e)}")
            
    # Create tool message outputs
    tool_outputs = [
        ToolMessage(
            content=observation,
            name=tool_call["name"],
            tool_call_id=tool_call["id"]
        ) for observation, tool_call in zip(observations, tool_calls)
    ]
    
    # Only increment counter for actual search tools, not think_tool
    search_tool_count = sum(1 for tc in tool_calls if tc["name"] == "tavily_search")
    
    return {
        "messages": tool_outputs, 
        "tool_call_iterations": state.get("tool_call_iterations", 0) + (1 if search_tool_count > 0 else 0)
    }

async def extract_competitors(state: CompetitorState) -> Dict:
    """Extract competitors from search results and AI analysis."""
    from langchain_core.messages import filter_messages
    
    # Use rate-limited model for extraction
    structured_model = compress_model.with_structured_output(SOCompetitorList)
    
    # Extract content we need
    tool_contents = [m.content for m in filter_messages(state["messages"], include_types=["tool"])]
    search_context = "\n---\n".join(tool_contents[-3:])  # Last 3 searches only
    
    # Get the last AI message content (the final analysis/summary)
    ai_messages = filter_messages(state["messages"], include_types=["ai"])
    last_ai_content = ai_messages[-1].content if ai_messages else "No AI analysis available"
    
    # Simplified, focused prompt
    messages = [
        SystemMessage(content=f"Extract competitors for {state['tenant'].tenant_name} from the search results and AI analysis below. Focus on direct competitors that customers would actually compare when making purchasing decisions."),
        HumanMessage(content=f"Target Company Information:\n{state['tenant'].model_dump_json(indent=2)}\n\nSearch Results:\n{search_context}\n\nAI Analysis:\n{last_ai_content}\n\nReturn structured competitor list.")
    ]
    
    result = await structured_model.ainvoke(messages)
    raw_notes = [m.content for m in filter_messages(state["messages"], include_types=["tool", "ai"])]
    
    return {
        "tenant": state['tenant'], 
        "competitors": result.competitors, 
        "raw_notes": raw_notes
    }

def should_continue(state: CompetitorState) -> Literal["tool_node", "extract_competitors"]:
    """Determine whether to continue research or provide final answer.
    
    Determines whether the agent should continue the research loop or provide
    a final answer based on whether the LLM made tool calls.
    
    Returns:
        "tool_node": Continue to tool execution
        "extract_competitors": Stop and extract research
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # If the LLM makes a tool call, continue to tool execution
    if last_message.tool_calls:
        return "tool_node"
    # Otherwise, we have a final answer
    return "extract_competitors"

# ===== GRAPH CONSTRUCTION =====

# Build the competitor finder workflow
competitor_graph_builder = StateGraph(CompetitorState)

# Add nodes to the graph
competitor_graph_builder.add_node("llm_call", llm_call)
competitor_graph_builder.add_node("tool_node", tool_node)
competitor_graph_builder.add_node("extract_competitors", extract_competitors)

# Add edges to connect nodes
competitor_graph_builder.add_edge(START, "llm_call")
competitor_graph_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "tool_node": "tool_node",
        "extract_competitors": "extract_competitors"
    }
)
competitor_graph_builder.add_edge("tool_node", "llm_call")
competitor_graph_builder.add_edge("extract_competitors", END)

# Compile the competitor finder
competitor_finder = competitor_graph_builder.compile()