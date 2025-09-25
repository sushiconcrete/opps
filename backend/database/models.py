# backend/database/models.py
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, JSON, Boolean, Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class AnalysisTask(Base):
    """分析任务模型 - 存储所有分析任务"""
    __tablename__ = "analysis_tasks"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    company_name = Column(String, nullable=False)
    task_type = Column(String, default="analysis")  # 'analysis', 'monitoring'
    status = Column(String, default="queued")  # queued, running, completed, failed
    progress = Column(Integer, default=0)
    message = Column(Text)
    config = Column(JSON)  # 存储任务配置 (enable_research, max_competitors等)
    results = Column(JSON)  # 存储完整的分析结果
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    competitors = relationship("CompetitorRecord", back_populates="task", cascade="all, delete-orphan")
    tenant_competitors = relationship("TenantCompetitor", back_populates="task", cascade="all, delete-orphan")

class Tenant(Base):
    """租户信息表 - 存储公司基础信息"""
    __tablename__ = "tenants"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False, unique=True, index=True)  # 域名标识如 'stripe.com'
    tenant_url = Column(String, nullable=False)  # 主页URL
    tenant_name = Column(String, nullable=False)
    tenant_description = Column(Text)
    target_market = Column(String)
    key_features = Column(JSON)  # List[str]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    tenant_competitors = relationship("TenantCompetitor", back_populates="tenant")

class Competitor(Base):
    """竞争对手主表 - 存储竞争对手基础信息"""
    __tablename__ = "competitors"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    competitor_id = Column(String, nullable=False, unique=True, index=True)  # 域名标识
    display_name = Column(String, nullable=False)
    primary_url = Column(String, nullable=False)
    brief_description = Column(Text)
    demographics = Column(Text)
    source = Column(String, default="search")
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    tenant_competitors = relationship("TenantCompetitor", back_populates="competitor")
    change_detections = relationship("ChangeDetectionCache", back_populates="competitor")

class TenantCompetitor(Base):
    """租户-竞争对手关联表"""
    __tablename__ = "tenant_competitors"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    competitor_id = Column(String, ForeignKey('competitors.id'), nullable=False)
    task_id = Column(String, ForeignKey('analysis_tasks.id'), nullable=True)  # 可选：记录发现来源
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    tenant = relationship("Tenant", back_populates="tenant_competitors")
    competitor = relationship("Competitor", back_populates="tenant_competitors")
    task = relationship("AnalysisTask", back_populates="tenant_competitors")
    
    # 唯一约束
    __table_args__ = (
        UniqueConstraint('tenant_id', 'competitor_id', name='unique_tenant_competitor'),
        Index('idx_tenant_competitor', 'tenant_id', 'competitor_id'),
    )

class CompetitorRecord(Base):
    """竞争对手记录 - 兼容现有代码，保留原有字段"""
    __tablename__ = "competitor_records"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey('analysis_tasks.id'), nullable=False, index=True)
    domain = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    primary_url = Column(String, nullable=False)
    brief_description = Column(Text)
    demographics = Column(Text)
    confidence = Column(Float, default=0.5)
    source = Column(String, default="search")
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    task = relationship("AnalysisTask", back_populates="competitors")

class ChangeDetectionCache(Base):
    """变化检测缓存表 - 3天TTL"""
    __tablename__ = "change_detection_cache"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    competitor_id = Column(String, ForeignKey('competitors.id'), nullable=False, index=True)
    url = Column(String, nullable=False, index=True)
    cache_key = Column(String, nullable=False, unique=True, index=True)  # competitor_id:url的哈希
    result_data = Column(JSON, nullable=False)  # 缓存的检测结果
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # TTL过期时间
    
    # 关系
    competitor = relationship("Competitor", back_populates="change_detections")
    
    # 索引优化
    __table_args__ = (
        Index('idx_cache_key_expires', 'cache_key', 'expires_at'),
        Index('idx_competitor_url', 'competitor_id', 'url'),
    )
    
    @classmethod
    def generate_cache_key(cls, competitor_id: str, url: str) -> str:
        """生成缓存键"""
        import hashlib
        key_string = f"{competitor_id}:{url}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    @classmethod
    def is_expired(cls, cache_record) -> bool:
        """检查缓存是否过期"""
        return datetime.utcnow() > cache_record.expires_at

class ChangeDetection(Base):
    """变化检测记录 - 原有实现保留"""
    __tablename__ = "change_detections"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    competitor_id = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False)
    change_type = Column(String, nullable=False)  # Added, Removed, Modified
    content = Column(Text, nullable=False)
    threat_level = Column(Integer, default=5)
    why_matter = Column(Text)
    suggestions = Column(Text)
    detected_at = Column(DateTime, default=datetime.utcnow)

class ContentStorage(Base):
    """内容存储表 - 支持OngoingTracker的previous content存储"""
    __tablename__ = "content_storage"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    url = Column(String, nullable=False, index=True)
    tag = Column(String, nullable=False, index=True)
    content_hash = Column(String, nullable=False)  # 内容哈希，用于去重
    content = Column(Text)  # 存储的markdown内容
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 复合索引
    __table_args__ = (
        Index('idx_url_tag', 'url', 'tag'),
    )
    
    @classmethod
    def generate_content_hash(cls, content: str) -> str:
        """生成内容哈希"""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()
    # 在你的 database/models.py 文件末尾添加这个User模型

class User(Base):
    """用户认证模型 - OAuth登录用户"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    
    # OAuth相关字段
    google_id = Column(String, nullable=True, unique=True)
    github_id = Column(String, nullable=True, unique=True) 
    github_username = Column(String, nullable=True)
    
    # 状态字段
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # 额外数据
    extra_data = Column(JSON, nullable=True)
    
    # 索引优化
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_google_id', 'google_id'),
        Index('idx_user_github_id', 'github_id'),
    )
    
    def __repr__(self):
        return f"<User(id='{self.id}', email='{self.email}', name='{self.name}')>"