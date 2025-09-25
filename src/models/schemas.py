from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, filter_messages
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool, InjectedToolArg
from tavily import TavilyClient
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from typing import List, TypedDict, Annotated, Sequence, Optional
import operator
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, AnyUrl, Field
from langgraph.graph import MessagesState

## Output Schemas
class SOTenant(BaseModel):
    """Schema for correcting the tenant ID."""
    tenant_id: str = Field(default="unknown", description="Unknown if not found, Domain-based stable key like 'stripe.com'")
    tenant_url: str = Field(default="unknown", description="Unknown if not found, Homepage URL")
    tenant_name: str = Field(default="unknown", description="Unknown if not found, Company/brand name")
    tenant_description: str = Field(default="unknown", description="Unknown if not found, One-line description of what they do")
    target_market: str = Field(default="unknown", description="Unknown if not found, The market they operate in")
    key_features: List[str] = Field(default=[], description="Unknown if not found, The key features of the company")


class SOCompetitor(BaseModel):
    id: str = Field(..., description="Domain-based stable key like 'stripe.com'")
    display_name: str = Field(..., description="Company/brand name")
    primary_url: str = Field(..., description="Homepage URL")
    brief_description: str = Field(..., description="One-line description of what they do")
    source: str = Field(default="search", description="Where this competitor was found")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence score")
    demographics: str = Field(..., description="One-line description of target user demographics and persona")

class SOCompetitorList(BaseModel):
    """Schema for listing competitors"""
    competitors: List[SOCompetitor]

class Change(BaseModel):
    change_type: str = Field(..., description=("Added | Removed | Modified"))
    content: str = Field(..., description=("A concise summary of what exactly changed on the competitor's website. Focus on the meaningful details extracted from the diff rather than raw HTML or markdown."))
    timestamp: str = Field(..., description=("The timestamp when this change was detected. Use ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ."))
    threat_level: int = Field(5, ge=0, le=10, description=("A numerical score from 0 to 10 representing the potential impact of this change on our business or strategy. 0 = negligible; 10 = extremely critical."))
    why_matter: str = Field(..., description=("An explanation of why this change is important from a competitive intelligence perspective. Highlight possible business, market, or positioning implications."))
    suggestions: str = Field(..., description=("Actionable next steps or recommendations for our strategy based on this change. Examples: monitor further updates, adjust pricing, review competitor roadmap, or prepare a counter-marketing response."))

class SOChanges(BaseModel):
    url: str = Field(..., description="The URL of the website that was compared")
    changes: List[Change]


# Use TypedDict for state (LangGraph-compatible)

class AgentInputState(MessagesState):
    """Input state for the full agent - only contains messages from user input."""
    pass

class CompetitorState(TypedDict):
    """State for competitor finder subgraph only"""
    tenant: SOTenant
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tool_call_iterations: int = 0
    competitors: List[SOCompetitor] = []
    raw_notes: Annotated[List[str], operator.add] = []
    changes: Annotated[List[SOChanges], operator.add] = []

class CompetitorFinderOutputState(TypedDict):
    """Output state for the competitor finder subgraph"""
    tenant: SOTenant
    competitors_list: List[SOCompetitor]
    raw_notes: Annotated[List[str], operator.add] = []