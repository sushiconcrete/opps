from pydantic import BaseModel, Field
from typing import List
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
from ..models.schemas import SOChanges, CompetitorState
from .llm_wrapper import create_rate_limited_llm
from langgraph.prebuilt import create_react_agent
from ..prompts.templates import COMPARE_PROMPT, get_today_str
from typing import Dict
import asyncio
from src.core.tracking import OngoingTracker
from langchain_deepseek import ChatDeepSeek
from typing import AsyncGenerator




_llm = None 

def _get_llm():
    global _llm
    if _llm is None:
        # Defer environment validation until actually needed
        # _llm = init_chat_model(model="openai:gpt-4.1", temperature=0)
        _llm = ChatDeepSeek(
            model="deepseek-reasoner",
            temperature=0,
            max_tokens=64000,
            timeout=None,
            max_retries=2,
        )
    return _llm

prompt = """You are a competitive intelligence assistant. Your job is to analyze a website git diff and output only **strategically meaningful changes** in the SOChanges schema.  

Today's date: {date}  

---

### Absolute Rules

- **IGNORE COMPLETELY**  
  - Purely cosmetic edits (spacing, colors, icons, capitalization, spelling, grammar).  
  - Technical/structural changes with no effect on user-facing content or positioning.  

- **INCLUDE ONLY IF STRATEGIC**  
  A change qualifies as meaningful if it involves at least one of these:  
  - New or removed **features, products, or integrations**.  
  - Shifts in **strategic messaging or positioning** (e.g. “future of work”, “AI-powered”, “for enterprises”).  
  - Changes to **pricing, plan structure, or currency/localization**.  
  - Launches of **SDKs, APIs, or developer programs**.  
  - Updates to **roadmap content, partnerships, or customer case studies**.  
  - **Thought leadership** additions (AI guides, whitepapers, webinars) tied to positioning.  

---

### Output Schema (Change)

- `type`: [Added | Modified | Removed]  
- `content`: One concise sentence describing the change.  
- `threat_level`: Integer 0–10 (0=negligible, 10=existential).  
- `why_matter`: Short, reasoned explanation of strategic significance.  
- `suggestions`: Actionable next step(s) for competitive response.  

---

### Method

1. Parse the git diff carefully.  
2. Discard everything irrelevant per the **IGNORE** rules.  
3. For each remaining item, decide if it is strategic (per **INCLUDE** rules).  
4. For each strategic change, output exactly one Change object.  
5. Be concise, structured, and avoid duplication.  

---
The diff for {url} is:  
{diff}  
"""

async def compare_agent_call(diff: str | dict, url: str) -> SOChanges:
    messages = [SystemMessage(content=prompt.format(date=get_today_str(), diff=diff, url=url))]
    structured_model = _get_llm().with_structured_output(SOChanges)
    result = await structured_model.ainvoke(messages)
    return result


async def ongoing_compare_agent(urls: List[str]) -> AsyncGenerator[SOChanges, None]:
    tracker = OngoingTracker(tag="test")
    from firecrawl.v2.types import Document
    sem = asyncio.Semaphore(3)
    tasks = []

    async def _process(update: Document):
        async with sem:
            return await compare_agent_call(
                update.change_tracking.get("diff", {}).get("json"),
                update.metadata.url,
            )

    async for update in tracker.track_stream(urls):
        if (
            isinstance(update, Document)
            and update.change_tracking["changeStatus"] == "changed"
        ):
            tasks.append(asyncio.create_task(_process(update)))

    for fut in asyncio.as_completed(tasks):
        result = await fut
        if result.changes:
            yield result
