# src/core/tenant_analyzer.py
"""Tenant Analyzer Implementation.

This module implements a tenant analyzer that extracts company information
using MCP tools and LLM analysis in a compiled LangGraph.
"""

import os
from typing import List, Dict, Any, TypedDict, Annotated
from langchain_core.messages import HumanMessage, BaseMessage
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_mcp_adapters.client import MultiServerMCPClient
from ..models.schemas import SOTenant
from ..prompts.templates import TENANT_INFO_PROMPT
from langchain.chat_models import init_chat_model

# ===== STATE DEFINITION =====

class TenantState(TypedDict):
    """Tenant analysis state"""
    messages: Annotated[List[BaseMessage], add_messages]
    tenant: SOTenant

# ===== CONFIGURATION =====

# Lazily initialize the model to avoid requiring OPENAI_API_KEY at import time
_llm = None

def _get_llm():
    """Return a shared rate-limited LLM wrapper (lazy)."""
    global _llm
    if _llm is None:
        # Defer environment validation until actually needed
        _llm = init_chat_model(model="openai:gpt-4.1", temperature=0)
    return _llm

# MCP tools setup (will be initialized lazily)
_mcp_tools = None

async def _get_mcp_tools(files_path: str = "./files/") -> List[Any]:
    """Get MCP tools (lazy initialization)"""
    global _mcp_tools
    if _mcp_tools is None:
        mcp_config = {
            "filesystem": {
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    os.path.abspath(files_path)
                ],
                "transport": "stdio"
            },
            "firecrawl": {
                "command": "npx",
                "args": ["-y", "firecrawl-mcp"],
                "env": {
                    "FIRECRAWL_API_KEY": os.getenv("FIRECRAWL_API_KEY", "")
                },
                "transport": "stdio"
            }
        }
        client = MultiServerMCPClient(mcp_config)
        _mcp_tools = await client.get_tools()
    return _mcp_tools

# ===== AGENT NODES =====

async def tenant_info_agent(state: TenantState) -> Dict:
    """Tenant information analysis node"""
    tenant_tools = await _get_mcp_tools()
    # Pass the rate-limited Runnable to keep OpenAI calls under the "openai" bucket
    tenant_info_agent = create_react_agent(_get_llm(), tenant_tools, response_format=SOTenant, prompt=TENANT_INFO_PROMPT)
    res = await tenant_info_agent.ainvoke({"messages": state.get("messages", [])})
    return {"tenant": res['structured_response']}

# ===== GRAPH CONSTRUCTION =====

# Build the tenant analysis workflow
tenant_graph_builder = StateGraph(TenantState)

# Add nodes to the graph
tenant_graph_builder.add_node("tenant_info_agent", tenant_info_agent)

# Add edges to connect nodes
tenant_graph_builder.add_edge(START, "tenant_info_agent")
tenant_graph_builder.add_edge("tenant_info_agent", END)

# Compile the agent
tenant_agent = tenant_graph_builder.compile()
