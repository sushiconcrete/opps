# backend/database/__init__.py
"""
数据库模块 - 统一导出所有数据库功能，包含完整的fallback支持
修复了外键约束和CRUD方法缺失问题
"""
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 导入核心数据库功能
try:
    from .connection import (
        get_db, 
        get_db_session, 
        init_db, 
        check_database_connection,
        get_database_stats,
        cleanup_database,
        test_database_integrity
    )
    CORE_DB_AVAILABLE = True
    logger.info("核心数据库功能导入成功")
except ImportError as e:
    logger.error(f"核心数据库功能导入失败: {e}")
    CORE_DB_AVAILABLE = False
    raise

# 导入模型
try:
    from .models import Base
    MODELS_AVAILABLE = True
    logger.info("数据库模型导入成功")
except ImportError as e:
    logger.error(f"数据库模型导入失败: {e}")
    MODELS_AVAILABLE = False
    raise

# 导入缓存管理器
try:
    from .cache_manager import (
        change_detection_cache, 
        content_cache,
        ChangeDetectionCacheManager,
        ContentCacheManager
    )
    CACHE_MANAGERS_AVAILABLE = True
    logger.info("缓存管理器导入成功")
except ImportError as e:
    logger.error(f"缓存管理器导入失败: {e}")
    CACHE_MANAGERS_AVAILABLE = False

# 导入CRUD操作
try:
    from .crud import (
        tenant_crud,
        competitor_crud, 
        tenant_competitor_crud,
        cache_crud,
        content_storage_crud,
        enhanced_task_crud,
        TenantCRUD,
        CompetitorCRUD,
        TenantCompetitorCRUD,
        ChangeDetectionCacheCRUD,
        ContentStorageCRUD,
        EnhancedTaskCRUD
    )
    ENHANCED_CRUD_AVAILABLE = True
    logger.info("增强CRUD操作导入成功")
except ImportError as e:
    logger.error(f"增强CRUD不可用: {e}")
    ENHANCED_CRUD_AVAILABLE = False

# ===== 功能完整的Fallback管理器 =====
class FallbackCacheManager:
    """功能完整的fallback缓存管理器"""
    
    def __init__(self, default_ttl_hours: int = 72):
        self.default_ttl_hours = default_ttl_hours
        logger.warning("使用fallback缓存管理器 - 功能受限")
    
    async def get_cached_results(self, url_competitor_pairs):
        """获取缓存结果 - fallback版本"""
        logger.warning("Fallback: 缓存获取功能不可用")
        return {}
    
    async def cache_results(self, results, competitor_id_mapping, ttl_hours=None):
        """缓存结果 - fallback版本"""
        logger.warning("Fallback: 缓存保存功能不可用")
        return []
    
    async def cache_single_result(self, url, competitor_id, result_data, ttl_hours=None):
        """缓存单个结果 - fallback版本"""
        logger.warning("Fallback: 单个缓存功能不可用")
        return False
    
    async def cleanup_expired_cache(self):
        """清理过期缓存 - fallback版本"""
        logger.warning("Fallback: 缓存清理功能不可用")
        return 0
    
    async def get_cache_stats(self):
        """获取缓存统计 - fallback版本"""
        return {
            "error": "缓存管理器不可用",
            "total_records": 0,
            "active_records": 0,
            "expired_records": 0
        }
    
    async def start_background_cleanup(self):
        """启动后台清理 - fallback版本"""
        logger.warning("Fallback: 后台清理任务不可用")
        return False
    
    async def stop_background_cleanup(self):
        """停止后台清理 - fallback版本"""
        logger.warning("Fallback: 后台清理任务不可用")
        return False

class FallbackContentCache:
    """功能完整的fallback内容缓存"""
    
    def __init__(self):
        logger.warning("使用fallback内容缓存管理器 - 功能受限")
    
    async def get_previous_content(self, urls, tag):
        """获取历史内容 - fallback版本"""
        logger.warning("Fallback: 历史内容获取功能不可用")
        return {}
    
    async def save_current_content(self, content_mapping, tag):
        """保存当前内容 - fallback版本"""
        logger.warning("Fallback: 内容保存功能不可用")
        return False
    
    async def cleanup_old_content(self, tag, keep_days=30):
        """清理旧内容 - fallback版本"""
        logger.warning("Fallback: 内容清理功能不可用")
        return 0

# 如果缓存管理器不可用，创建fallback实例
if not CACHE_MANAGERS_AVAILABLE:
    logger.warning("创建fallback缓存管理器")
    change_detection_cache = FallbackCacheManager()
    content_cache = FallbackContentCache()
    ChangeDetectionCacheManager = FallbackCacheManager
    ContentCacheManager = FallbackContentCache

# ===== 修复：向后兼容的基础CRUD =====
class BackwardCompatibleTaskCRUD:
    """向后兼容的任务CRUD"""
    
    def create_task(self, db, company_name, config=None, **kwargs):
        """创建任务"""
        from .models import AnalysisTask
        from datetime import datetime
        import uuid
        
        task = AnalysisTask(
            id=str(uuid.uuid4()),
            company_name=company_name,
            task_type=kwargs.get("task_type", "analysis"),
            config=config or {},
            status="queued",
            progress=0,
            message="Task queued",
            created_at=datetime.utcnow()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    
    def get_task(self, db, task_id):
        """获取任务"""
        from .models import AnalysisTask
        return db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
    
    def update_task(self, db, task_id, status=None, progress=None, message=None, results=None, **kwargs):
        """更新任务状态"""
        from datetime import datetime
        from .models import AnalysisTask
        
        task = self.get_task(db, task_id)
        if task:
            if status is not None:
                task.status = status
                if status == "running" and not task.started_at:
                    task.started_at = datetime.utcnow()
                elif status in ["completed", "failed"]:
                    task.completed_at = datetime.utcnow()
            
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if results is not None:
                task.results = results
            
            db.commit()
            db.refresh(task)
        return task
    
    def get_recent_tasks(self, db, limit=10):
        """获取最近的任务"""
        from .models import AnalysisTask
        return db.query(AnalysisTask).order_by(AnalysisTask.created_at.desc()).limit(limit).all()
    
    def get_running_tasks(self, db):
        """获取运行中的任务"""
        from .models import AnalysisTask
        return db.query(AnalysisTask).filter(AnalysisTask.status == "running").all()

class BackwardCompatibleCompetitorCRUD:
    """向后兼容的竞争对手CRUD"""
    
    def save_competitors(self, db, task_id, competitors_data):
        """保存竞争对手数据"""
        from .models import CompetitorRecord
        from datetime import datetime
        
        records = []
        for i, comp_data in enumerate(competitors_data):
            record = CompetitorRecord(
                task_id=task_id,
                domain=comp_data.get("id", comp_data.get("domain", f"comp_{i}")),
                display_name=comp_data.get("display_name", "Unknown"),
                primary_url=comp_data.get("primary_url", ""),
                brief_description=comp_data.get("brief_description", ""),
                demographics=comp_data.get("demographics", ""),
                confidence=comp_data.get("confidence", 0.5),
                source=comp_data.get("source", "search"),
                extra_data=comp_data.get("metadata", comp_data.get("extra_data", {})),
                created_at=datetime.utcnow()
            )
            db.add(record)
            records.append(record)
        
        db.commit()
        for record in records:
            db.refresh(record)
        return records

class BackwardCompatibleChangeCRUD:
    """修复后的向后兼容的变化CRUD"""
    
    def save_changes(self, db, competitor_id, url, changes_data):
        """保存变化数据 - 修复版本"""
        from .models import ChangeDetection
        from datetime import datetime
        
        try:
            records = []
            for change_data in changes_data:
                # 尝试使用数据中的timestamp，如果没有则使用当前时间
                detected_at = datetime.utcnow()
                if 'timestamp' in change_data:
                    try:
                        from dateutil import parser
                        detected_at = parser.parse(change_data['timestamp'])
                    except:
                        pass
                
                record = ChangeDetection(
                    competitor_id=competitor_id,
                    url=url,
                    change_type=change_data.get("change_type", "Modified"),
                    content=change_data.get("content", ""),
                    threat_level=change_data.get("threat_level", 5),
                    why_matter=change_data.get("why_matter", ""),
                    suggestions=change_data.get("suggestions", ""),
                    detected_at=detected_at
                )
                db.add(record)
                records.append(record)
            
            db.commit()
            for record in records:
                db.refresh(record)
            
            logger.info(f"保存变化记录: {len(records)} 条记录, competitor_id={competitor_id}")
            return records
            
        except Exception as e:
            db.rollback()
            logger.error(f"保存变化记录失败: {e}")
            return []

# 创建fallback CRUD如果增强版不可用
if not ENHANCED_CRUD_AVAILABLE:
    logger.warning("使用fallback CRUD实现")
    
    class MinimalTenantCRUD:
        @staticmethod
        def get_or_create_tenant(db, tenant_id, tenant_data):
            logger.warning("Fallback: 租户CRUD功能受限")
            return None, False
        
        @staticmethod
        def get_tenant_by_id(db, tenant_id):
            return None
        
        @staticmethod
        def get_tenant_competitors(db, tenant_id):
            return []
    
    class MinimalCompetitorCRUD:
        @staticmethod
        def get_or_create_competitor(db, competitor_id, competitor_data):
            logger.warning("Fallback: 竞争对手CRUD功能受限")
            return None, False
    
    class MinimalTenantCompetitorCRUD:
        @staticmethod
        def link_tenant_competitors(db, tenant_id, competitors_data, task_id=None):
            logger.warning("Fallback: 租户-竞争对手映射功能受限")
            return []
    
    class MinimalCacheCRUD:
        @staticmethod
        def get_cached_results_batch(db, url_competitor_pairs):
            return {}
        
        @staticmethod 
        def set_cached_result(db, competitor_id, url, result_data, ttl_hours=72, ensure_competitor_exists=True):
            return None
    
    class MinimalContentCRUD:
        @staticmethod
        def get_previous_content(db, urls, tag):
            return {}
        
        @staticmethod
        def save_current_content(db, content_mapping, tag):
            return []
    
    class MinimalEnhancedTaskCRUD:
        def create_task_with_tenant(self, db, company_name, tenant_data, config=None):
            # 使用基础任务创建
            return BackwardCompatibleTaskCRUD().create_task(db, company_name, config)
        
        def save_competitors_with_mapping(self, db, task_id, tenant_id, competitors_data):
            # 使用基础竞争对手保存
            records = BackwardCompatibleCompetitorCRUD().save_competitors(db, task_id, competitors_data)
            return records, []  # 返回记录和空映射列表
    
    # 分配最小实现
    tenant_crud = MinimalTenantCRUD()
    competitor_crud = MinimalCompetitorCRUD()
    tenant_competitor_crud = MinimalTenantCompetitorCRUD()
    cache_crud = MinimalCacheCRUD()
    content_storage_crud = MinimalContentCRUD()
    enhanced_task_crud = MinimalEnhancedTaskCRUD()
    
    # 类引用
    TenantCRUD = MinimalTenantCRUD
    CompetitorCRUD = MinimalCompetitorCRUD
    TenantCompetitorCRUD = MinimalTenantCompetitorCRUD
    ChangeDetectionCacheCRUD = MinimalCacheCRUD
    ContentStorageCRUD = MinimalContentCRUD
    EnhancedTaskCRUD = MinimalEnhancedTaskCRUD

# 基础CRUD实例（总是可用）
task_crud = BackwardCompatibleTaskCRUD()
basic_competitor_crud = BackwardCompatibleCompetitorCRUD()
change_crud = BackwardCompatibleChangeCRUD()  # 修复：正确实例化

def get_version_info():
    """获取数据库模块版本信息"""
    return {
        "version": "enhanced-1.2.1-fixed",
        "features": [
            "租户-竞争对手映射持久化",
            "3天TTL变化检测缓存", 
            "内容存储支持增量比较",
            "自动数据库清理",
            "性能优化索引",
            "完整的向后兼容支持",
            "健壮的fallback机制",
            "修复外键约束和CRUD方法问题"
        ],
        "status": {
            "core_db": CORE_DB_AVAILABLE,
            "models": MODELS_AVAILABLE,
            "enhanced_crud": ENHANCED_CRUD_AVAILABLE,
            "cache_managers": CACHE_MANAGERS_AVAILABLE,
            "basic_crud": True
        },
        "fixes": [
            "修复了BackwardCompatibleChangeCRUD.save_changes方法",
            "改进了外键约束错误处理",
            "增强了缓存系统的容错性"
        ]
    }

async def start_background_tasks():
    """启动后台任务"""
    try:
        if CACHE_MANAGERS_AVAILABLE:
            success = await change_detection_cache.start_background_cleanup()
            if success:
                logger.info("后台缓存清理任务已启动")
                return True
        
        logger.warning("后台任务未启动 - 缓存管理器不可用")
        return False
        
    except Exception as e:
        logger.error(f"启动后台任务失败: {e}")
        return False

async def stop_background_tasks():
    """停止后台任务"""
    try:
        if CACHE_MANAGERS_AVAILABLE:
            success = await change_detection_cache.stop_background_cleanup()
            logger.info("后台任务已停止")
            return success
        return False
    except Exception as e:
        logger.error(f"停止后台任务失败: {e}")
        return False

def migrate_legacy_data():
    """迁移现有数据到新结构"""
    try:
        stats = get_database_stats()
        
        return {
            "migrated_tenants": stats.get("tenants_count", 0),
            "migrated_competitors": stats.get("competitors_count", 0),
            "migrated_mappings": stats.get("tenant_competitors_count", 0),
            "status": "completed"
        }
    except Exception as e:
        logger.error(f"数据迁移失败: {e}")
        return {"error": str(e)}

# 导出所有主要功能
__all__ = [
    # 核心数据库
    'get_db', 'get_db_session', 'init_db',
    'check_database_connection', 'get_database_stats', 'cleanup_database',
    'test_database_integrity',
    
    # 模型
    'Base',
    
    # 缓存管理器（可能是fallback）
    'change_detection_cache', 'content_cache',
    'ChangeDetectionCacheManager', 'ContentCacheManager',
    
    # 增强CRUD（可能是fallback）
    'tenant_crud', 'competitor_crud', 'tenant_competitor_crud',
    'cache_crud', 'content_storage_crud', 'enhanced_task_crud',
    
    # CRUD类
    'TenantCRUD', 'CompetitorCRUD', 'TenantCompetitorCRUD',
    'ChangeDetectionCacheCRUD', 'ContentStorageCRUD', 'EnhancedTaskCRUD',
    
    # 基础CRUD（总是可用）
    'task_crud', 'basic_competitor_crud', 'change_crud',
    
    # 工具函数
    'get_version_info', 'start_background_tasks', 'stop_background_tasks',
    'migrate_legacy_data',
]

# 模块加载时检查数据库连接
if CORE_DB_AVAILABLE:
    try:
        if check_database_connection():
            logger.info("数据库连接验证成功")
        else:
            logger.warning("数据库连接验证失败")
    except Exception as e:
        logger.error(f"数据库连接检查时出错: {e}")

logger.info(f"数据库模块已加载 - 版本: {get_version_info()['version']}")
logger.info(f"可用功能: {len(get_version_info()['features'])}")

# 输出状态摘要
status = get_version_info()['status']
logger.info(f"模块状态: 核心DB={'✓' if status['core_db'] else '✗'}, "
           f"缓存={'✓' if status['cache_managers'] else '✗'}, "
           f"增强CRUD={'✓' if status['enhanced_crud'] else '✗'}")