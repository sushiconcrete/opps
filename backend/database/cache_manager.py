# backend/database/cache_manager.py
"""
完全修复版缓存管理器 - 正确处理UUID外键关系
问题：change_detection_cache.competitor_id 引用 competitors.id (UUID)，而非 competitors.competitor_id
解决：映射域名到UUID，使用UUID插入缓存表
"""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class UUIDCompetitorResolver:
    """UUID竞争对手解析器 - 正确处理域名到UUID的映射"""
    
    @staticmethod
    def get_competitor_uuid_by_domain(db, domain_id: str, url: str = None) -> Optional[str]:
        """通过域名ID获取competitor的UUID（用于外键）"""
        from . import models
        from sqlalchemy import or_
        
        try:
            # 方法1：直接通过competitor_id查找
            competitor = db.query(models.Competitor).filter(
                models.Competitor.competitor_id == domain_id
            ).first()
            
            if competitor:
                logger.debug(f"通过competitor_id找到UUID: {domain_id} -> {competitor.id}")
                return competitor.id
            
            # 方法2：通过URL查找
            if url:
                competitor = db.query(models.Competitor).filter(
                    models.Competitor.primary_url == url
                ).first()
                
                if competitor:
                    logger.debug(f"通过URL找到UUID: {url} -> {competitor.id}")
                    return competitor.id
            
            # 方法3：模糊匹配
            if url:
                domain = urlparse(url).netloc.replace('www.', '')
                
                competitor = db.query(models.Competitor).filter(
                    or_(
                        models.Competitor.competitor_id.like(f'%{domain}%'),
                        models.Competitor.primary_url.like(f'%{domain}%')
                    )
                ).first()
                
                if competitor:
                    logger.debug(f"通过模糊匹配找到UUID: {domain} -> {competitor.id}")
                    return competitor.id
            
            logger.warning(f"未找到匹配的competitor UUID: domain_id={domain_id}, url={url}")
            return None
            
        except Exception as e:
            logger.error(f"获取competitor UUID失败: {e}")
            return None
    
    @staticmethod
    def ensure_competitor_exists_and_get_uuid(db, domain_id: str, url: str) -> Optional[str]:
        """确保competitor存在并返回UUID"""
        from . import models
        
        try:
            # 首先尝试查找现有记录
            uuid = UUIDCompetitorResolver.get_competitor_uuid_by_domain(db, domain_id, url)
            if uuid:
                return uuid
            
            # 如果没找到，创建新的competitor
            display_name_map = {
                'google.com': 'Google',
                'alibaba.com': 'Alibaba Group',
                'tencent.com': 'Tencent',
                'facebook.com': 'Facebook',
                'amazon.com': 'Amazon',
                'microsoft.com': 'Microsoft',
                'apple.com': 'Apple',
                'netflix.com': 'Netflix'
            }
            
            new_competitor = models.Competitor(
                competitor_id=domain_id,
                display_name=display_name_map.get(domain_id, domain_id.split('.')[0].title()),
                primary_url=url,
                brief_description=f'Auto-created for caching: {domain_id}',
                demographics='',
                source='cache-uuid-fix',
                extra_data={
                    'created_from': 'uuid_fix',
                    'auto_created': True,
                    'created_at': datetime.utcnow().isoformat()
                }
            )
            
            db.add(new_competitor)
            db.commit()
            db.refresh(new_competitor)
            
            logger.info(f"为缓存创建新competitor: {domain_id} -> UUID: {new_competitor.id}")
            return new_competitor.id
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建competitor失败: {e}")
            return None


class ChangeDetectionCacheManager:
    """变化检测缓存管理器 - UUID修复版"""
    
    def __init__(self, default_ttl_hours: int = 72):
        self.default_ttl_hours = default_ttl_hours
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 3600
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, 
            thread_name_prefix="cache-uuid-fix"
        )
    
    async def get_cached_results(
        self, 
        url_competitor_pairs: List[Tuple[str, str]]
    ) -> Dict[str, Dict[str, Any]]:
        """批量获取缓存的变化检测结果 - UUID修复版"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor, 
                self._sync_get_cached_results_uuid_fixed, 
                url_competitor_pairs
            )
        except Exception as e:
            logger.error(f"获取缓存结果失败: {e}")
            return {}
    
    def _sync_get_cached_results_uuid_fixed(
        self, 
        url_competitor_pairs: List[Tuple[str, str]]
    ) -> Dict[str, Dict[str, Any]]:
        """同步版本的缓存获取 - 使用正确的UUID查询"""
        try:
            from .connection import get_db_session
            from . import models
            
            results = {}
            
            with get_db_session() as db:
                for url, domain_id in url_competitor_pairs:
                    try:
                        # 获取正确的UUID
                        competitor_uuid = UUIDCompetitorResolver.get_competitor_uuid_by_domain(
                            db, domain_id, url
                        )
                        
                        if not competitor_uuid:
                            logger.debug(f"跳过缓存查询，competitor不存在: {domain_id}")
                            continue
                        
                        # 使用cache_key查询（保持原有逻辑）
                        cache_key = models.ChangeDetectionCache.generate_cache_key(domain_id, url)
                        
                        cached_record = db.query(models.ChangeDetectionCache).filter(
                            models.ChangeDetectionCache.cache_key == cache_key,
                            models.ChangeDetectionCache.expires_at > datetime.utcnow()
                        ).first()
                        
                        if cached_record:
                            results[url] = cached_record.result_data
                            logger.debug(f"缓存命中: {url}")
                    
                    except Exception as e:
                        logger.warning(f"查询单个缓存记录失败 {url}: {e}")
                        continue
            
            logger.info(f"缓存查询完成: {len(results)}/{len(url_competitor_pairs)} 命中")
            return results
                
        except Exception as e:
            logger.error(f"同步获取缓存结果失败: {e}")
            return {}
    
    async def cache_results(
        self, 
        results: Dict[str, Dict[str, Any]],
        competitor_id_mapping: Dict[str, str],
        ttl_hours: Optional[int] = None
    ) -> List[str]:
        """批量缓存变化检测结果 - UUID修复版"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor,
                self._sync_cache_results_uuid_fixed,
                results,
                competitor_id_mapping,
                ttl_hours
            )
        except Exception as e:
            logger.error(f"缓存结果失败: {e}")
            return []
    
    def _sync_cache_results_uuid_fixed(
        self, 
        results: Dict[str, Dict[str, Any]], 
        competitor_id_mapping: Dict[str, str], 
        ttl_hours: Optional[int]
    ) -> List[str]:
        """同步版本的结果缓存 - 修复版：使用正确的UUID"""
        ttl = ttl_hours or self.default_ttl_hours
        cached_urls = []
        
        if not results or not competitor_id_mapping:
            logger.info("没有结果需要缓存")
            return cached_urls
        
        logger.info(f"开始缓存 {len(results)} 个结果（UUID修复版）")
        
        # 逐个处理每个缓存项
        for url, result_data in results.items():
            try:
                domain_id = competitor_id_mapping.get(url)
                
                if not domain_id:
                    logger.warning(f"跳过无映射的URL: {url}")
                    continue
                
                # 为每个缓存项创建独立的数据库会话
                from .connection import get_db_session
                from . import models
                
                with get_db_session() as db:
                    # 关键修复：获取正确的UUID用于外键
                    competitor_uuid = UUIDCompetitorResolver.ensure_competitor_exists_and_get_uuid(
                        db, domain_id, url
                    )
                    
                    if not competitor_uuid:
                        logger.error(f"无法获取competitor UUID: {domain_id}")
                        continue
                    
                    # 创建或更新缓存记录
                    expires_at = datetime.utcnow() + timedelta(hours=ttl)
                    cache_key = models.ChangeDetectionCache.generate_cache_key(domain_id, url)
                    
                    # 检查现有缓存
                    existing_cache = db.query(models.ChangeDetectionCache).filter(
                        models.ChangeDetectionCache.cache_key == cache_key
                    ).first()
                    
                    if existing_cache:
                        # 更新现有缓存
                        existing_cache.result_data = result_data
                        existing_cache.expires_at = expires_at
                        existing_cache.created_at = datetime.utcnow()
                        # 确保使用正确的UUID
                        existing_cache.competitor_id = competitor_uuid
                        logger.debug(f"更新缓存: {url} -> UUID: {competitor_uuid}")
                    else:
                        # 创建新缓存记录 - 关键修复：使用UUID而不是域名
                        cache_record = models.ChangeDetectionCache(
                            competitor_id=competitor_uuid,  # ← 使用UUID，不是域名字符串
                            url=url,
                            cache_key=cache_key,
                            result_data=result_data,
                            expires_at=expires_at
                        )
                        db.add(cache_record)
                        logger.debug(f"创建缓存: {url} -> UUID: {competitor_uuid}")
                    
                    # 提交缓存记录
                    try:
                        db.commit()
                        cached_urls.append(url)
                        logger.debug(f"成功缓存: {url}")
                    except Exception as e:
                        db.rollback()
                        logger.error(f"缓存提交失败 {url}: {e}")
                        continue
            
            except Exception as e:
                logger.error(f"处理缓存项失败 {url}: {e}", exc_info=True)
                continue
        
        logger.info(f"缓存完成: 成功 {len(cached_urls)}/{len(results)} 个")
        return cached_urls
    
    async def cache_single_result(
        self, 
        url: str, 
        competitor_id: str, 
        result_data: Dict[str, Any],
        ttl_hours: Optional[int] = None
    ) -> bool:
        """缓存单个变化检测结果 - UUID修复版"""
        try:
            results = {url: result_data}
            competitor_mapping = {url: competitor_id}
            cached_urls = await self.cache_results(
                results, 
                competitor_mapping, 
                ttl_hours
            )
            success = len(cached_urls) > 0
            if success:
                logger.info(f"成功缓存单个结果: {url}")
            else:
                logger.warning(f"缓存单个结果失败: {url}")
            return success
        except Exception as e:
            logger.error(f"缓存单个结果失败 {url}: {e}")
            return False
    
    async def cleanup_expired_cache(self) -> int:
        """清理所有过期的缓存记录"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, self._sync_cleanup_expired_cache)
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")
            return 0
    
    def _sync_cleanup_expired_cache(self) -> int:
        """同步版本的缓存清理"""
        try:
            from .connection import get_db_session
            from . import models
            
            with get_db_session() as db:
                deleted_count = db.query(models.ChangeDetectionCache).filter(
                    models.ChangeDetectionCache.expires_at <= datetime.utcnow()
                ).delete()
                
                db.commit()
                if deleted_count > 0:
                    logger.info(f"清理了 {deleted_count} 个过期缓存记录")
                return deleted_count
                
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")
            return 0
    
    async def start_background_cleanup(self):
        """启动后台清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            logger.info("后台清理任务已经在运行")
            return True
        
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("启动后台缓存清理任务（UUID修复版）")
        return True
    
    async def stop_background_cleanup(self):
        """停止后台清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("停止后台缓存清理任务")
        return True
    
    async def _cleanup_loop(self):
        """后台清理循环"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                deleted = await self.cleanup_expired_cache()
                if deleted > 0:
                    logger.info(f"后台清理删除了 {deleted} 个过期记录")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"缓存清理循环错误: {e}")
                await asyncio.sleep(300)  # 出错时等待5分钟
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, self._sync_get_cache_stats)
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {"error": str(e), "total_records": 0}
    
    def _sync_get_cache_stats(self) -> Dict[str, Any]:
        """同步版本的缓存统计"""
        try:
            from .connection import get_db_session
            from . import models
            from sqlalchemy import func
            
            with get_db_session() as db:
                total_records = db.query(func.count(models.ChangeDetectionCache.id)).scalar() or 0
                
                expired_records = db.query(func.count(models.ChangeDetectionCache.id)).filter(
                    models.ChangeDetectionCache.expires_at <= datetime.utcnow()
                ).scalar() or 0
                
                active_records = total_records - expired_records
                
                total_competitors = db.query(func.count(models.Competitor.id)).scalar() or 0
                auto_created_competitors = db.query(func.count(models.Competitor.id)).filter(
                    models.Competitor.source.like('cache-%')
                ).scalar() or 0
                
                return {
                    "total_records": total_records,
                    "active_records": active_records,
                    "expired_records": expired_records,
                    "total_competitors": total_competitors,
                    "auto_created_competitors": auto_created_competitors,
                    "default_ttl_hours": self.default_ttl_hours,
                    "status": "healthy",
                    "version": "uuid-fixed-final"
                }
                
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {
                "error": str(e), 
                "total_records": 0, 
                "status": "error",
                "version": "uuid-fixed-final"
            }
    
    async def validate_cache_integrity(self) -> Dict[str, Any]:
        """验证缓存完整性 - UUID修复版"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, self._sync_validate_cache_integrity)
        except Exception as e:
            logger.error(f"验证缓存完整性失败: {e}")
            return {"error": str(e)}
    
    def _sync_validate_cache_integrity(self) -> Dict[str, Any]:
        """同步版本的缓存完整性验证"""
        try:
            from .connection import get_db_session
            from . import models
            from sqlalchemy import text
            
            with get_db_session() as db:
                # 检查孤儿缓存记录（现在应该检查UUID外键）
                orphan_cache_query = text("""
                    SELECT COUNT(*) 
                    FROM change_detection_cache cdc 
                    LEFT JOIN competitors c ON cdc.competitor_id = c.id 
                    WHERE c.id IS NULL
                """)
                
                orphan_count = db.execute(orphan_cache_query).scalar() or 0
                
                # 获取所有缓存记录的competitor_id统计
                cache_records = db.query(models.ChangeDetectionCache).all()
                cache_competitor_uuids = [record.competitor_id for record in cache_records]
                
                # 验证这些UUID确实存在于competitors表中
                valid_count = 0
                invalid_uuids = []
                
                for uuid in cache_competitor_uuids:
                    exists = db.query(models.Competitor).filter(
                        models.Competitor.id == uuid
                    ).first()
                    
                    if exists:
                        valid_count += 1
                    else:
                        invalid_uuids.append(uuid)
                
                return {
                    "total_cache_records": len(cache_records),
                    "orphan_cache_records": orphan_count,
                    "valid_uuid_references": valid_count,
                    "invalid_uuid_references": invalid_uuids,
                    "integrity_status": "healthy" if orphan_count == 0 and len(invalid_uuids) == 0 else "issues_found",
                    "timestamp": datetime.utcnow().isoformat(),
                    "validation_method": "uuid_based"
                }
                
        except Exception as e:
            logger.error(f"验证缓存完整性失败: {e}")
            return {"error": str(e), "integrity_status": "error"}


class ContentCacheManager:
    """内容缓存管理器 - 保持原有功能"""
    
    def __init__(self):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, 
            thread_name_prefix="content-uuid-fix"
        )
    
    async def get_previous_content(self, urls: List[str], tag: str) -> Dict[str, str]:
        """获取URLs的上次保存的内容"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor, 
                self._sync_get_previous_content, 
                urls, 
                tag
            )
        except Exception as e:
            logger.error(f"获取历史内容失败: {e}")
            return {}
    
    def _sync_get_previous_content(self, urls: List[str], tag: str) -> Dict[str, str]:
        """同步版本的获取内容"""
        try:
            from .connection import get_db_session
            from . import models
            from sqlalchemy import func, and_
            
            with get_db_session() as db:
                subquery = db.query(
                    models.ContentStorage.url,
                    func.max(models.ContentStorage.created_at).label('latest_created')
                ).filter(
                    and_(
                        models.ContentStorage.url.in_(urls),
                        models.ContentStorage.tag == tag
                    )
                ).group_by(models.ContentStorage.url).subquery()
                
                records = db.query(models.ContentStorage).join(
                    subquery,
                    and_(
                        models.ContentStorage.url == subquery.c.url,
                        models.ContentStorage.created_at == subquery.c.latest_created
                    )
                ).all()
                
                return {record.url: record.content for record in records}
                
        except Exception as e:
            logger.error(f"获取历史内容失败: {e}")
            return {}
    
    async def save_current_content(self, content_mapping: Dict[str, str], tag: str) -> bool:
        """保存当前内容"""
        try:
            loop = asyncio.get_event_loop()
            records = await loop.run_in_executor(
                self._executor,
                self._sync_save_current_content,
                content_mapping,
                tag
            )
            success = len(records) > 0 or len(content_mapping) == 0
            logger.info(f"保存了 {len(records)} 条内容记录，标签: '{tag}'")
            return success
        except Exception as e:
            logger.error(f"保存当前内容失败: {e}")
            return False
    
    def _sync_save_current_content(self, content_mapping: Dict[str, str], tag: str) -> list:
        """同步版本的保存内容"""
        try:
            from .connection import get_db_session
            from . import models
            from sqlalchemy import and_
            
            records = []
            
            with get_db_session() as db:
                for url, content in content_mapping.items():
                    if not content:
                        continue
                        
                    content_hash = models.ContentStorage.generate_content_hash(content)
                    
                    existing = db.query(models.ContentStorage).filter(
                        and_(
                            models.ContentStorage.url == url,
                            models.ContentStorage.tag == tag,
                            models.ContentStorage.content_hash == content_hash
                        )
                    ).first()
                    
                    if not existing:
                        record = models.ContentStorage(
                            url=url,
                            tag=tag,
                            content_hash=content_hash,
                            content=content
                        )
                        db.add(record)
                        records.append(record)
                
                if records:
                    db.commit()
                    for record in records:
                        db.refresh(record)
            
            return records
                
        except Exception as e:
            logger.error(f"同步保存内容失败: {e}")
            return []


# 创建修复版缓存管理器实例
change_detection_cache = ChangeDetectionCacheManager()
content_cache = ContentCacheManager()

# 缓存系统验证函数
async def validate_cache_system():
    """验证修复后的缓存系统"""
    try:
        logger.info("开始验证UUID修复版缓存系统...")
        
        # 获取基础统计
        stats = await change_detection_cache.get_cache_stats()
        logger.info(f"缓存统计: {stats}")
        
        # 验证完整性
        integrity = await change_detection_cache.validate_cache_integrity()
        logger.info(f"完整性检查: {integrity}")
        
        status = "healthy"
        if integrity.get('orphan_cache_records', 0) > 0:
            logger.warning(f"发现 {integrity['orphan_cache_records']} 个孤儿缓存记录")
            status = "needs_attention"
        
        if len(integrity.get('invalid_uuid_references', [])) > 0:
            logger.warning(f"发现无效UUID引用: {integrity['invalid_uuid_references']}")
            status = "needs_attention"
        
        return {
            "status": status,
            "stats": stats,
            "integrity": integrity,
            "version": "uuid-fixed-final"
        }
        
    except Exception as e:
        logger.error(f"验证缓存系统失败: {e}")
        return {"status": "error", "error": str(e)}

# 导出所有必要的组件
__all__ = [
    'ChangeDetectionCacheManager',
    'ContentCacheManager', 
    'UUIDCompetitorResolver',
    'change_detection_cache',
    'content_cache',
    'validate_cache_system'
]