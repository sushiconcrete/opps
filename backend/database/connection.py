# backend/database/connection.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
from typing import Generator
from .models import Base
import logging
import urllib.parse

logger = logging.getLogger(__name__)

def get_safe_database_url():
    """安全地获取数据库URL，处理编码问题"""
    try:
        # 从环境变量获取数据库URL
        database_url = os.getenv(
            "DATABASE_URL", 
            "postgresql://postgres:lxq0220@localhost:5432/opp_db"
        )
        
        # 处理可能的编码问题
        if isinstance(database_url, bytes):
            database_url = database_url.decode('utf-8', errors='ignore')
        
        # 确保URL中的特殊字符被正确编码
        # 解析URL以安全地处理密码中的特殊字符
        if '://' in database_url:
            scheme, rest = database_url.split('://', 1)
            
            if '@' in rest:
                credentials, host_part = rest.split('@', 1)
                
                if ':' in credentials:
                    username, password = credentials.split(':', 1)
                    # URL编码密码中的特殊字符
                    password = urllib.parse.quote_plus(password)
                    credentials = f"{username}:{password}"
                
                database_url = f"{scheme}://{credentials}@{host_part}"
        
        logger.info(f"数据库URL处理完成: {database_url.split('@')[0]}@***")
        return database_url
        
    except Exception as e:
        logger.error(f"获取数据库URL时出错: {e}")
        # 返回默认的安全URL
        return "postgresql://postgres:lxq0220@localhost:5432/opp_db"

# 安全获取数据库URL
DATABASE_URL = get_safe_database_url()

# Create engine with robust configuration - FIXED: removed 'encoding' parameter
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
    # 关键修复：添加编码和连接参数
    connect_args={
        "options": "-c timezone=utc",
        "client_encoding": "utf8",  # 明确指定客户端编码
    },
    # REMOVED: encoding='utf-8' - this parameter is not supported in SQLAlchemy 2.0+
    # 处理连接池的编码问题
    pool_reset_on_return='rollback'
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_database_encoding():
    """测试数据库连接的编码设置"""
    try:
        with engine.connect() as conn:
            # 测试UTF-8编码
            result = conn.execute(text("SHOW client_encoding"))
            encoding = result.scalar()
            logger.info(f"数据库客户端编码: {encoding}")
            
            # 测试服务器编码
            result = conn.execute(text("SHOW server_encoding"))
            server_encoding = result.scalar()
            logger.info(f"数据库服务器编码: {server_encoding}")
            
            return True
    except Exception as e:
        logger.error(f"数据库编码测试失败: {e}")
        return False

def init_db():
    """Initialize database, create all tables with proper error handling"""
    try:
        logger.info("Starting database initialization...")
        
        # 首先测试编码
        if not test_database_encoding():
            logger.warning("数据库编码测试失败，但继续初始化")
        
        # Drop and recreate all tables for clean start (be careful in production!)
        try:
            # First, drop foreign key constraints to avoid circular dependencies
            with engine.connect() as conn:
                # Disable foreign key checks temporarily
                conn.execute(text("SET session_replication_role = replica;"))
                
                # Drop all tables
                Base.metadata.drop_all(bind=engine)
                logger.info("已删除现有表结构")
                
                # Re-enable foreign key checks
                conn.execute(text("SET session_replication_role = DEFAULT;"))
                conn.commit()
                
        except Exception as e:
            logger.warning(f"删除表时出现警告: {e}")
            # Try alternative approach - drop tables individually
            try:
                with engine.connect() as conn:
                    # Get all table names
                    result = conn.execute(text("""
                        SELECT tablename FROM pg_tables 
                        WHERE schemaname = 'public' 
                        AND tablename IN (
                            'analysis_tasks', 'tenants', 'competitors', 
                            'tenant_competitors', 'change_detection_cache', 
                            'content_storage', 'competitor_records', 'change_detections',
                            'monitors', 'monitor_competitors', 'change_read_receipts',
                            'analysis_archives', 'users'
                        )
                    """))
                    tables = [row[0] for row in result.fetchall()]
                    
                    # Drop tables in reverse dependency order
                    for table in reversed(tables):
                        try:
                            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                            logger.info(f"已删除表: {table}")
                        except Exception as table_error:
                            logger.warning(f"删除表 {table} 失败: {table_error}")
                    
                    conn.commit()
                    logger.info("已通过CASCADE方式删除所有表")
                    
            except Exception as cascade_error:
                logger.error(f"CASCADE删除也失败: {cascade_error}")
                raise
        
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("已创建新表结构")
        except Exception as e:
            logger.error(f"创建表失败: {e}")
            raise
        
        # Verify tables exist
        with engine.connect() as conn:
            required_tables = [
                'analysis_tasks', 'tenants', 'competitors', 
                'tenant_competitors', 'change_detection_cache', 
                'content_storage', 'competitor_records', 'change_detections',
                'monitors', 'monitor_competitors', 'change_read_receipts',
                'analysis_archives', 'users'
            ]
            
            missing_tables = []
            for table in required_tables:
                try:
                    result = conn.execute(text(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table_name)"
                    ), {"table_name": table})
                    
                    if result.scalar():
                        logger.info(f"✅ Table '{table}' created successfully")
                    else:
                        missing_tables.append(table)
                        logger.error(f"❌ Table '{table}' missing")
                except Exception as e:
                    logger.error(f"检查表 {table} 时出错: {e}")
                    missing_tables.append(table)
            
            if missing_tables:
                raise Exception(f"Failed to create tables: {missing_tables}")
        
        # Create indexes
        _create_additional_indexes()
        
        logger.info("✅ Database initialization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

def _create_additional_indexes():
    """Create performance indexes"""
    try:
        with engine.connect() as conn:
            # Safe index creation with proper error handling
            indexes = [
                """CREATE INDEX IF NOT EXISTS idx_tenant_competitor_lookup 
                   ON tenant_competitors(tenant_id, competitor_id)""",
                """CREATE INDEX IF NOT EXISTS idx_cache_expires_at 
                   ON change_detection_cache(expires_at)""",
                """CREATE INDEX IF NOT EXISTS idx_content_url_tag_created 
                   ON content_storage(url, tag, created_at DESC)""",
                """CREATE INDEX IF NOT EXISTS idx_competitor_id_url
                   ON change_detection_cache(competitor_id, url)""",
                """CREATE INDEX IF NOT EXISTS idx_tenant_id_lookup
                   ON tenants(tenant_id)""",
                """CREATE INDEX IF NOT EXISTS idx_competitor_id_lookup
                   ON competitors(competitor_id)"""
            ]
            
            success_count = 0
            for i, index_sql in enumerate(indexes):
                try:
                    conn.execute(text(index_sql))
                    success_count += 1
                except Exception as e:
                    logger.warning(f"创建索引 {i+1} 失败: {e}")
            
            conn.commit()
            logger.info(f"✅ 成功创建 {success_count}/{len(indexes)} 个数据库索引")
            
    except Exception as e:
        logger.warning(f"⚠️ Error creating indexes: {e}")

def get_db() -> Generator[Session, None, None]:
    """Get database session for FastAPI dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Get database session for regular functions with proper transaction handling"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        db.close()

def check_database_connection():
    """Check database connection with detailed diagnostics"""
    try:
        with engine.connect() as conn:
            # 基本连接测试
            result = conn.execute(text("SELECT 1 as test"))
            test_value = result.scalar()
            
            if test_value != 1:
                logger.error("❌ Database connection test failed")
                return False
            
            # 编码测试
            try:
                result = conn.execute(text("SELECT 'UTF-8测试中文' as encoding_test"))
                encoding_test = result.scalar()
                logger.info("✅ UTF-8编码测试通过")
            except Exception as e:
                logger.warning(f"⚠️ UTF-8编码测试失败: {e}")
            
            # 显示连接信息（隐藏敏感信息）
            masked_url = DATABASE_URL
            if '@' in masked_url:
                parts = masked_url.split('@')
                if len(parts) >= 2:
                    masked_url = parts[0].split('://')[0] + '://***@' + parts[1]
            
            logger.info(f"✅ Database connection successful: {masked_url}")
            return True
                
    except UnicodeDecodeError as e:
        logger.error(f"❌ Database connection encoding error: {e}")
        logger.info("提示: 请检查数据库连接字符串中是否有特殊字符")
        return False
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

def get_database_stats():
    """Get comprehensive database statistics"""
    try:
        with engine.connect() as conn:
            stats = {}
            
            table_counts = [
                'analysis_tasks', 'tenants', 'competitors', 'tenant_competitors',
                'competitor_records', 'change_detection_cache', 'change_detections', 'content_storage'
            ]
            
            for table in table_counts:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    stats[f"{table}_count"] = count
                except Exception as e:
                    stats[f"{table}_count"] = 0
                    logger.warning(f"Could not count table {table}: {e}")
            
            # Cache-specific stats
            try:
                result = conn.execute(text("""
                    SELECT 
                        COUNT(*) as total_cache,
                        COUNT(CASE WHEN expires_at > NOW() THEN 1 END) as active_cache,
                        COUNT(CASE WHEN expires_at <= NOW() THEN 1 END) as expired_cache
                    FROM change_detection_cache
                """))
                cache_row = result.fetchone()
                if cache_row:
                    stats['cache_total'] = cache_row[0]
                    stats['cache_active'] = cache_row[1] 
                    stats['cache_expired'] = cache_row[2]
            except Exception as e:
                logger.warning(f"Could not get cache stats: {e}")
            
            return stats
            
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"error": str(e)}

def cleanup_database():
    """Clean up expired data with proper transaction handling"""
    try:
        with get_db_session() as db:
            expired_count = 0
            old_content_count = 0
            
            # Clean expired cache
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            
            result = db.execute(text("""
                DELETE FROM change_detection_cache 
                WHERE expires_at < :now
            """), {"now": now})
            expired_count = result.rowcount
            
            # Clean old content (30 days)
            cutoff_date = now - timedelta(days=30)
            result = db.execute(text("""
                DELETE FROM content_storage 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            old_content_count = result.rowcount
            
            logger.info(f"Database cleanup: removed {expired_count} expired cache, {old_content_count} old content")
            return {
                "expired_cache_deleted": expired_count,
                "old_content_deleted": old_content_count
            }
            
    except Exception as e:
        logger.error(f"Database cleanup failed: {e}")
        return {"error": str(e)}

# Test database integrity
def test_database_integrity():
    """Test database tables and constraints"""
    try:
        with get_db_session() as db:
            # Test each table exists and is accessible
            tables_to_test = [
                'analysis_tasks', 'tenants', 'competitors', 'tenant_competitors',
                'change_detection_cache', 'content_storage'
            ]
            
            results = {}
            for table in tables_to_test:
                try:
                    result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    results[table] = {"status": "OK", "count": count}
                except Exception as e:
                    results[table] = {"status": "ERROR", "error": str(e)}
            
            return results
            
    except Exception as e:
        logger.error(f"Database integrity test failed: {e}")
        return {"error": str(e)}

def fix_database_encoding():
    """修复数据库编码问题"""
    try:
        with engine.connect() as conn:
            # 设置客户端编码
            conn.execute(text("SET client_encoding TO 'UTF8'"))
            
            # 检查编码设置
            result = conn.execute(text("SHOW client_encoding"))
            encoding = result.scalar()
            logger.info(f"客户端编码已设置为: {encoding}")
            
            return True
            
    except Exception as e:
        logger.error(f"修复数据库编码失败: {e}")
        return False
