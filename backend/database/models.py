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
    latest_stage = Column(String, nullable=True)

    user_id = Column(String, ForeignKey('users.id'), nullable=True, index=True)
    monitor_id = Column(String, ForeignKey('monitors.id'), nullable=True, index=True)

    # 关系
    competitors = relationship("CompetitorRecord", back_populates="task", cascade="all, delete-orphan")
    tenant_competitors = relationship("TenantCompetitor", back_populates="task", cascade="all, delete-orphan")
    monitor = relationship("Monitor", back_populates="tasks", foreign_keys=[monitor_id])
    user = relationship("User", back_populates="analysis_tasks", foreign_keys=[user_id])
    archive_entry = relationship("AnalysisArchive", back_populates="task", uselist=False)

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


class Monitor(Base):
    """监控实体 - 绑定用户与租户分析记录"""
    __tablename__ = "monitors"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    latest_task_id = Column(String, ForeignKey('analysis_tasks.id'), nullable=True, index=True)

    user = relationship("User", back_populates="monitors")
    tenant = relationship("Tenant")
    tasks = relationship("AnalysisTask", back_populates="monitor", foreign_keys="AnalysisTask.monitor_id")
    latest_task = relationship("AnalysisTask", foreign_keys=[latest_task_id], post_update=True)
    tracked_competitors = relationship("MonitorCompetitor", back_populates="monitor", cascade="all, delete-orphan")
    archives = relationship("AnalysisArchive", back_populates="monitor")

    __table_args__ = (
        UniqueConstraint('user_id', 'url', name='uq_monitor_user_url'),
        Index('idx_monitor_user', 'user_id'),
        Index('idx_monitor_tenant', 'tenant_id'),
    )


class MonitorCompetitor(Base):
    """用户监控的竞争对手映射表"""
    __tablename__ = "monitor_competitors"

    id = Column(String, primary_key=True, default=generate_uuid)
    monitor_id = Column(String, ForeignKey('monitors.id'), nullable=False)
    competitor_id = Column(String, ForeignKey('competitors.id'), nullable=False)
    tracked = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monitor = relationship("Monitor", back_populates="tracked_competitors")
    competitor = relationship("Competitor")

    __table_args__ = (
        UniqueConstraint('monitor_id', 'competitor_id', name='uq_monitor_competitor'),
        Index('idx_monitor_competitor_monitor', 'monitor_id'),
        Index('idx_monitor_competitor_competitor', 'competitor_id'),
    )

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
    
    read_receipts = relationship("ChangeReadReceipt", back_populates="change", cascade="all, delete-orphan")

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


class ChangeReadReceipt(Base):
    """记录用户已读的变化项"""
    __tablename__ = "change_read_receipts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    change_id = Column(String, ForeignKey('change_detections.id'), nullable=False, index=True)
    read_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="read_receipts")
    change = relationship("ChangeDetection", back_populates="read_receipts")

    __table_args__ = (
        UniqueConstraint('user_id', 'change_id', name='uq_user_change_read'),
    )


class AnalysisArchive(Base):
    """归档的分析快照"""
    __tablename__ = "analysis_archives"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey('users.id'), nullable=False, index=True)
    monitor_id = Column(String, ForeignKey('monitors.id'), nullable=True, index=True)
    task_id = Column(String, ForeignKey('analysis_tasks.id'), nullable=True, index=True)
    title = Column(String, nullable=False)
    tenant_snapshot = Column(JSON)
    competitor_snapshot = Column(JSON)
    change_snapshot = Column(JSON)
    metadata_json = Column(JSON)
    search_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="archives")
    monitor = relationship("Monitor", back_populates="archives")
    task = relationship("AnalysisTask", back_populates="archive_entry")
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

    monitors = relationship("Monitor", back_populates="user", cascade="all, delete-orphan")
    analysis_tasks = relationship("AnalysisTask", back_populates="user")
    read_receipts = relationship("ChangeReadReceipt", back_populates="user", cascade="all, delete-orphan")
    archives = relationship("AnalysisArchive", back_populates="user", cascade="all, delete-orphan")

    # 索引优化
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_google_id', 'google_id'),
        Index('idx_user_github_id', 'github_id'),
    )
    
    def __repr__(self):
        return f"<User(id='{self.id}', email='{self.email}', name='{self.name}')>"
