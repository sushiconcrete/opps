# backend/app.py - 完整保留分析功能 + OAuth认证
from datetime import datetime, timedelta, timezone
import os
import sys
from pathlib import Path

# ========== 环境变量加载 ==========
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

env_paths = [
    os.path.join(project_root, ".env"),
    os.path.join(current_dir, ".env"),
    os.path.join(os.getcwd(), ".env"),
]

from dotenv import load_dotenv
env_loaded = False
for env_path in env_paths:
    if os.path.exists(env_path):
        print(f"找到.env文件: {env_path}")
        load_dotenv(env_path)
        env_loaded = True
        break

if not env_loaded:
    print(f"警告：未找到.env文件，尝试的路径:")
    for path in env_paths:
        print(f"  - {path}")

required_env_vars = ["OPENAI_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"]
print("环境变量检查:")
for var in required_env_vars:
    value = os.getenv(var)
    if value:
        print(f"  ✅ {var}: {value[:10]}...")
    else:
        print(f"  ❌ {var}: 未设置")

os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # 允许开发环境使用HTTP

# ========== FastAPI和OAuth相关导入 ==========
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Any
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse, urlencode

# OAuth 相关导入
from jose import JWTError, jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
import secrets
import httpx

if project_root not in sys.path:
    sys.path.append(project_root)

from database import (
    init_db, 
    get_db,
    check_database_connection,
    task_crud,
    competitor_crud,
    change_crud,
    basic_competitor_crud,
    get_db_session,
    tenant_crud,
    enhanced_task_crud,
    change_detection_cache,
    get_database_stats,
    monitor_crud,
    monitor_competitor_crud,
    change_read_crud,
    archive_crud
)

# ========== OAuth 配置 ==========
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Google OAuth配置
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")

# GitHub OAuth配置  
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/api/auth/github/callback")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== JWT 认证函数 ==========
security = HTTPBearer()

class TaskEventBroker:
    """In-memory broker for streaming analysis events"""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._history: Dict[str, List[dict]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, task_id: str) -> asyncio.Lock:
        lock = self._locks.get(task_id)
        if not lock:
            lock = asyncio.Lock()
            self._locks[task_id] = lock
        return lock

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._get_lock(task_id):
            subscribers = self._subscribers.setdefault(task_id, set())
            subscribers.add(queue)
            history = list(self._history.get(task_id, []))

        for event in history:
            await queue.put(event)

        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        async with self._get_lock(task_id):
            subscribers = self._subscribers.get(task_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)
                self._history.pop(task_id, None)
                self._locks.pop(task_id, None)

    async def publish(self, task_id: str, event: dict) -> None:
        async with self._get_lock(task_id):
            subscribers = list(self._subscribers.get(task_id, []))
            history = self._history.setdefault(task_id, [])
            history.append(event)
            if len(history) > 50:
                history.pop(0)

        if not subscribers:
            return

        for queue in subscribers:
            await queue.put(event)

    def prime(self, task_id: str, events: List[dict]) -> None:
        self._history[task_id] = list(events[-50:])

    def get_history(self, task_id: str) -> List[dict]:
        return list(self._history.get(task_id, []))


event_broker = TaskEventBroker()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证JWT令牌"""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        ensure_user_record(payload)
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in again."
        ) from exc


require_auth = verify_token


def ensure_user_record(payload: dict) -> None:
    """Make sure a decoded JWT payload maps to a persisted user."""
    user_id = payload.get("sub")
    if not user_id:
        return

    try:
        from database.models import User
        with get_db_session() as db_session:
            user = db_session.query(User).filter(User.id == user_id).first()
            now = datetime.now(timezone.utc)

            if user:
                user.last_login = now
                email = payload.get("email")
                if email and user.email != email:
                    user.email = email
                name = payload.get("name")
                if name and user.name != name:
                    user.name = name
                avatar = payload.get("picture") or payload.get("avatar_url")
                if avatar and user.avatar_url != avatar:
                    user.avatar_url = avatar
                return

            email = payload.get("email") or f"{user_id}@placeholder.local"
            name = payload.get("name") or (email.split("@", 1)[0] if "@" in email else "User")
            avatar_url = payload.get("picture") or payload.get("avatar_url")

            new_user = User(
                id=user_id,
                email=email,
                name=name or "User",
                avatar_url=avatar_url,
                is_active=True,
                is_verified=bool(payload.get("email_verified")),
                created_at=now,
                updated_at=now,
                last_login=now
            )
            db_session.add(new_user)
    except Exception as exc:
        logger.warning(f"Failed to ensure user record for {user_id}: {exc}")

def create_google_oauth_flow():
    """创建Google OAuth流程 - 修复版本"""
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    }
    
    # 使用完整的scope URLs
    scopes = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile'
    ]
    
    return Flow.from_client_config(
        client_config,
        scopes=scopes,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

def get_or_create_user(db: Session, user_info: dict, provider: str):
    """获取或创建用户（支持Google和GitHub）"""
    try:
        from database.models import User
        
        email = user_info.get('email')
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # 查找现有用户
        user = db.query(User).filter(User.email == email).first()
        
        if user:
            # 更新最后登录时间和提供商信息
            user.last_login = datetime.now(timezone.utc)
            
            if provider == "google" and not user.google_id:
                user.google_id = user_info.get('sub') or user_info.get('google_id')
            elif provider == "github" and not user.github_id:
                user.github_id = str(user_info.get('github_id', ''))
                user.github_username = user_info.get('github_username', '')
            
            # 更新头像（如果更新了）
            if user_info.get('picture') and user_info['picture'] != user.avatar_url:
                user.avatar_url = user_info['picture']
                
            db.commit()
            db.refresh(user)
            return user
        
        # 创建新用户
        user_data = {
            'email': email,
            'name': user_info.get('name', ''),
            'avatar_url': user_info.get('picture', ''),
            'is_active': True,
            'created_at': datetime.now(timezone.utc),
            'last_login': datetime.now(timezone.utc)
        }
        
        if provider == "google":
            user_data['google_id'] = user_info.get('sub') or user_info.get('google_id')
        elif provider == "github":
            user_data['github_id'] = str(user_info.get('github_id', ''))
            user_data['github_username'] = user_info.get('github_username', '')
        
        new_user = User(**user_data)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Created new {provider} user: {new_user.email}")
        return new_user
        
    except Exception as e:
        logger.error(f"用户管理失败: {e}")
        db.rollback()
        # 返回临时用户对象，确保OAuth流程能完成
        return type('User', (), {
            'id': user_info.get('sub') or str(user_info.get('github_id', str(uuid.uuid4()))),
            'email': user_info.get('email', ''),
            'name': user_info.get('name', ''),
            'avatar_url': user_info.get('picture', ''),
        })()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在初始化数据库...")
    if init_db():
        logger.info("数据库初始化成功")
    else:
        logger.warning("数据库初始化失败，使用内存存储")
    
    check_database_connection()
    yield
    logger.info("应用正在关闭...")

app = FastAPI(
    title="OPP - Competitor Analysis API", 
    version="1.0.0-oauth",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalysisRequest(BaseModel):
    company_name: str
    enable_research: bool = True
    max_competitors: int = 10
    enable_caching: bool = True
    monitor_id: Optional[str] = None
    monitor_name: Optional[str] = None
    tenant_url: Optional[str] = None

class TaskResponse(BaseModel):
    task_id: str
    message: str
    monitor_id: Optional[str] = None

class MonitorCreateRequest(BaseModel):
    url: str
    name: Optional[str] = None

class MonitorRenameRequest(BaseModel):
    name: str

class CompetitorTrackRequest(BaseModel):
    monitor_id: Optional[str] = None
    display_name: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[float] = None

class BulkReadRequest(BaseModel):
    change_ids: List[str]
    monitor_id: Optional[str] = None

class ArchiveCreateRequest(BaseModel):
    monitor_id: Optional[str] = None
    task_id: Optional[str] = None
    title: str
    metadata: Optional[Dict[str, Any]] = None


def serialize_monitor(monitor) -> Dict[str, Any]:
    latest_task = getattr(monitor, 'latest_task', None)
    tracked_records = list(getattr(monitor, 'tracked_competitors', []) or [])
    tracked_ids: List[str] = []
    tracked_slugs: List[str] = []

    for record in tracked_records:
        competitor_pk = getattr(record, 'competitor_id', None)
        if competitor_pk:
            tracked_ids.append(competitor_pk)
        competitor_obj = getattr(record, 'competitor', None)
        competitor_slug = getattr(competitor_obj, 'competitor_id', None) if competitor_obj else None
        if competitor_slug:
            tracked_slugs.append(competitor_slug)

    return {
        'id': monitor.id,
        'name': monitor.name,
        'url': monitor.url,
        'created_at': monitor.created_at,
        'updated_at': getattr(monitor, 'updated_at', None),
        'last_run_at': monitor.last_run_at,
        'latest_task_id': monitor.latest_task_id,
        'latest_task_status': getattr(latest_task, 'status', None),
        'latest_task_progress': getattr(latest_task, 'progress', None),
        'archived_at': monitor.archived_at,
        'tracked_competitor_ids': tracked_ids,
        'tracked_competitor_slugs': tracked_slugs
    }


def serialize_archive(archive) -> Dict[str, Any]:
    return {
        'id': archive.id,
        'monitor_id': archive.monitor_id,
        'task_id': archive.task_id,
        'title': archive.title,
        'created_at': archive.created_at,
        'tenant': archive.tenant_snapshot,
        'competitors': archive.competitor_snapshot,
        'changes': archive.change_snapshot,
        'metadata': archive.metadata_json
    }

class StatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    company_name: str

analyzer_components = {}

def get_analyzer_components():
    """获取分析组件（懒加载）"""
    if not analyzer_components:
        try:
            from src.core.tenant_analyzer import tenant_agent
            from src.core.competitor_finder import competitor_finder
            from src.core.compare_agent import change_detector
            
            analyzer_components['tenant_agent'] = tenant_agent
            analyzer_components['competitor_finder'] = competitor_finder
            analyzer_components['change_detector'] = change_detector
            
            logger.info("分析组件初始化成功")
            
        except Exception as e:
            logger.error(f"分析组件初始化失败: {e}")
            raise
    
    return analyzer_components

# ========== 核心修复：统一的Competitor ID管理器 ==========
class CompetitorIDManager:
    """统一管理competitor ID的映射和一致性"""
    
    @staticmethod
    def extract_domain_id(url: str) -> str:
        """从URL提取标准化的domain ID"""
        if not url:
            return ""
        
        try:
            if not url.startswith(('http://', 'https://')):
                url = f'https://{url}'
            
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # 移除www前缀
            if domain.startswith('www.'):
                domain = domain[4:]
                
            return domain
        except Exception as e:
            logger.warning(f"解析URL失败 {url}: {e}")
            return url.lower().replace('www.', '')
    
    @staticmethod
    def get_or_create_competitor_id(comp_data: dict, db_session: Session) -> str:
        """获取或创建标准化的competitor ID，确保数据库一致性"""
        from database.models import Competitor
        from sqlalchemy import or_
        
        # 提取基本信息
        primary_url = comp_data.get('primary_url', '')
        display_name = comp_data.get('display_name', '')
        existing_id = comp_data.get('competitor_id') or comp_data.get('id', '')
        
        # 生成标准domain ID
        domain_id = CompetitorIDManager.extract_domain_id(primary_url)
        
        # 1. 首先尝试通过URL精确匹配
        if primary_url:
            existing_by_url = db_session.query(Competitor).filter(
                Competitor.primary_url == primary_url
            ).first()
            
            if existing_by_url:
                logger.info(f"通过URL找到现有competitor: {existing_by_url.competitor_id}")
                return existing_by_url.competitor_id
        
        # 2. 尝试通过domain ID匹配
        if domain_id:
            existing_by_domain = db_session.query(Competitor).filter(
                Competitor.competitor_id == domain_id
            ).first()
            
            if existing_by_domain:
                logger.info(f"通过domain ID找到现有competitor: {domain_id}")
                return domain_id
        
        # 3. 尝试通过显示名称模糊匹配
        if display_name:
            company_name = display_name.lower().replace(' ', '').replace('group', '').replace('inc', '').replace('ltd', '')
            
            fuzzy_matches = db_session.query(Competitor).filter(
                or_(
                    Competitor.display_name.ilike(f'%{display_name}%'),
                    Competitor.competitor_id.ilike(f'%{company_name}%')
                )
            ).all()
            
            for match in fuzzy_matches:
                if primary_url and match.primary_url:
                    match_domain = CompetitorIDManager.extract_domain_id(match.primary_url)
                    if match_domain == domain_id:
                        logger.info(f"通过模糊匹配找到competitor: {match.competitor_id}")
                        return match.competitor_id
        
        # 4. 如果都没找到，返回标准化的domain ID（将在后续创建）
        final_id = domain_id or existing_id or f"comp_{hash(display_name or primary_url)}"
        logger.info(f"将使用新的competitor ID: {final_id}")
        return final_id
    
    @staticmethod
    def ensure_competitor_exists(comp_data: dict, competitor_id: str, db_session: Session) -> bool:
        """确保competitor记录存在于数据库中"""
        from database.models import Competitor
        
        try:
            existing = db_session.query(Competitor).filter(
                Competitor.competitor_id == competitor_id
            ).first()
            
            if existing:
                # 更新现有记录的信息（如果提供了更好的数据）
                if comp_data.get('primary_url') and not existing.primary_url:
                    existing.primary_url = comp_data['primary_url']
                if comp_data.get('display_name') and existing.display_name != comp_data['display_name']:
                    existing.display_name = comp_data['display_name']
                if comp_data.get('brief_description') and not existing.brief_description:
                    existing.brief_description = comp_data['brief_description']
                
                db_session.commit()
                return True
            
            # 创建新记录
            new_competitor = Competitor(
                competitor_id=competitor_id,
                display_name=comp_data.get('display_name', competitor_id),
                primary_url=comp_data.get('primary_url', ''),
                brief_description=comp_data.get('brief_description', ''),
                demographics=comp_data.get('demographics', ''),
                source=comp_data.get('source', 'analysis'),
                extra_data=comp_data.get('extra_data', {})
            )
            
            db_session.add(new_competitor)
            db_session.commit()
            logger.info(f"成功创建competitor记录: {competitor_id}")
            return True
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"确保competitor存在时出错: {e}")
            return False

# ========== 修复后的主分析函数 ==========
async def run_analysis_with_persistence(
    task_id: str,
    company_name: str,
    enable_research: bool,
    max_competitors: int,
    enable_caching: bool,
    db: Session,
    user_id: Optional[str] = None,
    monitor_id: Optional[str] = None
):
    """运行分析任务（异步）- 使用统一的ID管理系统"""
    cached_results = {}
    uncached_competitors = []

    analysis_context: Dict[str, Any] = {
        "tenant": None,
        "competitors": [],
        "changes": []
    }

    async def emit(event: Dict[str, Any]) -> None:
        try:
            await event_broker.publish(task_id, event)
        except Exception as publish_error:
            logger.warning(f'Failed to publish event for {task_id}: {publish_error}')

    try:
        logger.info(f"开始分析任务: {company_name} (缓存: {'启用' if enable_caching else '禁用'})")
        
        task_crud.update_task(db, task_id, 
            status="running",
            progress=10,
            message="Initializing analysis components..."
        )
        
        await emit({
            "type": "status",
            "stage": "initializing",
            "progress": 10,
            "message": "Initializing analysis components..."
        })
        
        components = get_analyzer_components()
        tenant_agent = components['tenant_agent']
        competitor_finder = components['competitor_finder']
        change_detector = components['change_detector']
        
        # 第一步：分析公司信息并持久化租户数据
        task_crud.update_task(db, task_id,
            progress=25,
            message="Analyzing company information..."
        )
        
        from langchain_core.messages import HumanMessage
        tenant_result = await tenant_agent.ainvoke({
            "messages": [HumanMessage(content=f"Analyze this company: {company_name}")]
        })
        tenant = tenant_result.get("tenant")
        
        if not tenant:
            raise Exception("Failed to extract tenant information")
        
        # 保存租户信息到数据库
        tenant_id = None
        tenant_payload: Dict[str, Any] = {}
        saved_tenant = None
        try:
            with get_db_session() as db_session:
                if hasattr(tenant, 'model_dump'):
                    tenant_dict = tenant.model_dump()
                elif hasattr(tenant, '__dict__'):
                    tenant_dict = tenant.__dict__
                else:
                    tenant_dict = dict(tenant) if hasattr(tenant, 'keys') else {}

                if 'tenant_id' not in tenant_dict or not tenant_dict['tenant_id']:
                    tenant_dict['tenant_id'] = company_name.lower().replace(' ', '_').replace('-', '_')

                tenant_id = tenant_dict['tenant_id']
                tenant_payload = {
                    'tenant_id': tenant_dict.get('tenant_id'),
                    'tenant_name': tenant_dict.get('tenant_name'),
                    'tenant_url': tenant_dict.get('tenant_url'),
                    'tenant_description': tenant_dict.get('tenant_description'),
                    'target_market': tenant_dict.get('target_market'),
                    'key_features': tenant_dict.get('key_features'),
                }

                saved_tenant, created = tenant_crud.get_or_create_tenant(
                    db_session, tenant_id, tenant_dict
                )

                if monitor_id and user_id and saved_tenant:
                    monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
                    if monitor:
                        monitor_crud.attach_tenant(db_session, monitor, saved_tenant)

                logger.info(f"租户信息{'创建' if created else '更新'}: {tenant_dict.get('tenant_name', company_name)}")
        except Exception as e:
            logger.warning(f"保存租户信息失败: {e}")

        if tenant_payload:
            analysis_context['tenant'] = tenant_payload
            task_crud.update_task(db, task_id,
                progress=40,
                message='Company profile ready',
                latest_stage='tenant'
            )
            await emit({
                'type': 'stage',
                'stage': 'tenant',
                'progress': 40,
                'data': tenant_payload
            })

        # 第二步：查找竞争对手
        task_crud.update_task(db, task_id,
            progress=50,
            message="Finding competitors..."
        )
        
        existing_competitors = []
        if tenant_id and enable_caching:
            try:
                with get_db_session() as db_session:
                    existing_competitors = tenant_crud.get_tenant_competitors(db_session, tenant_id)
                    if existing_competitors:
                        logger.info(f"找到已存储的竞争对手: {len(existing_competitors)} 个")
            except Exception as e:
                logger.warning(f"查询已存储竞争对手失败: {e}")
        
        if not existing_competitors:
            competitor_state = {
                "tenant": tenant,
                "messages": [],
                "competitors": [],
                "tool_call_iterations": 0,
                "raw_notes": []
            }
            
            competitor_result = await competitor_finder.ainvoke(competitor_state)
            competitors = competitor_result.get("competitors", [])
            limited_competitors = competitors[:max_competitors]
            
            if limited_competitors and tenant_id:
                try:
                    with get_db_session() as db_session:
                        competitors_data = []
                        for comp in limited_competitors:
                            if hasattr(comp, 'model_dump'):
                                comp_dict = comp.model_dump()
                            elif hasattr(comp, '__dict__'):
                                comp_dict = comp.__dict__
                            else:
                                comp_dict = dict(comp) if hasattr(comp, 'keys') else {}
                            competitors_data.append(comp_dict)
                        
                        records, mappings = enhanced_task_crud.save_competitors_with_mapping(
                            db_session, task_id, tenant_id, competitors_data
                        )
                        
                        logger.info(f"保存竞争对手: {len(records)} 个记录, {len(mappings)} 个映射关系")
                except Exception as e:
                    logger.warning(f"保存竞争对手映射失败: {e}")
        else:
            limited_competitors = existing_competitors[:max_competitors]
            logger.info(f"使用已存储的竞争对手: {len(limited_competitors)} 个")
        
        # 保存竞争对手到任务（为了兼容性）
        competitor_stage_payload: Dict[str, Any] = {'competitors': []}
        if limited_competitors:
            competitors_for_save = []
            for comp in limited_competitors:
                if hasattr(comp, 'model_dump'):
                    comp_dict = comp.model_dump()
                elif isinstance(comp, dict):
                    comp_dict = comp
                elif hasattr(comp, '__dict__'):
                    comp_dict = {}
                    for attr in ['id', 'competitor_id', 'display_name', 'primary_url', 'brief_description', 'demographics', 'source', 'confidence', 'url', 'description', 'target_users']:
                        if hasattr(comp, attr):
                            comp_dict[attr] = getattr(comp, attr)
                else:
                    comp_dict = {
                        'id': str(comp),
                        'display_name': str(comp),
                        'primary_url': '',
                        'brief_description': 'Auto converted'
                    }

                competitors_for_save.append(comp_dict)

            domain_keys = []
            for comp_dict in competitors_for_save:
                key = comp_dict.get('competitor_id') or comp_dict.get('id') or comp_dict.get('domain') or comp_dict.get('primary_url')
                if isinstance(key, str) and key not in domain_keys:
                    domain_keys.append(key)

            id_lookup: Dict[str, str] = {}
            if domain_keys:
                try:
                    from database.models import Competitor
                    with get_db_session() as db_session:
                        records = db_session.query(Competitor).filter(Competitor.competitor_id.in_(domain_keys)).all()
                        id_lookup = {record.competitor_id: record.id for record in records}
                except Exception as lookup_error:
                    logger.warning(f'获取竞争对手主键失败: {lookup_error}')

            enriched_competitors = []
            for comp_dict in competitors_for_save:
                domain_key = comp_dict.get('competitor_id') or comp_dict.get('id') or comp_dict.get('domain') or comp_dict.get('primary_url')
                primary_id = id_lookup.get(domain_key) if isinstance(domain_key, str) else None

                competitor_payload = {
                    'id': primary_id or domain_key or comp_dict.get('display_name'),
                    'competitor_id': domain_key,
                    'display_name': comp_dict.get('display_name') or comp_dict.get('name') or comp_dict.get('id'),
                    'primary_url': comp_dict.get('primary_url') or comp_dict.get('url') or '',
                    'brief_description': comp_dict.get('brief_description') or comp_dict.get('description') or '',
                    'source': comp_dict.get('source', 'analysis'),
                    'confidence': comp_dict.get('confidence', 0.5),
                    'demographics': comp_dict.get('demographics') or comp_dict.get('target_users') or ''
                }
                enriched_competitors.append(competitor_payload)

            basic_competitor_crud.save_competitors(db, task_id, competitors_for_save)

            tracked_competitor_ids: List[str] = []
            if monitor_id and user_id:
                try:
                    from database.models import Competitor
                    from sqlalchemy import or_

                    with get_db_session() as db_session:
                        monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
                        if monitor:
                            seen: Set[str] = set()
                            for comp_payload in enriched_competitors:
                                candidate = comp_payload.get('id') or comp_payload.get('competitor_id')
                                if not candidate or candidate in seen:
                                    continue
                                competitor_record = db_session.query(Competitor).filter(
                                    or_(
                                        Competitor.id == candidate,
                                        Competitor.competitor_id == candidate
                                    )
                                ).first()
                                if competitor_record:
                                    monitor_competitor_crud.set_tracking(
                                        db_session, monitor.id, competitor_record.id, True
                                    )
                                    tracked_competitor_ids.append(competitor_record.id)
                                    seen.add(candidate)
                except Exception as tracking_error:
                    logger.warning(f"同步监控的竞争对手失败: {tracking_error}")

            if tracked_competitor_ids:
                competitor_stage_payload['tracked_competitor_ids'] = tracked_competitor_ids

            competitor_stage_payload['competitors'] = enriched_competitors
            analysis_context['competitors'] = competitor_stage_payload
            task_crud.update_task(db, task_id,
                progress=70,
                message='Competitor set generated',
                latest_stage='competitors'
            )
            await emit({
                'type': 'stage',
                'stage': 'competitors',
                'progress': 70,
                'data': competitor_stage_payload
            })
        
        # 第三步：分析竞争对手变化（使用统一ID管理）
        task_crud.update_task(db, task_id,
            progress=75,
            message=f"Analyzing changes for {min(3, len(limited_competitors))} competitors..."
        )
        
        changes_result = []
        competitor_mapping: Dict[str, str] = {}
        if enable_research and limited_competitors:
            logger.info("=== 开始竞争对手变化分析（使用统一ID管理） ===")
            competitors_to_analyze = limited_competitors[:3]
            
            # 使用统一的ID管理器构建映射
            competitor_mapping = {}
            competitors_for_detection = []
            
            with get_db_session() as db_session:
                for comp in competitors_to_analyze:
                    try:
                        # 统一提取竞争对手信息
                        if hasattr(comp, 'model_dump'):
                            comp_data = comp.model_dump()
                        elif isinstance(comp, dict):
                            comp_data = comp
                        elif hasattr(comp, '__dict__'):
                            comp_data = comp.__dict__
                        else:
                            logger.warning(f"无法解析竞争对手数据: {type(comp)}")
                            continue
                        
                        comp_url = comp_data.get('primary_url', '')
                        if not comp_url:
                            logger.warning(f"竞争对手缺少URL: {comp_data}")
                            continue
                        
                        # 使用统一ID管理器获取一致的competitor_id
                        comp_id = CompetitorIDManager.get_or_create_competitor_id(comp_data, db_session)
                        
                        # 确保competitor记录存在
                        if CompetitorIDManager.ensure_competitor_exists(comp_data, comp_id, db_session):
                            competitor_mapping[comp_url] = comp_id
                            competitors_for_detection.append(comp)
                            logger.info(f"映射确认: {comp_url} -> {comp_id}")
                        else:
                            logger.error(f"无法确保competitor存在: {comp_id}")
                    
                    except Exception as e:
                        logger.error(f"处理竞争对手时出错: {e}", exc_info=True)
                        continue
            
            logger.info(f"=== 最终竞争对手映射 ({len(competitor_mapping)}个) ===")
            for url, comp_id in competitor_mapping.items():
                logger.info(f"  {url} -> {comp_id}")
            
            if not competitor_mapping:
                logger.warning("没有有效的URL-竞争对手映射，跳过缓存检查")
                change_state = {
                    "competitors": competitors_to_analyze,
                    "changes": []
                }
                change_result = await change_detector.ainvoke(change_state)
                changes_result = change_result.get("changes", [])
            else:
                # 使用缓存系统（现在有一致的映射）
                cached_results = {}
                uncached_competitors = []
                
                if enable_caching:
                    try:
                        # 获取缓存结果
                        url_competitor_pairs = list(competitor_mapping.items())
                        cached_results = await change_detection_cache.get_cached_results(url_competitor_pairs)
                        
                        # 确定哪些需要新检测
                        for comp in competitors_for_detection:
                            comp_url = ""
                            if hasattr(comp, 'primary_url'):
                                comp_url = comp.primary_url
                            elif isinstance(comp, dict):
                                comp_url = comp.get('primary_url', '')
                            
                            if comp_url and comp_url not in cached_results:
                                uncached_competitors.append(comp)
                        
                        logger.info(f"缓存命中: {len(cached_results)} 个URL, 需要检测: {len(uncached_competitors)} 个URL")
                    
                    except Exception as e:
                        logger.error(f"查询缓存失败，将执行完整检测: {e}")
                        uncached_competitors = competitors_for_detection
                        cached_results = {}
                else:
                    uncached_competitors = competitors_for_detection
                    logger.info("缓存已禁用，执行完整变化检测")
                
                # 对未缓存的竞争对手执行变化检测
                new_changes = []
                if uncached_competitors:
                    change_state = {
                        "competitors": uncached_competitors,
                        "changes": []
                    }
                    
                    try:
                        change_result = await change_detector.ainvoke(change_state)
                        new_changes = change_result.get("changes", [])
                        logger.info(f"完成变化检测: {len(new_changes)} 个结果")
                    except Exception as e:
                        logger.error(f"变化检测失败: {e}")
                        new_changes = []
                    
                    # 缓存新的检测结果
                    if enable_caching and new_changes:
                        try:
                            cache_data = {}
                            cache_competitor_mapping = {}
                            
                            for i, change_result in enumerate(new_changes):
                                if i < len(uncached_competitors):
                                    comp = uncached_competitors[i]
                                    comp_url = ""
                                    if hasattr(comp, 'primary_url'):
                                        comp_url = comp.primary_url
                                    elif isinstance(comp, dict):
                                        comp_url = comp.get('primary_url', '')
                                    
                                    comp_id = competitor_mapping.get(comp_url)
                                    
                                    if comp_url and comp_id:
                                        if hasattr(change_result, 'model_dump'):
                                            change_dict = change_result.model_dump()
                                        elif isinstance(change_result, dict):
                                            change_dict = change_result
                                        else:
                                            change_dict = {"changes": []}
                                        
                                        cache_data[comp_url] = change_dict
                                        cache_competitor_mapping[comp_url] = comp_id
                            
                            if cache_data:
                                logger.info(f"准备缓存数据: {list(cache_data.keys())}")
                                logger.info(f"竞争对手映射: {cache_competitor_mapping}")
                                
                                cached_urls = await change_detection_cache.cache_results(
                                    cache_data, cache_competitor_mapping
                                )
                                logger.info(f"成功缓存变化检测结果: {len(cached_urls)} 个URL")
                        
                        except Exception as e:
                            logger.error(f"缓存变化检测结果失败: {e}")
                
                # 合并缓存结果和新结果
                changes_result = list(cached_results.values()) + new_changes

                if cached_results:
                    logger.info(f"使用缓存结果: {len(cached_results)} 个，新检测: {len(new_changes)} 个")
                else:
                    logger.info("所有变化检测结果都来自新检测")

            collected_change_records = []
            
            # 保存变化记录到数据库
            for i, changes in enumerate(changes_result):
                try:
                    if changes and hasattr(changes, 'changes') and changes.changes:
                        # 获取对应的竞争对手ID
                        if i < len(competitors_to_analyze):
                            comp = competitors_to_analyze[i]
                            comp_url = ""
                            
                            if hasattr(comp, 'primary_url'):
                                comp_url = comp.primary_url
                            elif isinstance(comp, dict):
                                comp_url = comp.get('primary_url', '')
                            
                            comp_id = competitor_mapping.get(comp_url, f"comp_{i}")
                        else:
                            comp_id = f"comp_{i}"
                            comp_url = ""
                        
                        # 保存变化记录
                        changes_list = []
                        if hasattr(changes.changes, '__iter__'):
                            for change in changes.changes:
                                if hasattr(change, 'model_dump'):
                                    changes_list.append(change.model_dump())
                                elif isinstance(change, dict):
                                    changes_list.append(change)
                        
                        if changes_list:
                            saved_records = change_crud.save_changes(db, comp_id, comp_url, changes_list)
                            if saved_records:
                                collected_change_records.extend(saved_records)
                            logger.info(f"保存变化记录: {len(changes_list)} 条记录, competitor_id={comp_id}")
                
                except Exception as e:
                    logger.error(f"保存变化记录失败: {e}")
        
        change_stage_payload: Dict[str, Any] = {'changes': []}
        candidate_competitor_ids = set(competitor_mapping.values())
        if not candidate_competitor_ids and collected_change_records:
            candidate_competitor_ids = {record.competitor_id for record in collected_change_records if hasattr(record, 'competitor_id')}

        if candidate_competitor_ids:
            try:
                from database.models import ChangeDetection
                with get_db_session() as db_session:
                    change_records = (
                        db_session.query(ChangeDetection)
                        .filter(ChangeDetection.competitor_id.in_(list(candidate_competitor_ids)))
                        .order_by(ChangeDetection.detected_at.desc())
                        .limit(120)
                        .all()
                    )
                    read_map = {}
                    if user_id:
                        read_map = change_read_crud.fetch_read_ids(
                            db_session,
                            user_id,
                            [record.id for record in change_records]
                        )
                    for record in change_records:
                        read_at_value = None
                        if record.id in read_map and read_map[record.id]:
                            read_at_value = read_map[record.id].isoformat()
                        change_stage_payload['changes'].append({
                            'id': record.id,
                            'url': record.url,
                            'change_type': record.change_type,
                            'content': record.content,
                            'timestamp': record.detected_at.isoformat() if record.detected_at else None,
                            'threat_level': record.threat_level,
                            'why_matter': record.why_matter,
                            'suggestions': record.suggestions,
                            'read_at': read_at_value
                        })
            except Exception as fetch_error:
                logger.warning(f"获取变化记录失败: {fetch_error}")

        if change_stage_payload['changes']:
            analysis_context['changes'] = change_stage_payload
            task_crud.update_task(db, task_id,
                progress=90,
                message='Change insights compiled',
                latest_stage='changes'
            )
            await emit({
                'type': 'stage',
                'stage': 'changes',
                'progress': 90,
                'data': change_stage_payload
            })

        # 第四步：生成最终结果
        task_crud.update_task(db, task_id,
            progress=95,
            message="Generating analysis report..."
        )
        
        final_results = {
            "tenant": tenant.model_dump() if hasattr(tenant, 'model_dump') else tenant,
            "competitors": [
                c.model_dump() if hasattr(c, 'model_dump') else c 
                for c in limited_competitors
            ],
            "competitor_analysis": {},
            "summary": {
                "total_competitors": len(limited_competitors),
                "analyzed_competitors": len(changes_result),
                "total_changes": sum(
                    len(c.changes) if hasattr(c, 'changes') and c.changes else 0 
                    for c in changes_result
                ),
                "company_name": company_name,
                "analysis_time": 0,
                "cache_enabled": enable_caching,
                "cache_hits": len(cached_results) if enable_caching else 0
            }
        }
        
        # 添加变化分析到结果中
        for i, changes in enumerate(changes_result):
            if i < len(limited_competitors):
                comp = limited_competitors[i]
                if hasattr(comp, 'competitor_id'):
                    comp_id = comp.competitor_id
                elif hasattr(comp, 'id'):
                    comp_id = comp.id  
                else:
                    comp_id = f"comp_{i}"
                
                final_results["competitor_analysis"][comp_id] = {
                    "competitor": comp.model_dump() if hasattr(comp, 'model_dump') else comp,
                    "changes": changes.model_dump() if hasattr(changes, 'model_dump') else changes,
                    "strengths": [],
                    "weaknesses": [],
                    "user_feedbacks": []
                }
        
        # 获取任务开始时间并计算耗时
        task = task_crud.get_task(db, task_id)
        if task and task.started_at:
            final_results["summary"]["analysis_time"] = (
                datetime.utcnow() - task.started_at
            ).total_seconds()
        
        if monitor_id and user_id:
            try:
                with get_db_session() as db_session:
                    monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
                    if monitor:
                        monitor_crud.set_latest_task(db_session, monitor, task_id)
            except Exception as monitor_error:
                logger.warning(f"更新监控任务失败: {monitor_error}")

        # 更新任务状态：完成
        task_crud.update_task(db, task_id,
            status="completed",
            progress=100,
            message="Analysis complete",
            results=final_results,
            latest_stage="complete"
        )

        await emit({
            'type': 'status',
            'stage': 'complete',
            'progress': 100,
            'data': analysis_context
        })

        logger.info(f"分析完成: {company_name}, 找到 {len(limited_competitors)} 个竞争对手, 缓存命中 {len(cached_results) if enable_caching else 0} 个")

    except Exception as e:
        logger.error(f"分析失败 [{company_name}]: {str(e)}", exc_info=True)

        task_crud.update_task(db, task_id,
            status="failed",
            progress=0,
            message=f"Analysis failed: {str(e)}"
        )
        await emit({
            'type': 'status',
            'stage': 'failed',
            'progress': 0,
            'message': str(e)
        })

# 保持原有的run_analysis函数作为向后兼容
async def run_analysis(task_id: str, company_name: str, enable_research: bool, max_competitors: int, db: Session):
    """向后兼容的分析函数"""
    await run_analysis_with_persistence(task_id, company_name, enable_research, max_competitors, True, db)

def validate_config():
    """验证配置"""
    required_vars = ["OPENAI_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"缺少必要的环境变量: {', '.join(missing_vars)}")
        return False
    
    logger.info("环境变量配置检查通过")
    return True

# ========== OAuth 路由 ==========

@app.get("/api/auth/google")
async def google_login():
    """初始化Google OAuth登录"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="Google OAuth not configured"
        )
    
    try:
        flow = create_google_oauth_flow()
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='select_account'
        )
        
        logger.info("Redirecting to Google OAuth")
        return RedirectResponse(url=authorization_url)
        
    except Exception as e:
        logger.error(f"Google OAuth initialization failed: {e}")
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        error_params = urlencode({"error": "OAuth initialization failed"})
        return RedirectResponse(url=f"{frontend_url}?{error_params}")

@app.get("/api/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """处理Google OAuth回调 - 修复版本"""
    try:
        logger.info(f"Google callback called with URL: {request.url}")
        
        # 创建flow，但不需要验证state，因为Google会处理这个
        flow = create_google_oauth_flow()
        
        # 直接获取authorization response，不验证scope变化
        authorization_response = str(request.url)
        
        try:
            flow.fetch_token(authorization_response=authorization_response)
            logger.info("Token exchange successful")
        except Exception as token_error:
            logger.error(f"Token exchange failed: {token_error}")
            # 如果是scope问题，尝试忽略scope验证
            import urllib.parse as urlparse
            from google.auth.transport.requests import Request as GoogleRequest
            
            # 手动解析code参数
            parsed_url = urlparse.urlparse(authorization_response)
            query_params = urlparse.parse_qs(parsed_url.query)
            code = query_params.get('code', [None])[0]
            
            if not code:
                raise Exception("No authorization code found")
            
            # 手动交换token
            token_request = GoogleRequest()
            token_response = flow.oauth2session.fetch_token(
                flow.client_config['token_uri'],
                authorization_response=authorization_response,
                code=code,
                client_secret=GOOGLE_CLIENT_SECRET
            )
            
            flow.credentials = flow.oauth2session.token
        
        # 获取用户信息
        credentials = flow.credentials
        user_info_service = google_requests.Request()
        
        # 使用access token直接调用用户信息API
        import requests
        headers = {'Authorization': f'Bearer {credentials.token}'}
        response = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to get user info: {response.text}")
        
        user_info = response.json()
        logger.info(f"User info retrieved: {user_info.get('email', 'No email')}")
        
        # 获取或创建用户
        user = get_or_create_user(db, user_info, "google")
        
        # 创建JWT令牌
        access_token = create_access_token(
            data={
                "sub": user.id,
                "email": user.email,
                "name": user.name,
                "provider": "google"
            }
        )
        
        # 重定向到前端
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(url=f"{frontend_url}?token={access_token}")
        
    except Exception as e:
        logger.error(f"Google OAuth callback failed: {e}")
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        error_params = urlencode({"error": "Authentication failed"})
        return RedirectResponse(url=f"{frontend_url}?{error_params}")

@app.get("/api/auth/github")
async def github_login():
    """初始化GitHub OAuth登录"""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured"
        )
    
    try:
        state = secrets.token_urlsafe(32)
        
        params = {
            'client_id': GITHUB_CLIENT_ID,
            'redirect_uri': GITHUB_REDIRECT_URI,
            'scope': 'user:email',
            'state': state,
            'allow_signup': 'true'
        }
        
        authorization_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
        logger.info("Redirecting to GitHub OAuth")
        return RedirectResponse(url=authorization_url)
        
    except Exception as e:
        logger.error(f"GitHub OAuth initialization failed: {e}")
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        error_params = urlencode({"error": "OAuth initialization failed"})
        return RedirectResponse(url=f"{frontend_url}?{error_params}")

@app.get("/api/auth/github/callback")
async def github_callback(request: Request, db: Session = Depends(get_db)):
    """处理GitHub OAuth回调"""
    try:
        code = request.query_params.get('code')
        error = request.query_params.get('error')
        
        if error:
            raise Exception(f"GitHub OAuth error: {error}")
            
        if not code:
            raise Exception("No authorization code received")
        
        token_data = {
            'client_id': GITHUB_CLIENT_ID,
            'client_secret': GITHUB_CLIENT_SECRET,
            'code': code,
            'redirect_uri': GITHUB_REDIRECT_URI
        }
        
        async with httpx.AsyncClient() as client:
            # 获取访问令牌
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                data=token_data,
                headers={'Accept': 'application/json'}
            )
            
            if token_response.status_code != 200:
                raise Exception("Failed to get access token from GitHub")
                
            token_info = token_response.json()
            access_token = token_info.get('access_token')
            
            if not access_token:
                raise Exception("No access token in GitHub response")
            
            # 获取用户信息
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    'Authorization': f'token {access_token}',
                    'Accept': 'application/json'
                }
            )
            
            if user_response.status_code != 200:
                raise Exception("Failed to get user info from GitHub")
                
            github_user = user_response.json()
            
            # 获取用户邮箱
            email = github_user.get('email')
            if not email:
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        'Authorization': f'token {access_token}',
                        'Accept': 'application/json'
                    }
                )
                
                if email_response.status_code == 200:
                    emails = email_response.json()
                    primary_email = next(
                        (e['email'] for e in emails if e.get('primary', False)), 
                        None
                    )
                    if primary_email:
                        email = primary_email
            
            if not email:
                raise Exception("Unable to get email from GitHub account")
        
        # 准备用户信息
        user_info = {
            'email': email,
            'name': github_user.get('name') or github_user.get('login', ''),
            'picture': github_user.get('avatar_url', ''),
            'github_id': github_user['id'],
            'github_username': github_user.get('login', '')
        }
        
        # 获取或创建用户
        user = get_or_create_user(db, user_info, "github")
        
        # 创建JWT令牌
        access_token = create_access_token(
            data={
                "sub": user.id,
                "email": user.email, 
                "name": user.name,
                "provider": "github"
            }
        )
        
        # 重定向到前端
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(url=f"{frontend_url}?token={access_token}")
        
    except Exception as e:
        logger.error(f"GitHub OAuth callback failed: {e}")
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        error_params = urlencode({"error": "Authentication failed"})
        return RedirectResponse(url=f"{frontend_url}?{error_params}")

@app.get("/api/auth/me")
async def get_current_user(current_user = Depends(verify_token), db: Session = Depends(get_db)):
    """获取当前用户信息"""
    try:
        from database.models import User
        user = db.query(User).filter(User.id == current_user["sub"]).first()
        if not user:
            # 如果数据库中没找到用户，返回token中的信息
            return {
                "id": current_user.get("sub"),
                "email": current_user.get("email"),
                "name": current_user.get("name"),
                "provider": current_user.get("provider", "unknown"),
                "avatar_url": "",
            }
        
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at,
            "last_login": user.last_login,
            "provider": current_user.get("provider", "unknown")
        }
    except Exception as e:
        logger.error(f"Get user info failed: {e}")
        # 返回token中的基本信息
        return {
            "id": current_user.get("sub"),
            "email": current_user.get("email"),
            "name": current_user.get("name"),
            "provider": current_user.get("provider", "unknown"),
            "avatar_url": "",
        }

@app.post("/api/auth/logout")
async def logout():
    """登出（前端需要删除token）"""
    return {"message": "Logged out successfully"}

@app.websocket("/ws/analysis/{task_id}")
async def analysis_stream(websocket: WebSocket, task_id: str):
    token = websocket.query_params.get('token')
    if not token:
        auth_header = websocket.headers.get('authorization')
        if auth_header and auth_header.lower().startswith('bearer '):
            token = auth_header.split(' ', 1)[1]

    if not token:
        await websocket.close(code=4401)
        return

    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    queue = await event_broker.subscribe(task_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await event_broker.unsubscribe(task_id, queue)


@app.get("/api/monitors")
async def list_monitors(current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db_session() as db_session:
        monitors = monitor_crud.list_monitors(db_session, user_id)
        payload = [serialize_monitor(monitor) for monitor in monitors]
    return {'monitors': payload}


@app.post("/api/monitors")
async def create_monitor(request: MonitorCreateRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not request.url.strip():
        raise HTTPException(status_code=400, detail="Monitor URL is required")

    with get_db_session() as db_session:
        monitor = monitor_crud.get_or_create_monitor(
            db_session,
            user_id=user_id,
            url=request.url.strip(),
            name=request.name or request.url.strip()
        )
        payload = serialize_monitor(monitor)
    return payload


@app.patch("/api/monitors/{monitor_id}")
async def rename_monitor(monitor_id: str, request: MonitorRenameRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Monitor name cannot be empty")

    with get_db_session() as db_session:
        monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")
        monitor = monitor_crud.update_monitor_name(db_session, monitor, request.name.strip())
        payload = serialize_monitor(monitor)
    return payload



@app.delete("/api/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db_session() as db_session:
        monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")
        monitor_crud.deactivate_monitor(db_session, monitor)
    return {'status': 'ok'}


def _serialize_competitor_record(record) -> Dict[str, Any]:
    return {
        'id': getattr(record, 'id', None),
        'competitor_id': getattr(record, 'competitor_id', None),
        'display_name': getattr(record, 'display_name', None),
        'primary_url': getattr(record, 'primary_url', None),
        'brief_description': getattr(record, 'brief_description', None),
        'source': getattr(record, 'source', None),
        'demographics': getattr(record, 'demographics', None),
    }


@app.post("/api/competitors/{competitor_id}/track")
async def track_competitor(competitor_id: str, request: CompetitorTrackRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not request.monitor_id:
        raise HTTPException(status_code=400, detail="monitor_id is required")

    with get_db_session() as db_session:
        monitor = monitor_crud.get_monitor(db_session, request.monitor_id, user_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")

        from database.models import Competitor
        from sqlalchemy import or_

        competitor = db_session.query(Competitor).filter(
            or_(
                Competitor.id == competitor_id,
                Competitor.competitor_id == competitor_id
            )
        ).first()

        if not competitor:
            normalized_url = (request.url or '').strip()
            if not normalized_url:
                raise HTTPException(status_code=404, detail="Competitor not found")

            # Ensure URL has protocol for storage consistency
            if not normalized_url.startswith(('http://', 'https://')):
                normalized_url = f'https://{normalized_url}'

            competitor_payload = {
                'competitor_id': competitor_id,
                'display_name': request.display_name or competitor_id,
                'primary_url': normalized_url,
                'brief_description': request.description or '',
                'source': request.source or 'manual',
                'extra_data': {'created_from_monitor': monitor.id},
            }
            if request.confidence is not None:
                competitor_payload['confidence'] = max(0.0, min(1.0, request.confidence))

            competitor, _ = competitor_crud.get_or_create_competitor(
                db_session,
                competitor_id=competitor_id,
                competitor_data=competitor_payload
            )

        monitor_competitor_crud.set_tracking(db_session, monitor.id, competitor.id, True)
        tracked_ids = monitor_competitor_crud.get_tracked_competitor_ids(db_session, monitor.id)

    return {
        'status': 'ok',
        'tracked_competitor_ids': tracked_ids,
        'competitor': _serialize_competitor_record(competitor)
    }


@app.delete("/api/competitors/{competitor_id}/untrack")
async def untrack_competitor(competitor_id: str, request: CompetitorTrackRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not request.monitor_id:
        raise HTTPException(status_code=400, detail="monitor_id is required")

    with get_db_session() as db_session:
        monitor = monitor_crud.get_monitor(db_session, request.monitor_id, user_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found")

        from database.models import Competitor
        from sqlalchemy import or_

        competitor = db_session.query(Competitor).filter(
            or_(
                Competitor.id == competitor_id,
                Competitor.competitor_id == competitor_id
            )
        ).first()
        if not competitor:
            raise HTTPException(status_code=404, detail="Competitor not found")

        monitor_competitor_crud.remove_tracking(db_session, monitor.id, competitor.id)
        tracked_ids = monitor_competitor_crud.get_tracked_competitor_ids(db_session, monitor.id)

    return {
        'status': 'ok',
        'tracked_competitor_ids': tracked_ids,
        'untracked_competitor_id': competitor.id
    }


@app.post("/api/changes/{change_id}/read")
async def mark_change_read(change_id: str, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db_session() as db_session:
        receipt = change_read_crud.mark_read(db_session, user_id, change_id)
    return {'change_id': change_id, 'read_at': receipt.read_at} if receipt else {'change_id': change_id}


@app.post("/api/changes/bulk-read")
async def bulk_read_changes(request: BulkReadRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not request.change_ids:
        return {'updated': 0}

    with get_db_session() as db_session:
        updated = change_read_crud.bulk_mark_read(db_session, user_id, request.change_ids)
    return {'updated': updated}


@app.get("/api/archives")
async def list_archives(current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db_session() as db_session:
        archives = archive_crud.list_archives(db_session, user_id)
        payload = [serialize_archive(archive) for archive in archives]
    return {'archives': payload}


@app.post("/api/archives")
async def create_archive(request: ArchiveCreateRequest, current_user = Depends(require_auth)):
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not request.title.strip():
        raise HTTPException(status_code=400, detail="Archive title is required")

    tenant_snapshot = None
    competitor_snapshot = None
    change_snapshot = None

    with get_db_session() as db_session:
        if request.task_id:
            task = task_crud.get_task(db_session, request.task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            results = task.results or {}
            tenant_snapshot = results.get('tenant')
            competitor_snapshot = results.get('competitors')
            change_snapshot = []
            competitor_analysis = results.get('competitor_analysis') or {}
            for content in competitor_analysis.values():
                if isinstance(content, dict):
                    changes = content.get('changes')
                    if isinstance(changes, dict) and 'changes' in changes:
                        change_snapshot.extend(changes.get('changes') or [])
                    elif isinstance(changes, list):
                        change_snapshot.extend(changes)
            if not change_snapshot:
                change_snapshot = results.get('changes')

        archive = archive_crud.create_archive(
            db_session,
            user_id=user_id,
            monitor_id=request.monitor_id,
            task_id=request.task_id,
            title=request.title.strip(),
            tenant_snapshot=tenant_snapshot,
            competitor_snapshot=competitor_snapshot,
            change_snapshot=change_snapshot,
            metadata=request.metadata or {},
            search_text=(request.metadata or {}).get('search_text') if request.metadata else None
        )

        payload = serialize_archive(archive)

    return payload

@app.post("/api/analyze", response_model=TaskResponse)
async def start_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """启动分析任务"""
    company_name = (request.company_name or '').strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name cannot be empty")
    
    if request.max_competitors < 1 or request.max_competitors > 20:
        raise HTTPException(status_code=400, detail="Max competitors should be between 1-20")
    
    if not validate_config():
        raise HTTPException(status_code=500, detail="Service configuration incomplete")
    
    user_id = current_user.get('sub') if isinstance(current_user, dict) else None
    if not user_id:
        raise HTTPException(status_code=401, detail='Authentication required')

    monitor_id = request.monitor_id

    if monitor_id:
        try:
            with get_db_session() as db_session:
                monitor = monitor_crud.get_monitor(db_session, monitor_id, user_id)
                if not monitor:
                    raise HTTPException(status_code=404, detail='Monitor not found')
        except HTTPException:
            raise
        except Exception as monitor_error:
            logger.error(f'Failed to validate monitor {monitor_id}: {monitor_error}')
            raise HTTPException(status_code=500, detail='Monitor validation failed')
    else:
        base_url = (request.tenant_url or company_name).strip()
        try:
            with get_db_session() as db_session:
                monitor = monitor_crud.get_or_create_monitor(
                    db_session,
                    user_id=user_id,
                    url=base_url or company_name,
                    name=request.monitor_name or company_name
                )
                if monitor:
                    monitor_id = monitor.id
        except Exception as monitor_error:
            logger.warning(f'自动创建监控失败: {monitor_error}')
            monitor_id = None

    task = task_crud.create_task(
        db,
        company_name=company_name,
        config={
            "enable_research": request.enable_research,
            "max_competitors": request.max_competitors,
            "enable_caching": request.enable_caching
        },
        user_id=user_id,
        monitor_id=monitor_id
    )

    event_broker.prime(task.id, [])

    background_tasks.add_task(
        run_analysis_with_persistence,
        task.id,
        company_name,
        request.enable_research,
        request.max_competitors,
        request.enable_caching,
        db,
        user_id,
        monitor_id
    )
    
    logger.info(f"新分析任务已启动: {request.company_name} (ID: {task.id}, 缓存: {'启用' if request.enable_caching else '禁用'})")
    
    cache_message = f", caching {'enabled' if request.enable_caching else 'disabled'}"
    return TaskResponse(
        task_id=task.id,
        message=f"Analysis started with unified ID management{cache_message}",
        monitor_id=monitor_id
    )

@app.get("/api/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str, db: Session = Depends(get_db)):
    """获取任务状态"""
    task = task_crud.get_task(db, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return StatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
        message=task.message or "",
        company_name=task.company_name
    )

@app.get("/api/results/{task_id}")
async def get_results(task_id: str, db: Session = Depends(get_db)):
    """获取任务结果"""
    task = task_crud.get_task(db, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status not in ["completed", "failed"]:
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed yet, current status: {task.status}"
        )
    
    if task.status == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {task.message}"
        )
    
    return {
        "task_id": task.id,
        "status": task.status,
        "results": task.results or {},
        "started_at": task.started_at,
        "completed_at": task.completed_at
    }

@app.get("/api/tasks")
async def get_recent_tasks(limit: int = 10, db: Session = Depends(get_db)):
    """获取最近的任务列表"""
    tasks = task_crud.get_recent_tasks(db, limit=limit)
    return {
        "tasks": [
            {
                "id": task.id,
                "company_name": task.company_name,
                "status": task.status,
                "progress": task.progress,
                "created_at": task.created_at,
                "completed_at": task.completed_at
            }
            for task in tasks
        ]
    }

@app.get("/api/stats")
async def get_system_stats():
    """获取系统统计信息"""
    try:
        db_stats = get_database_stats()
        cache_stats = await change_detection_cache.get_cache_stats()
        
        return {
            "database": db_stats,
            "cache": cache_stats,
            "version": "1.0.0-unified-id-management"
        }
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
        return {
            "error": str(e),
            "version": "1.0.0-unified-id-management"
        }

@app.get("/api/tenants/{tenant_id}/history")
async def get_tenant_history(tenant_id: str):
    """获取租户的分析历史"""
    try:
        with get_db_session() as db:
            tenant = tenant_crud.get_tenant_by_id(db, tenant_id)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")
            
            competitors = tenant_crud.get_tenant_competitors(db, tenant_id)
            
            return {
                "tenant": {
                    "id": tenant.tenant_id,
                    "name": tenant.tenant_name,
                    "description": tenant.tenant_description,
                    "target_market": tenant.target_market,
                    "created_at": tenant.created_at,
                    "updated_at": tenant.updated_at
                },
                "competitors": [
                    {
                        "id": comp.id,
                        "display_name": comp.display_name,
                        "primary_url": comp.primary_url,
                        "brief_description": comp.brief_description
                    }
                    for comp in competitors
                ],
                "total_competitors": len(competitors)
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取租户历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tenant history: {str(e)}")

@app.get("/app")
async def serve_frontend():
    """提供前端页面"""
    frontend_file = os.path.join(project_root, "frontend", "index.html")
    if os.path.exists(frontend_file):
        return FileResponse(frontend_file)
    else:
        raise HTTPException(status_code=404, detail="Frontend page not found")

@app.get("/")
async def root(db: Session = Depends(get_db)):
    """API根路径"""
    try:
        running_tasks = task_crud.get_running_tasks(db)
        all_tasks = task_crud.get_recent_tasks(db, limit=100)
        
        db_stats = get_database_stats()
        cache_stats = await change_detection_cache.get_cache_stats()
    except Exception as e:
        logger.warning(f"获取统计信息失败: {e}")
        running_tasks = []
        all_tasks = []
        db_stats = {"error": str(e)}
        cache_stats = {"error": str(e)}
    
    return {
        "message": "OPP - Competitor Analysis API with OAuth",
        "version": "1.0.0-oauth",
        "database": "connected" if check_database_connection() else "disconnected",
        "active_tasks": len(running_tasks),
        "total_tasks": len(all_tasks),
        "database_stats": db_stats,
        "cache_stats": cache_stats,
        "oauth_providers": ["Google", "GitHub"],
        "auth_configured": {
            "google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
            "github": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)
        },
        "features": [
            "统一的Competitor ID管理",
            "智能映射和一致性检查",  
            "增强的缓存系统",
            "完整的错误处理和日志记录",
            "Google & GitHub OAuth认证"
        ],
        "env_status": {
            "openai_key": "✅" if os.getenv("OPENAI_API_KEY") else "❌",
            "tavily_key": "✅" if os.getenv("TAVILY_API_KEY") else "❌",
            "firecrawl_key": "✅" if os.getenv("FIRECRAWL_API_KEY") else "❌",
        }
    }

if __name__ == "__main__":
    import uvicorn
    print("启动OPP竞争对手分析API服务（统一ID管理 + OAuth版）...")
    print("环境检查...")
    
    if validate_config():
        print("配置验证通过，启动服务器...")
        print("数据库初始化...")
        
        # OAuth配置检查
        oauth_status = []
        if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
            oauth_status.append("Google OAuth: ✅")
        else:
            oauth_status.append("Google OAuth: ❌")
            
        if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
            oauth_status.append("GitHub OAuth: ✅") 
        else:
            oauth_status.append("GitHub OAuth: ❌")
            
        print("OAuth状态:", " | ".join(oauth_status))
        
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    else:
        print("配置验证失败，请检查.env文件")
        print(f"当前工作目录: {os.getcwd()}")
        print(f"项目根目录: {project_root}")
        exit(1)
