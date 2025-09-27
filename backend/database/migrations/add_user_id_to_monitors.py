"""
添加Change Radar增强功能的迁移脚本
运行: python backend/database/migrations/add_change_enhancements.py
"""
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from backend.database.connection import engine, get_db_session
from backend.database.models import UserPreferences, User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_change_enhancements():
    """添加Change Radar增强功能"""
    try:
        with engine.connect() as conn:
            # 1. 添加is_first字段到change_detections表
            logger.info("检查change_detections表的is_first字段...")
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='change_detections' AND column_name='is_first'
            """))
            
            if not result.fetchone():
                logger.info("添加is_first字段到change_detections表...")
                conn.execute(text("""
                    ALTER TABLE change_detections 
                    ADD COLUMN is_first BOOLEAN DEFAULT TRUE
                """))
                
                # 创建索引
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_change_is_first 
                    ON change_detections(is_first)
                """))
            
            # 2. 添加monitor_id字段到change_detections表
            logger.info("检查change_detections表的monitor_id字段...")
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='change_detections' AND column_name='monitor_id'
            """))
            
            if not result.fetchone():
                logger.info("添加monitor_id字段到change_detections表...")
                conn.execute(text("""
                    ALTER TABLE change_detections 
                    ADD COLUMN monitor_id VARCHAR
                """))
                
                # 添加外键约束
                conn.execute(text("""
                    ALTER TABLE change_detections 
                    ADD CONSTRAINT fk_change_monitor 
                    FOREIGN KEY (monitor_id) REFERENCES monitors(id)
                """))
                
                # 创建索引
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_change_monitor 
                    ON change_detections(monitor_id)
                """))
                
                # 创建复合索引
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_change_detection_query 
                    ON change_detections(monitor_id, detected_at DESC, is_first)
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_change_detection_threat 
                    ON change_detections(threat_level, detected_at DESC)
                """))
            
            # 3. 创建user_preferences表
            logger.info("创建user_preferences表...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR UNIQUE NOT NULL REFERENCES users(id),
                    change_view_threshold FLOAT DEFAULT 0.0,
                    email_alert_threshold FLOAT DEFAULT 7.0,
                    email_alerts_enabled BOOLEAN DEFAULT FALSE,
                    email_frequency VARCHAR DEFAULT 'daily',
                    email_time VARCHAR DEFAULT '09:00',
                    last_email_sent TIMESTAMP,
                    default_page_size INTEGER DEFAULT 10,
                    theme VARCHAR DEFAULT 'system',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # 创建索引
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_user_preferences_user 
                ON user_preferences(user_id)
            """))
            
            conn.commit()
            logger.info("✅ 数据库迁移完成")
            
            # 4. 为现有用户创建默认偏好设置
            with get_db_session() as db:
                users = db.query(User).all()
                for user in users:
                    existing_pref = db.query(UserPreferences).filter(
                        UserPreferences.user_id == user.id
                    ).first()
                    
                    if not existing_pref:
                        pref = UserPreferences(
                            user_id=user.id,
                            change_view_threshold=0.0,
                            email_alert_threshold=7.0,
                            email_alerts_enabled=False
                        )
                        db.add(pref)
                        logger.info(f"为用户 {user.email} 创建默认偏好设置")
                
                db.commit()
            
            return True
            
    except Exception as e:
        logger.error(f"迁移失败: {e}")
        return False

if __name__ == "__main__":
    if migrate_change_enhancements():
        print("✅ Change Radar增强迁移成功完成")
    else:
        print("❌ 迁移失败")
        sys.exit(1)