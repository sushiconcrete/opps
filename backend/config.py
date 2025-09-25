# backend/config.py
import os
from dotenv import load_dotenv
from functools import lru_cache

# 加载环境变量
load_dotenv(override=True)

@lru_cache()
class Settings:
    """应用配置"""
    
    # Application
    APP_NAME: str = "OPP Agent"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://opp_user:opp_password@localhost:5432/opp_db"
    )
    REDIS_URL: str = os.getenv(
        "REDIS_URL", 
        "redis://localhost:6379/0"
    )
    
    # Authentication
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    
    # API Keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")
    
    # Rate Limits
    FIRECRAWL_LIMIT_PER_MIN: int = 10
    TAVILY_LIMIT_PER_MIN: int = 60
    OPENAI_LIMIT_PER_MIN: int = 500
    
    # Concurrency
    MAX_CONCURRENT_SCRAPES: int = 5
    MAX_CONCURRENT_SEARCHES: int = 10
    MAX_GLOBAL_CONCURRENT: int = 10  # 为同事预留
    
    # Features (为同事预留的开关)
    USE_MCP_POOL: bool = False
    ENABLE_PRIORITY_QUEUE: bool = False
    ENABLE_ONGOING_TRACKING: bool = False
    
    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30  # seconds
    WS_CONNECTION_TIMEOUT: int = 600  # seconds
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    class Config:
        case_sensitive = True
        env_file = ".env"

@lru_cache()
def get_settings():
    """获取配置单例"""
    return Settings()

settings = get_settings()