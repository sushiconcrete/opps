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
from src.core.tracking import ArchiveTracker
from langchain_deepseek import ChatDeepSeek
import logging

# ===== 新增：导入缓存管理器 =====
from backend.database import change_detection_cache

logger = logging.getLogger(__name__)

_llm = None 

def _get_llm():
    global _llm
    if _llm is None:
        # Defer environment validation until actually needed
        # _llm = init_chat_model(model="openai:gpt-4.1", temperature=0)
        _llm = ChatDeepSeek(
            model="deepseek-chat",
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
        )
    return _llm

prompt = """You are a competitive intelligence assistant. Your job is to analyze a website git diff and output only **strategically meaningful changes** in the SOChanges schema.  

Today's date: {date}  

---

### Absolute Rules

- **IGNORE COMPLETELY**  
  - Anything referencing `web.archive.org`, Internet Archive snapshots, cached links, or similar archival content.  
  - Purely cosmetic edits (spacing, colors, icons, capitalization, spelling, grammar).  
  - Technical/structural changes with no effect on user-facing content or positioning.  

- **INCLUDE ONLY IF STRATEGIC**  
  A change qualifies as meaningful if it involves at least one of these:  
  - New or removed **features, products, or integrations**.  
  - Shifts in **strategic messaging or positioning** (e.g. "future of work", "AI-powered", "for enterprises").  
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

### Example (for clarity)

DO NOT OUTPUT:  
- "Corrected 'organisations' to 'organizations'"  
- "Replaced archived image links with live ones"  
- "Wayback Machine Changes or web.archive.org changes"

OUTPUT:  
- type: Added  
  content: "Introduced new AI meeting notes feature in Premium plan."  
  threat_level: 7  
  why_matter: "Feature gating AI notes to paid tiers can drive upsell and competitive pressure."  
  suggestions: "Evaluate premium AI feature bundling; prepare messaging around value for money."  

---
The diff for {url} is:  
{diff}  
"""

async def compare_agent_call(diff: str, url: str):
    messages = [SystemMessage(content=prompt.format(date=get_today_str(), diff=diff, url=url))]
    structured_model = _get_llm().with_structured_output(SOChanges)
    result = await structured_model.ainvoke(messages)
    return result

# ===== 【核心修复】：重命名并优化变化检测函数 =====
async def change_detection_node(state: CompetitorState, day_delta: int = 20, enable_caching: bool = True) -> Dict:
    """变化检测节点函数 - 修复版本，解决递归引用问题
    
    Args:
        state: 竞争对手状态，包含需要检测的竞争对手列表
        day_delta: 检测多少天前的变化
        enable_caching: 是否启用缓存机制
    
    Returns:
        包含变化结果的字典
    """
    logger.info(f"开始变化检测节点: enable_caching={enable_caching}")
    
    competitors = state.get("competitors", [])
    if not competitors:
        logger.warning("变化检测节点: 没有竞争对手数据")
        return {"changes": []}
    
    # 【修复】：统一数据格式验证，确保访问一致性
    valid_competitors = []
    url_competitor_pairs = []
    
    for i, competitor in enumerate(competitors):
        try:
            # 【修复】：统一数据访问方式，支持对象和字典
            if isinstance(competitor, dict):
                comp_url = competitor.get('primary_url', '')
                comp_id = competitor.get('competitor_id', competitor.get('id', f"comp_{i}"))
                comp_name = competitor.get('display_name', 'Unknown')
            else:
                # 处理对象类型
                comp_url = getattr(competitor, 'primary_url', '')
                comp_id = getattr(competitor, 'competitor_id', getattr(competitor, 'id', f"comp_{i}"))
                comp_name = getattr(competitor, 'display_name', 'Unknown')
            
            # 【修复】：严格URL验证
            if comp_url and isinstance(comp_url, str) and comp_url.startswith('http'):
                valid_competitors.append(competitor)
                url_competitor_pairs.append((comp_url, comp_id))
                logger.info(f"变化检测节点 - 有效竞争对手: {comp_name} -> {comp_url}")
            else:
                logger.warning(f"变化检测节点 - 跳过无效URL: {comp_name} - URL: '{comp_url}' (type: {type(comp_url)})")
        
        except Exception as e:
            logger.error(f"变化检测节点 - 处理竞争对手数据时出错: {e}", exc_info=True)
            continue
    
    if not valid_competitors:
        logger.warning("变化检测节点: 没有有效的竞争对手URL")
        return {"changes": []}
    
    logger.info(f"变化检测节点: 将检测 {len(valid_competitors)} 个有效竞争对手")
    
    # ===== 步骤1：检查缓存 =====
    cached_results = {}
    uncached_pairs = url_competitor_pairs
    
    if enable_caching:
        try:
            logger.info(f"变化检测节点: 检查缓存 - {len(url_competitor_pairs)} 个URL")
            cached_results = await change_detection_cache.get_cached_results(url_competitor_pairs)
            
            # 过滤出需要重新检测的URL
            uncached_pairs = [
                (url, comp_id) for url, comp_id in url_competitor_pairs 
                if url not in cached_results
            ]
            
            logger.info(f"变化检测节点: 缓存命中 {len(cached_results)} 个URL, 需要检测 {len(uncached_pairs)} 个URL")
        
        except Exception as e:
            logger.warning(f"变化检测节点: 查询缓存失败: {e}")
            # 缓存失败时继续正常流程
            uncached_pairs = url_competitor_pairs
    
    # ===== 步骤2：对未缓存的URL执行变化检测 =====
    new_results = {}
    
    if uncached_pairs:
        # 提取需要检测的URL
        uncached_urls = [url for url, _ in uncached_pairs]
        
        logger.info(f"变化检测节点: 开始检测 {len(uncached_urls)} 个未缓存URL")
        
        # 使用原有的检测逻辑
        tracker = ArchiveTracker()
        
        # 限制并发LLM调用避免触发速率限制
        sem = asyncio.Semaphore(3)
        tasks: List[asyncio.Task] = []
        
        async def _process(update: Dict):
            # 跳过没有有意义diff的项目
            diff_text = (update.get("gitdiff") or "").strip()
            if not diff_text or diff_text.lower().startswith("no change"):
                return None
            
            async with sem:
                try:
                    return await compare_agent_call(diff_text, update.get("url"))
                except Exception as e:
                    logger.error(f"变化检测节点: 处理变化检测失败 {update.get('url')}: {e}")
                    return None
        
        # 使用流式检测获得更快的响应
        try:
            async for update in tracker.compare_stream(uncached_urls, day_delta=day_delta):
                if update and update.get("url"):
                    task = asyncio.create_task(_process(update))
                    tasks.append((update.get("url"), task))
        except Exception as e:
            logger.error(f"变化检测节点: tracker.compare_stream失败: {e}")
        
        if tasks:
            # 等待所有任务完成
            for url, task in tasks:
                try:
                    result = await task
                    if result is not None:
                        # 映射URL到结果用于缓存
                        new_results[url] = result
                        logger.info(f"变化检测节点: 成功检测 {url}")
                except Exception as e:
                    logger.error(f"变化检测节点: 处理检测结果失败 {url}: {e}")
                    continue
            
            logger.info(f"变化检测节点: 新检测完成 - {len(new_results)} 个有效结果")
            
            # ===== 步骤3：缓存新结果 =====
            if enable_caching and new_results:
                try:
                    # 准备缓存数据
                    cache_data = {}
                    competitor_mapping = {}
                    
                    for url, result in new_results.items():
                        # 找到对应的competitor_id
                        comp_id = None
                        for u, c_id in uncached_pairs:
                            if u == url:
                                comp_id = c_id
                                break
                        
                        if comp_id:
                            # 序列化结果
                            result_dict = result.model_dump() if hasattr(result, 'model_dump') else result
                            cache_data[url] = result_dict
                            competitor_mapping[url] = comp_id
                    
                    if cache_data:
                        cached_urls = await change_detection_cache.cache_results(
                            cache_data, competitor_mapping
                        )
                        logger.info(f"变化检测节点: 缓存新检测结果 - {len(cached_urls)} 个URL")
                
                except Exception as e:
                    logger.warning(f"变化检测节点: 缓存新检测结果失败: {e}")
    
    # ===== 步骤4：合并缓存结果和新结果 =====
    all_results = {}
    all_results.update(cached_results)
    all_results.update(new_results)
    
    # 转换为最终格式
    final_changes = list(all_results.values())
    
    logger.info(f"变化检测节点完成: 总计 {len(final_changes)} 个结果 (缓存: {len(cached_results)}, 新检测: {len(new_results)})")
    
    return {"changes": final_changes}

# ===== 保持向后兼容的原始函数 =====
async def change_detector_with_cache(state: CompetitorState, day_delta: int = 20, enable_caching: bool = True) -> Dict:
    """增强版：集成缓存机制的变化检测器 - 调用修复后的节点函数"""
    return await change_detection_node(state, day_delta, enable_caching)

async def change_detector_legacy(state: CompetitorState, day_delta: int = 20) -> Dict:
    """原始的变化检测器（向后兼容，默认启用缓存）"""
    return await change_detection_node(state, day_delta, enable_caching=True)

# ===== 新增：无缓存版本 =====
async def change_detector_no_cache(state: CompetitorState, day_delta: int = 20) -> Dict:
    """无缓存版本的变化检测器"""
    return await change_detection_node(state, day_delta, enable_caching=False)

# ===== 【关键修复】：LangGraph构建 - 修复递归引用问题 =====
agent_builder = StateGraph(CompetitorState)
# 【修复】：使用正确的节点函数，避免递归引用
agent_builder.add_node("change_detector", change_detection_node)
agent_builder.add_edge(START, "change_detector")
agent_builder.add_edge("change_detector", END)
change_detector = agent_builder.compile()

# ===== 新增：带缓存控制的图构建器工厂 =====
def build_change_detector_with_cache_control(enable_caching: bool = True):
    """构建带缓存控制的变化检测器图
    
    Args:
        enable_caching: 是否启用缓存机制
    
    Returns:
        编译后的LangGraph
    """
    async def change_detector_node_with_cache_control(state: CompetitorState) -> Dict:
        return await change_detection_node(state, 20, enable_caching)
    
    builder = StateGraph(CompetitorState)
    builder.add_node("change_detector", change_detector_node_with_cache_control)
    builder.add_edge(START, "change_detector")
    builder.add_edge("change_detector", END)
    return builder.compile()

# ===== 新增：缓存管理功能 =====
async def clear_change_detection_cache():
    """清理所有变化检测缓存"""
    try:
        cleared_count = await change_detection_cache.cleanup_expired_cache()
        logger.info(f"清理缓存完成: {cleared_count} 条过期记录")
        return cleared_count
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        return 0

async def get_cache_statistics():
    """获取缓存统计信息"""
    try:
        stats = await change_detection_cache.get_cache_stats()
        return stats
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        return {"error": str(e)}

async def invalidate_url_cache(urls: List[str]):
    """使指定URL的缓存失效
    
    Args:
        urls: 要使缓存失效的URL列表
    
    Returns:
        被使失效的缓存数量
    """
    try:
        count = 0
        for url in urls:
            if hasattr(change_detection_cache, 'invalidate_cache'):
                if await change_detection_cache.invalidate_cache(url):
                    count += 1
        
        logger.info(f"使缓存失效完成: {count}/{len(urls)} 个URL")
        return count
    except Exception as e:
        logger.error(f"使缓存失效失败: {e}")
        return 0