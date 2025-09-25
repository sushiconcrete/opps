from dotenv import load_dotenv
load_dotenv()
from langgraph.graph import StateGraph, START, END
from src.models.schemas import CompetitorState
from src.core import tenant_agent, competitor_finder, change_detector
from langchain_core.messages import HumanMessage
import asyncio
from src.core.ongoing_compare_agent import ongoing_compare_agent
from typing import List
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ===== 导入增强的持久化功能 =====
from backend.database import (
    get_db_session,
    tenant_crud,
    enhanced_task_crud,
    change_detection_cache,
    content_cache,
    get_database_stats,
    init_db,
    check_database_connection
)

logger = logging.getLogger(__name__)

async def build_opp_agent():
    """构建OPP分析代理"""
    agent_builder = StateGraph(CompetitorState)
    agent_builder.add_node("tenant_info_agent", tenant_agent)
    agent_builder.add_node("competitor_finder", competitor_finder)
    agent_builder.add_node("change_detector", change_detector)

    agent_builder.add_edge(START, "tenant_info_agent")
    agent_builder.add_edge("tenant_info_agent", "competitor_finder")
    agent_builder.add_edge("competitor_finder", "change_detector")
    agent_builder.add_edge("change_detector", END)
    opp_agent = agent_builder.compile()
    return opp_agent

# ===== 增强版：优化的持久化OPP Agent =====
async def run_opp_agent_with_enhanced_persistence(
    company_name: str = "FL Studio", 
    enable_caching: bool = True,
    max_competitors: int = 10,
    day_delta: int = 20
):
    """运行OPP代理并使用优化的持久化功能
    
    Args:
        company_name: 要分析的公司名称
        enable_caching: 是否启用缓存机制
        max_competitors: 最大竞争对手数量
        day_delta: 变化检测的天数回溯
    
    Returns:
        完整的分析结果
    """
    
    logger.info(f"开始增强版分析: {company_name} (缓存: {'启用' if enable_caching else '禁用'})")
    
    task_id = None
    tenant_id = None
    full_result = {}
    
    try:
        opp_agent = await build_opp_agent()
        
        # ===== 第一步：执行分析并收集结果 =====
        logger.info("执行分析流程...")
        async for update in opp_agent.astream(
            {"messages": [HumanMessage(content=company_name)]},
            stream_mode="updates",
        ):
            print(update)
            full_result.update(update)
            
            # ===== 租户信息处理 =====
            if "tenant_info_agent" in update and update["tenant_info_agent"].get("tenant"):
                tenant_data = update["tenant_info_agent"]["tenant"]
                
                try:
                    with get_db_session() as db:
                        # 标准化租户数据
                        tenant_dict = _normalize_data(tenant_data)
                        
                        # 确保有tenant_id
                        if 'tenant_id' not in tenant_dict or not tenant_dict['tenant_id']:
                            tenant_dict['tenant_id'] = company_name.lower().replace(' ', '_').replace('-', '_')
                        
                        tenant_id = tenant_dict['tenant_id']
                        
                        # 创建或更新租户
                        tenant_record, created = tenant_crud.get_or_create_tenant(
                            db, tenant_id, tenant_dict
                        )
                        
                        # 创建任务记录
                        task = enhanced_task_crud.create_task_with_tenant(
                            db, 
                            company_name, 
                            tenant_dict, 
                            {
                                'enable_caching': enable_caching,
                                'max_competitors': max_competitors,
                                'day_delta': day_delta
                            }
                        )
                        task_id = task.id
                        
                        action = "创建" if created else "更新"
                        logger.info(f"{action}租户: {tenant_dict.get('tenant_name', company_name)} (任务ID: {task_id})")
                
                except Exception as e:
                    logger.error(f"处理租户信息失败: {e}")
            
            # ===== 竞争对手信息处理 =====
            if "competitor_finder" in update and update["competitor_finder"].get("competitors") and tenant_id and task_id:
                competitors = update["competitor_finder"]["competitors"]
                
                # 限制竞争对手数量
                limited_competitors = competitors[:max_competitors]
                
                try:
                    with get_db_session() as db:
                        # 检查是否启用缓存且已有竞争对手
                        existing_competitors = []
                        if enable_caching:
                            existing_competitors = tenant_crud.get_tenant_competitors(db, tenant_id)
                            
                            if existing_competitors:
                                logger.info(f"使用已存储的竞争对手: {len(existing_competitors)} 个")
                                # 更新状态以使用已存储的竞争对手
                                full_result["competitor_finder"]["competitors"] = existing_competitors[:max_competitors]
                                continue
                        
                        # 保存新的竞争对手
                        competitors_data = [_normalize_data(comp) for comp in limited_competitors]
                        
                        records, mappings = enhanced_task_crud.save_competitors_with_mapping(
                            db, task_id, tenant_id, competitors_data
                        )
                        
                        logger.info(f"保存竞争对手: {len(records)} 个记录, {len(mappings)} 个映射关系")
                
                except Exception as e:
                    logger.error(f"处理竞争对手信息失败: {e}")
            
            # ===== 变化检测处理 =====
            if "change_detector" in update and update["change_detector"].get("changes"):
                changes = update["change_detector"]["changes"]
                
                if enable_caching and changes:
                    try:
                        # 准备缓存数据
                        cache_data = {}
                        competitor_mapping = {}
                        
                        # 获取当前的竞争对手列表
                        current_competitors = full_result.get("competitor_finder", {}).get("competitors", [])
                        
                        for i, change in enumerate(changes):
                            if i < len(current_competitors):
                                comp = current_competitors[i]
                                comp_url = _get_url_from_competitor(comp)
                                comp_id = _get_id_from_competitor(comp)
                                
                                if comp_url:
                                    change_dict = _normalize_data(change)
                                    cache_data[comp_url] = change_dict
                                    competitor_mapping[comp_url] = comp_id
                        
                        if cache_data:
                            cached_urls = await change_detection_cache.cache_results(
                                cache_data, competitor_mapping
                            )
                            logger.info(f"缓存变化检测结果: {len(cached_urls)} 个URL")
                    
                    except Exception as e:
                        logger.error(f"缓存变化检测结果失败: {e}")
        
        # ===== 第二步：生成最终统计 =====
        summary = _generate_analysis_summary(full_result, company_name, enable_caching)
        full_result["summary"] = summary
        
        logger.info(f"分析完成: {company_name}")
        logger.info(f"- 租户信息: {'已保存' if tenant_id else '未保存'}")
        logger.info(f"- 竞争对手: {summary.get('total_competitors', 0)} 个")
        logger.info(f"- 检测到变化: {summary.get('total_changes', 0)} 个")
        logger.info(f"- 缓存命中: {summary.get('cache_hits', 0)} 个")
        
        return full_result
        
    except Exception as e:
        logger.error(f"分析过程中出错: {e}")
        # TODO: 更新任务状态为失败
        if task_id:
            try:
                with get_db_session() as db:
                    enhanced_task_crud.update_task_status(
                        db, task_id, "failed", f"Analysis failed: {str(e)}"
                    )
            except:
                pass
        raise

# ===== 增强版：带持久化的持续跟踪 =====
async def run_ongoing_opp_agent_with_enhanced_persistence(
    database_urls: List[str], 
    tag: str = "default",
    save_content: bool = True
):
    """运行持续跟踪并使用增强的持久化功能
    
    Args:
        database_urls: 要跟踪的URL列表
        tag: 跟踪标签
        save_content: 是否保存内容到数据库
    
    Returns:
        跟踪结果列表
    """
    
    logger.info(f"开始增强版持续跟踪: {len(database_urls)} 个URL (标签: {tag})")
    
    # 导入增强的跟踪器
    from src.core.tracking import OngoingTracker
    
    tracker = OngoingTracker(tag=tag)
    results = []
    
    try:
        # 使用增强版本的流式跟踪
        async for update in tracker.ongoing_tracking_stream_with_persistence(
            database_urls, 
            tag=tag, 
            save_content=save_content
        ):
            # 处理结果
            if hasattr(update, 'model_dump'):
                result_dict = update.model_dump()
            else:
                result_dict = update
            
            results.append(result_dict)
            
            # 输出结果
            url = result_dict.get('url', 'unknown')
            has_changes = 'gitdiff' in result_dict and result_dict['gitdiff'] != "No changes found."
            error = result_dict.get('error')
            
            if error:
                logger.info(f"跟踪结果 [{url}]: {error}")
            elif has_changes:
                logger.info(f"跟踪结果 [{url}]: 检测到变化")
            else:
                logger.info(f"跟踪结果 [{url}]: 无变化")
        
        # 获取跟踪统计
        try:
            try:
                stats = await tracker.get_tracking_statistics(tag)
            except AttributeError:
                # 如果方法不存在，使用内容缓存的统计
                stats = await content_cache.get_tag_statistics(tag)
            logger.info(f"跟踪统计: {stats}")
        except Exception as e:
            logger.warning(f"获取跟踪统计失败: {e}")
        
        logger.info(f"持续跟踪完成: 处理了 {len(results)} 个结果")
        return results
    
    except Exception as e:
        logger.error(f"持续跟踪过程中出错: {e}")
        raise

# ===== 保持向后兼容的原始函数 =====
async def run_opp_agent():
    """原始函数保持不变（向后兼容）"""
    opp_agent = await build_opp_agent()
    async for update in opp_agent.astream(
        {"messages": [HumanMessage(content="FL Studio")]},
        stream_mode="updates",
        subgraphs=True,
    ):
        print(update)

async def run_ongoing_opp_agent(database_urls: List[str]):
    """原始函数保持不变（向后兼容）"""
    results = []
    async for update in ongoing_compare_agent(database_urls):
        results.append(update)
        print(update.model_dump())
    return results

# ===== 辅助函数 =====
def _normalize_data(data):
    """标准化数据格式"""
    if hasattr(data, 'model_dump'):
        return data.model_dump()
    elif hasattr(data, '__dict__'):
        return data.__dict__
    elif isinstance(data, dict):
        return data
    else:
        return {"raw_data": str(data)}

def _get_url_from_competitor(competitor):
    """从竞争对手对象获取URL"""
    if hasattr(competitor, 'primary_url'):
        return competitor.primary_url
    elif isinstance(competitor, dict):
        return competitor.get('primary_url')
    return None

def _get_id_from_competitor(competitor):
    """从竞争对手对象获取ID"""
    if hasattr(competitor, 'id'):
        return competitor.id
    elif isinstance(competitor, dict):
        return competitor.get('id')
    return None

def _generate_analysis_summary(full_result, company_name, enable_caching):
    """生成分析摘要"""
    tenant_data = full_result.get("tenant_info_agent", {}).get("tenant", {})
    competitors = full_result.get("competitor_finder", {}).get("competitors", [])
    changes = full_result.get("change_detector", {}).get("changes", [])
    
    # 计算变化总数
    total_changes = 0
    for change in changes:
        if hasattr(change, 'changes'):
            total_changes += len(change.changes) if change.changes else 0
        elif isinstance(change, dict) and 'changes' in change:
            total_changes += len(change['changes']) if change['changes'] else 0
    
    return {
        "company_name": company_name,
        "tenant_name": tenant_data.get('tenant_name') if isinstance(tenant_data, dict) else getattr(tenant_data, 'tenant_name', company_name),
        "total_competitors": len(competitors),
        "analyzed_competitors": len(changes),
        "total_changes": total_changes,
        "cache_enabled": enable_caching,
        "cache_hits": 0,  # 这里可以从实际的缓存统计中获取
        "analysis_timestamp": asyncio.get_event_loop().time()
    }

# ===== 系统监控和管理功能 =====
async def get_enhanced_system_stats():
    """获取增强的系统统计信息"""
    try:
        # 数据库统计
        db_stats = get_database_stats()
        
        # 缓存统计 - 现在使用async方法
        cache_stats = await change_detection_cache.get_cache_stats()
        
        # 内容存储统计 - 现在使用async方法
        try:
            content_stats = await content_cache.get_global_statistics()
        except Exception as e:
            content_stats = {"error": str(e)}
        
        return {
            "database": db_stats,
            "cache": cache_stats,
            "content_storage": content_stats,
            "version": "enhanced-1.0.0"
        }
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
        return {"error": str(e)}

async def cleanup_system_data(days_to_keep: int = 30):
    """清理系统数据
    
    Args:
        days_to_keep: 保留多少天的数据
    
    Returns:
        清理统计信息
    """
    cleanup_results = {}
    
    try:
        # 清理过期缓存
        cache_cleaned = await change_detection_cache.cleanup_expired_cache()
        cleanup_results["cache_cleaned"] = cache_cleaned
        
        # 清理旧内容
        try:
            content_cleaned = await content_cache.cleanup_old_content("default", days_to_keep)
            cleanup_results["content_cleaned"] = content_cleaned
        except Exception as e:
            logger.warning(f"清理旧内容失败: {e}")
            cleanup_results["content_cleaned"] = 0
        
        logger.info(f"系统清理完成: 缓存 {cache_cleaned} 条, 内容 {cleanup_results.get('content_cleaned', 0)} 条")
        
    except Exception as e:
        logger.error(f"系统清理失败: {e}")
        cleanup_results["error"] = str(e)
    
    return cleanup_results

async def get_tenant_analysis_history_enhanced(tenant_id: str):
    """获取租户的增强分析历史"""
    try:
        with get_db_session() as db:
            # 获取租户信息
            tenant = tenant_crud.get_tenant_by_id(db, tenant_id)
            if not tenant:
                logger.warning(f"未找到租户: {tenant_id}")
                return None
            
            # 获取竞争对手映射
            competitors = tenant_crud.get_tenant_competitors(db, tenant_id)
            
            # 获取任务历史
            tasks = enhanced_task_crud.get_tenant_tasks(db, tenant_id)
            
            logger.info(f"租户 {tenant.tenant_name} 分析历史:")
            logger.info(f"- 竞争对手: {len(competitors)} 个")
            logger.info(f"- 分析任务: {len(tasks)} 个")
            
            return {
                'tenant': {
                    'id': tenant.tenant_id,
                    'name': tenant.tenant_name,
                    'description': tenant.tenant_description,
                    'target_market': tenant.target_market,
                    'created_at': tenant.created_at,
                    'updated_at': tenant.updated_at
                },
                'competitors': [
                    {
                        'id': comp.id,
                        'display_name': comp.display_name,
                        'primary_url': comp.primary_url,
                        'brief_description': comp.brief_description
                    }
                    for comp in competitors
                ],
                'tasks': [
                    {
                        'id': task.id,
                        'status': task.status,
                        'created_at': task.created_at,
                        'completed_at': task.completed_at
                    }
                    for task in tasks
                ],
                'statistics': {
                    'total_competitors': len(competitors),
                    'total_tasks': len(tasks)
                }
            }
    except Exception as e:
        logger.error(f"获取租户分析历史失败: {e}")
        return {'error': str(e)}

if __name__ == "__main__":
    # 初始化数据库（如果需要）
    if check_database_connection():
        init_db()
        logger.info("数据库连接正常")
    else:
        logger.warning("数据库连接失败，某些功能可能不可用")
    
    # ===== 选择运行模式 =====
    
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "legacy":
            # 传统模式（无持久化）
            logger.info("运行传统模式")
            asyncio.run(run_opp_agent())
        
        elif mode == "enhanced":
            # 增强模式（带持久化）
            company = sys.argv[2] if len(sys.argv) > 2 else "FL Studio"
            logger.info(f"运行增强模式: {company}")
            result = asyncio.run(run_opp_agent_with_enhanced_persistence(company, enable_caching=True))
            
        elif mode == "tracking":
            # 持续跟踪模式
            urls = [
                "https://news.ycombinator.com/", 
                "https://www.ycombinator.com/",
                "https://www.stripe.com/",
            ]
            logger.info("运行持续跟踪模式")
            asyncio.run(run_ongoing_opp_agent_with_enhanced_persistence(urls, "test_tracking"))
        
        elif mode == "stats":
            # 系统统计模式
            logger.info("获取系统统计")
            async def show_stats():
                stats = await get_enhanced_system_stats()
                print("=== 系统统计 ===")
                for key, value in stats.items():
                    print(f"{key}: {value}")
            
            asyncio.run(show_stats())
        
        elif mode == "cleanup":
            # 清理模式
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            logger.info(f"清理系统数据 (保留 {days} 天)")
            result = asyncio.run(cleanup_system_data(days))
            print(f"清理结果: {result}")
        
        else:
            print("未知模式，可用模式:")
            print("  legacy   - 传统模式")
            print("  enhanced - 增强模式")
            print("  tracking - 持续跟踪")
            print("  stats    - 系统统计")
            print("  cleanup  - 数据清理")
    
    else:
        # 默认：增强模式
        logger.info("运行默认增强模式")
        async def run_default():
            result = await run_opp_agent_with_enhanced_persistence("FL Studio", enable_caching=True)
            
            # 显示系统统计
            print("\n=== 系统统计 ===")
            stats_result = await get_enhanced_system_stats()
            for key, value in stats_result.items():
                print(f"{key}: {value}")
        
        asyncio.run(run_default())
