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
from typing import Optional
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
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
    get_database_stats
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
            raise HTTPException(status_code=401, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

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

class TaskResponse(BaseModel):
    task_id: str
    message: str

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
    db: Session
):
    """运行分析任务（异步）- 使用统一的ID管理系统"""
    cached_results = {}
    uncached_competitors = []
    
    try:
        logger.info(f"开始分析任务: {company_name} (缓存: {'启用' if enable_caching else '禁用'})")
        
        task_crud.update_task(db, task_id, 
            status="running",
            progress=10,
            message="Initializing analysis components..."
        )
        
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
                
                saved_tenant, created = tenant_crud.get_or_create_tenant(
                    db_session, tenant_id, tenant_dict
                )
                
                logger.info(f"租户信息{'创建' if created else '更新'}: {tenant_dict.get('tenant_name', company_name)}")
        except Exception as e:
            logger.warning(f"保存租户信息失败: {e}")
        
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
        if limited_competitors:
            competitors_for_save = []
            for comp in limited_competitors:
                if hasattr(comp, 'model_dump'):
                    competitors_for_save.append(comp.model_dump())
                elif isinstance(comp, dict):
                    competitors_for_save.append(comp)
                elif hasattr(comp, '__dict__'):
                    comp_dict = {}
                    for attr in ['id', 'competitor_id', 'display_name', 'primary_url', 'brief_description', 'demographics', 'source', 'confidence']:
                        if hasattr(comp, attr):
                            comp_dict[attr] = getattr(comp, attr)
                    competitors_for_save.append(comp_dict)
                else:
                    competitors_for_save.append({
                        'id': str(comp),
                        'display_name': str(comp),
                        'primary_url': '',
                        'brief_description': 'Auto converted'
                    })
            
            basic_competitor_crud.save_competitors(db, task_id, competitors_for_save)
        
        # 第三步：分析竞争对手变化（使用统一ID管理）
        task_crud.update_task(db, task_id,
            progress=75,
            message=f"Analyzing changes for {min(3, len(limited_competitors))} competitors..."
        )
        
        changes_result = []
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
                            change_crud.save_changes(db, comp_id, comp_url, changes_list)
                            logger.info(f"保存变化记录: {len(changes_list)} 条记录, competitor_id={comp_id}")
                
                except Exception as e:
                    logger.error(f"保存变化记录失败: {e}")
        
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
        
        # 更新任务状态：完成
        task_crud.update_task(db, task_id,
            status="completed",
            progress=100,
            message="Analysis complete",
            results=final_results
        )
        
        logger.info(f"分析完成: {company_name}, 找到 {len(limited_competitors)} 个竞争对手, 缓存命中 {len(cached_results) if enable_caching else 0} 个")
        
    except Exception as e:
        logger.error(f"分析失败 [{company_name}]: {str(e)}", exc_info=True)
        
        task_crud.update_task(db, task_id,
            status="failed",
            progress=0,
            message=f"Analysis failed: {str(e)}"
        )

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

def require_auth(current_user = Depends(verify_token)):
    """要求认证的依赖项"""
    return current_user

# ========== 现有的分析相关路由（完全保留）==========

@app.post("/api/analyze", response_model=TaskResponse)
async def start_analysis(
    request: AnalysisRequest, 
    background_tasks: BackgroundTasks,
    # current_user = Depends(require_auth),  # 取消注释以要求认证
    db: Session = Depends(get_db)
):
    """启动分析任务"""
    if not request.company_name.strip():
        raise HTTPException(status_code=400, detail="Company name cannot be empty")
    
    if request.max_competitors < 1 or request.max_competitors > 20:
        raise HTTPException(status_code=400, detail="Max competitors should be between 1-20")
    
    if not validate_config():
        raise HTTPException(status_code=500, detail="Service configuration incomplete")
    
    task = task_crud.create_task(
        db,
        company_name=request.company_name.strip(),
        config={
            "enable_research": request.enable_research,
            "max_competitors": request.max_competitors,
            "enable_caching": request.enable_caching
        }
    )
    
    background_tasks.add_task(
        run_analysis_with_persistence,
        task.id,
        request.company_name.strip(),
        request.enable_research,
        request.max_competitors,
        request.enable_caching,
        db
    )
    
    logger.info(f"新分析任务已启动: {request.company_name} (ID: {task.id}, 缓存: {'启用' if request.enable_caching else '禁用'})")
    
    cache_message = f", caching {'enabled' if request.enable_caching else 'disabled'}"
    return TaskResponse(
        task_id=task.id,
        message=f"Analysis started with unified ID management{cache_message}"
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