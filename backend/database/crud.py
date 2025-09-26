# backend/database/crud.py
"""Enhanced CRUD operations with proper foreign key handling"""
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import desc, and_, or_, func
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from . import models
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

class TenantCRUD:
    """Tenant CRUD operations"""
    
    @staticmethod
    def get_or_create_tenant(
        db: Session, 
        tenant_id: str, 
        tenant_data: Dict[str, Any]
    ) -> Tuple[models.Tenant, bool]:
        """Get or create tenant record"""
        try:
            # Try to get existing tenant
            tenant = db.query(models.Tenant).filter(
                models.Tenant.tenant_id == tenant_id
            ).first()
            
            if tenant:
                # Update existing tenant
                tenant.tenant_name = tenant_data.get('tenant_name', tenant.tenant_name)
                tenant.tenant_url = tenant_data.get('tenant_url', tenant.tenant_url)
                tenant.tenant_description = tenant_data.get('tenant_description', tenant.tenant_description)
                tenant.target_market = tenant_data.get('target_market', tenant.target_market)
                tenant.key_features = tenant_data.get('key_features', tenant.key_features)
                tenant.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(tenant)
                return tenant, False
            
            # Create new tenant
            tenant = models.Tenant(
                tenant_id=tenant_id,
                tenant_name=tenant_data.get('tenant_name', 'Unknown'),
                tenant_url=tenant_data.get('tenant_url', ''),
                tenant_description=tenant_data.get('tenant_description', ''),
                target_market=tenant_data.get('target_market', ''),
                key_features=tenant_data.get('key_features', [])
            )
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            return tenant, True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error in get_or_create_tenant: {e}")
            raise
    
    @staticmethod
    def get_tenant_by_id(db: Session, tenant_id: str) -> Optional[models.Tenant]:
        """Get tenant by tenant_id"""
        return db.query(models.Tenant).filter(
            models.Tenant.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def get_tenant_competitors(db: Session, tenant_id: str) -> List[models.Competitor]:
        """获取租户的所有竞争对手 - 修复缺失方法"""
        try:
            tenant = TenantCRUD.get_tenant_by_id(db, tenant_id)
            if not tenant:
                return []
            
            # 通过关联表查询
            competitors = db.query(models.Competitor).join(
                models.TenantCompetitor
            ).filter(
                models.TenantCompetitor.tenant_id == tenant.id
            ).all()
            
            return competitors
            
        except Exception as e:
            logger.error(f"获取租户竞争对手失败: {e}")
            return []

class CompetitorCRUD:
    """Competitor CRUD operations"""
    
    @staticmethod
    def get_or_create_competitor(
        db: Session, 
        competitor_id: str, 
        competitor_data: Dict[str, Any]
    ) -> Tuple[models.Competitor, bool]:
        """Get or create competitor record"""
        try:
            competitor = db.query(models.Competitor).filter(
                models.Competitor.competitor_id == competitor_id
            ).first()
            
            if competitor:
                # Update existing
                competitor.display_name = competitor_data.get('display_name', competitor.display_name)
                competitor.primary_url = competitor_data.get('primary_url', competitor.primary_url)
                competitor.brief_description = competitor_data.get('brief_description', competitor.brief_description)
                competitor.demographics = competitor_data.get('demographics', competitor.demographics)
                competitor.source = competitor_data.get('source', competitor.source)
                competitor.extra_data = competitor_data.get('extra_data', competitor.extra_data)
                competitor.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(competitor)
                return competitor, False
            
            # Create new competitor
            competitor = models.Competitor(
                competitor_id=competitor_id,
                display_name=competitor_data.get('display_name', 'Unknown'),
                primary_url=competitor_data.get('primary_url', ''),
                brief_description=competitor_data.get('brief_description', ''),
                demographics=competitor_data.get('demographics', ''),
                source=competitor_data.get('source', 'search'),
                extra_data=competitor_data.get('extra_data', {})
            )
            db.add(competitor)
            db.commit()
            db.refresh(competitor)
            return competitor, True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error in get_or_create_competitor: {e}")
            raise

class TenantCompetitorCRUD:
    """Tenant-Competitor relationship CRUD"""
    
    @staticmethod
    def link_tenant_competitors(
        db: Session,
        tenant_id: str,
        competitors_data: List[Dict[str, Any]],
        task_id: Optional[str] = None
    ) -> List[models.TenantCompetitor]:
        """Link tenant with competitors (idempotent)"""
        try:
            # Get tenant
            tenant = TenantCRUD.get_tenant_by_id(db, tenant_id)
            if not tenant:
                raise ValueError(f"Tenant {tenant_id} not found")
            
            created_links = []
            
            for comp_data in competitors_data:
                competitor_id = comp_data.get('id') or comp_data.get('competitor_id')
                if not competitor_id:
                    logger.warning(f"Skipping competitor without id: {comp_data}")
                    continue
                
                # Get or create competitor
                competitor, _ = CompetitorCRUD.get_or_create_competitor(
                    db, competitor_id, comp_data
                )
                
                # Check existing link
                existing_link = db.query(models.TenantCompetitor).filter(
                    and_(
                        models.TenantCompetitor.tenant_id == tenant.id,
                        models.TenantCompetitor.competitor_id == competitor.id
                    )
                ).first()
                
                if not existing_link:
                    # Create new link
                    link = models.TenantCompetitor(
                        tenant_id=tenant.id,
                        competitor_id=competitor.id,
                        task_id=task_id,
                        confidence=comp_data.get('confidence', 0.5)
                    )
                    db.add(link)
                    created_links.append(link)
                else:
                    # Update confidence
                    existing_link.confidence = max(
                        existing_link.confidence, 
                        comp_data.get('confidence', 0.5)
                    )
                    created_links.append(existing_link)
            
            db.commit()
            for link in created_links:
                db.refresh(link)
            
            return created_links
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error linking tenant competitors: {e}")
            raise

class ChangeDetectionCacheCRUD:
    """Change detection cache CRUD with proper foreign key handling"""
    
    @staticmethod
    def get_cached_result(
        db: Session, 
        competitor_id: str, 
        url: str
    ) -> Optional[models.ChangeDetectionCache]:
        """Get cached change detection result"""
        cache_key = models.ChangeDetectionCache.generate_cache_key(competitor_id, url)
        
        cache_record = db.query(models.ChangeDetectionCache).filter(
            and_(
                models.ChangeDetectionCache.cache_key == cache_key,
                models.ChangeDetectionCache.expires_at > datetime.utcnow()
            )
        ).first()
        
        return cache_record
    
    @staticmethod
    def set_cached_result(
        db: Session,
        competitor_id: str,
        url: str,
        result_data: Dict[str, Any],
        ttl_hours: int = 72,
        ensure_competitor_exists: bool = True
    ) -> models.ChangeDetectionCache:
        """Set cached change detection result with proper FK handling"""
        try:
            # Ensure competitor exists if requested
            if ensure_competitor_exists:
                competitor = db.query(models.Competitor).filter(
                    models.Competitor.competitor_id == competitor_id
                ).first()
                
                if not competitor:
                    # Create minimal competitor record
                    competitor_data = {
                        'display_name': f'Auto-created for {competitor_id}',
                        'primary_url': url,
                        'brief_description': '',
                        'demographics': '',
                        'source': 'cache'
                    }
                    competitor, _ = CompetitorCRUD.get_or_create_competitor(
                        db, competitor_id, competitor_data
                    )
                    logger.info(f"Auto-created competitor {competitor_id} for caching")
            
            cache_key = models.ChangeDetectionCache.generate_cache_key(competitor_id, url)
            expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
            
            # Check existing cache
            existing = db.query(models.ChangeDetectionCache).filter(
                models.ChangeDetectionCache.cache_key == cache_key
            ).first()
            
            if existing:
                # Update existing
                existing.result_data = result_data
                existing.expires_at = expires_at
                existing.created_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return existing
            
            # Create new cache record
            cache_record = models.ChangeDetectionCache(
                competitor_id=competitor_id,
                url=url,
                cache_key=cache_key,
                result_data=result_data,
                expires_at=expires_at
            )
            db.add(cache_record)
            db.commit()
            db.refresh(cache_record)
            return cache_record
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error setting cached result: {e}")
            raise
    
    @staticmethod
    def get_cached_results_batch(
        db: Session,
        url_competitor_pairs: List[Tuple[str, str]]
    ) -> Dict[str, Dict[str, Any]]:
        """Batch get cached results"""
        try:
            cache_keys = [
                models.ChangeDetectionCache.generate_cache_key(comp_id, url)
                for url, comp_id in url_competitor_pairs
            ]
            
            cached_records = db.query(models.ChangeDetectionCache).filter(
                and_(
                    models.ChangeDetectionCache.cache_key.in_(cache_keys),
                    models.ChangeDetectionCache.expires_at > datetime.utcnow()
                )
            ).all()
            
            results = {}
            for record in cached_records:
                results[record.url] = record.result_data
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting batch cached results: {e}")
            return {}
    
    @staticmethod
    def cleanup_expired_cache(db: Session) -> int:
        """Clean expired cache records"""
        try:
            deleted_count = db.query(models.ChangeDetectionCache).filter(
                models.ChangeDetectionCache.expires_at <= datetime.utcnow()
            ).delete()
            
            db.commit()
            return deleted_count
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error cleaning expired cache: {e}")
            return 0

class ContentStorageCRUD:
    """Content storage CRUD operations"""
    
    @staticmethod
    def get_previous_content(
        db: Session, 
        urls: List[str], 
        tag: str
    ) -> Dict[str, str]:
        """Get previous content for URLs"""
        try:
            # Get latest content for each URL with the given tag
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
            logger.error(f"Error getting previous content: {e}")
            return {}
    
    @staticmethod
    def save_current_content(
        db: Session,
        content_mapping: Dict[str, str],
        tag: str
    ) -> List[models.ContentStorage]:
        """Save current content with deduplication"""
        try:
            records = []
            
            for url, content in content_mapping.items():
                if not content:
                    continue
                    
                content_hash = models.ContentStorage.generate_content_hash(content)
                
                # Check for duplicate content
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
            db.rollback()
            logger.error(f"Error saving current content: {e}")
            return []

class EnhancedTaskCRUD:
    """Enhanced task CRUD with integration support"""
    
    @staticmethod
    def create_task_with_tenant(
        db: Session,
        company_name: str,
        tenant_data: Dict[str, Any],
        config: dict = None
    ) -> models.AnalysisTask:
        """Create task and link with tenant"""
        try:
            # Create or get tenant
            tenant_id = tenant_data.get('tenant_id', company_name.lower().replace(' ', '_'))
            tenant, _ = TenantCRUD.get_or_create_tenant(db, tenant_id, tenant_data)
            
            # Create task
            task = models.AnalysisTask(
                company_name=company_name,
                task_type="analysis",
                config=config or {},
                status="queued",
                progress=0,
                message="Task queued"
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            
            return task
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating task with tenant: {e}")
            raise
    
    @staticmethod
    def save_competitors_with_mapping(
        db: Session,
        task_id: str,
        tenant_id: str,
        competitors: List[dict]
    ) -> Tuple[List[models.CompetitorRecord], List[models.TenantCompetitor]]:
        """Save competitors and create mappings"""
        try:
            # Save competitor records (backward compatibility)
            competitor_records = []
            for comp_data in competitors:
                record = models.CompetitorRecord(
                    task_id=task_id,
                    domain=comp_data.get("id", comp_data.get("domain", "unknown")),
                    display_name=comp_data.get("display_name", "Unknown"),
                    primary_url=comp_data.get("primary_url", ""),
                    brief_description=comp_data.get("brief_description", ""),
                    demographics=comp_data.get("demographics", ""),
                    confidence=comp_data.get("confidence", 0.5),
                    source=comp_data.get("source", "search"),
                    extra_data=comp_data.get("metadata", comp_data.get("extra_data", {}))
                )
                db.add(record)
                competitor_records.append(record)
            
            # Create tenant-competitor mappings
            tenant_competitor_links = TenantCompetitorCRUD.link_tenant_competitors(
                db, tenant_id, competitors, task_id
            )
            
            db.commit()
            for record in competitor_records:
                db.refresh(record)
            
            return competitor_records, tenant_competitor_links
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving competitors with mapping: {e}")
            raise

class MonitorCRUD:
    """Monitor CRUD operations"""

    @staticmethod
    def list_monitors(db: Session, user_id: str, include_archived: bool = False) -> List[models.Monitor]:
        query = db.query(models.Monitor).options(
            selectinload(models.Monitor.latest_task),
            selectinload(models.Monitor.tracked_competitors).selectinload(models.MonitorCompetitor.competitor),
        ).filter(
            models.Monitor.user_id == user_id
        )
        if not include_archived:
            query = query.filter(
                models.Monitor.is_active.is_(True),
                models.Monitor.archived_at.is_(None)
            )
        return query.order_by(models.Monitor.created_at.desc()).all()

    @staticmethod
    def get_monitor(db: Session, monitor_id: str, user_id: str) -> Optional[models.Monitor]:
        return db.query(models.Monitor).options(
            selectinload(models.Monitor.latest_task),
            selectinload(models.Monitor.tracked_competitors).selectinload(models.MonitorCompetitor.competitor),
        ).filter(
            models.Monitor.id == monitor_id,
            models.Monitor.user_id == user_id
        ).first()

    @staticmethod
    def create_monitor(
        db: Session,
        user_id: str,
        url: str,
        name: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> models.Monitor:
        normalized_url = url.strip()
        monitor = models.Monitor(
            user_id=user_id,
            url=normalized_url,
            name=name or normalized_url,
            tenant_id=tenant_id,
            is_active=True
        )
        db.add(monitor)
        db.commit()
        db.refresh(monitor)
        return monitor

    @staticmethod
    def get_or_create_monitor(
        db: Session,
        user_id: str,
        url: str,
        name: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> models.Monitor:
        monitor = db.query(models.Monitor).filter(
            models.Monitor.user_id == user_id,
            models.Monitor.url == url.strip()
        ).first()
        if monitor:
            if name and monitor.name != name:
                monitor.name = name
            if tenant_id and monitor.tenant_id != tenant_id:
                monitor.tenant_id = tenant_id
            monitor.is_active = True
            monitor.archived_at = None
            monitor.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(monitor)
            return monitor
        return MonitorCRUD.create_monitor(db, user_id, url, name=name, tenant_id=tenant_id)

    @staticmethod
    def update_monitor_name(db: Session, monitor: models.Monitor, new_name: str) -> models.Monitor:
        monitor.name = new_name
        monitor.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(monitor)
        return monitor

    @staticmethod
    def deactivate_monitor(db: Session, monitor: models.Monitor) -> None:
        monitor.is_active = False
        monitor.archived_at = datetime.utcnow()
        monitor.updated_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def set_latest_task(db: Session, monitor: models.Monitor, task_id: str) -> None:
        monitor.latest_task_id = task_id
        monitor.last_run_at = datetime.utcnow()
        monitor.updated_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def attach_tenant(db: Session, monitor: models.Monitor, tenant: models.Tenant) -> None:
        monitor.tenant_id = tenant.id
        monitor.updated_at = datetime.utcnow()
        db.commit()


class MonitorCompetitorCRUD:
    """Monitor competitor tracking"""

    @staticmethod
    def set_tracking(
        db: Session,
        monitor_id: str,
        competitor_id: str,
        tracked: bool = True
    ) -> models.MonitorCompetitor:
        record = db.query(models.MonitorCompetitor).filter(
            models.MonitorCompetitor.monitor_id == monitor_id,
            models.MonitorCompetitor.competitor_id == competitor_id
        ).first()

        if record:
            record.tracked = tracked
            record.updated_at = datetime.utcnow()
        else:
            record = models.MonitorCompetitor(
                monitor_id=monitor_id,
                competitor_id=competitor_id,
                tracked=tracked
            )
            db.add(record)

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def remove_tracking(db: Session, monitor_id: str, competitor_id: str) -> None:
        record = db.query(models.MonitorCompetitor).filter(
            models.MonitorCompetitor.monitor_id == monitor_id,
            models.MonitorCompetitor.competitor_id == competitor_id
        ).first()
        if record:
            db.delete(record)
            db.commit()

    @staticmethod
    def get_tracked_competitor_ids(db: Session, monitor_id: str) -> List[str]:
        records = db.query(models.MonitorCompetitor).filter(
            models.MonitorCompetitor.monitor_id == monitor_id,
            models.MonitorCompetitor.tracked.is_(True)
        ).all()
        return [record.competitor_id for record in records]


class ChangeReadCRUD:
    """Change read receipt CRUD"""

    @staticmethod
    def mark_read(db: Session, user_id: str, change_id: str) -> models.ChangeReadReceipt:
        record = db.query(models.ChangeReadReceipt).filter(
            models.ChangeReadReceipt.user_id == user_id,
            models.ChangeReadReceipt.change_id == change_id
        ).first()

        if record:
            record.read_at = datetime.utcnow()
        else:
            record = models.ChangeReadReceipt(
                user_id=user_id,
                change_id=change_id,
                read_at=datetime.utcnow()
            )
            db.add(record)

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def bulk_mark_read(db: Session, user_id: str, change_ids: List[str]) -> int:
        count = 0
        for change_id in change_ids:
            ChangeReadCRUD.mark_read(db, user_id, change_id)
            count += 1
        return count

    @staticmethod
    def fetch_read_ids(db: Session, user_id: str, change_ids: List[str]) -> Dict[str, datetime]:
        if not change_ids:
            return {}
        records = db.query(models.ChangeReadReceipt).filter(
            models.ChangeReadReceipt.user_id == user_id,
            models.ChangeReadReceipt.change_id.in_(change_ids)
        ).all()
        return {record.change_id: record.read_at for record in records}


class ArchiveCRUD:
    """Archive CRUD"""

    @staticmethod
    def list_archives(db: Session, user_id: str) -> List[models.AnalysisArchive]:
        return db.query(models.AnalysisArchive).filter(
            models.AnalysisArchive.user_id == user_id
        ).order_by(models.AnalysisArchive.created_at.desc()).all()

    @staticmethod
    def create_archive(
        db: Session,
        user_id: str,
        monitor_id: Optional[str],
        task_id: Optional[str],
        title: str,
        tenant_snapshot: Optional[dict],
        competitor_snapshot: Optional[List[dict]],
        change_snapshot: Optional[List[dict]],
        metadata: Optional[dict],
        search_text: Optional[str]
    ) -> models.AnalysisArchive:
        archive = models.AnalysisArchive(
            user_id=user_id,
            monitor_id=monitor_id,
            task_id=task_id,
            title=title,
            tenant_snapshot=tenant_snapshot,
            competitor_snapshot=competitor_snapshot,
            change_snapshot=change_snapshot,
            metadata_json=metadata,
            search_text=search_text
        )
        db.add(archive)
        db.commit()
        db.refresh(archive)
        return archive

# Create CRUD instances
tenant_crud = TenantCRUD()
competitor_crud = CompetitorCRUD()
tenant_competitor_crud = TenantCompetitorCRUD()
cache_crud = ChangeDetectionCacheCRUD()
content_storage_crud = ContentStorageCRUD()
enhanced_task_crud = EnhancedTaskCRUD()
monitor_crud = MonitorCRUD()
monitor_competitor_crud = MonitorCompetitorCRUD()
change_read_crud = ChangeReadCRUD()
archive_crud = ArchiveCRUD()
