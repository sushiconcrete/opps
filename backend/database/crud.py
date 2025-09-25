# backend/database/crud.py
"""Enhanced CRUD operations with proper foreign key handling"""
from sqlalchemy.orm import Session
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

# Create CRUD instances
tenant_crud = TenantCRUD()
competitor_crud = CompetitorCRUD()
tenant_competitor_crud = TenantCompetitorCRUD()
cache_crud = ChangeDetectionCacheCRUD()
content_storage_crud = ContentStorageCRUD()
enhanced_task_crud = EnhancedTaskCRUD()