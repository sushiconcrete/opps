"""
邮件发送任务
"""
import logging
from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db_session, user_preferences_crud
from ..database.models import User, UserPreferences, ChangeDetection, Monitor
from .email_service import email_service

logger = logging.getLogger(__name__)

async def send_daily_change_alerts():
    """发送每日变化提醒邮件"""
    try:
        logger.info("开始发送每日变化提醒邮件...")
        
        with get_db_session() as db:
            # 获取启用邮件提醒的用户
            alert_users = user_preferences_crud.get_users_for_email_alerts(db)
            
            for user, preferences in alert_users:
                if preferences.email_frequency != "daily":
                    continue
                
                # 检查是否已发送今日邮件
                if preferences.last_email_sent:
                    if preferences.last_email_sent.date() == datetime.utcnow().date():
                        logger.info(f"用户 {user.email} 今日已发送邮件，跳过")
                        continue
                
                # 获取用户的所有monitors
                monitors = db.query(Monitor).filter(
                    Monitor.user_id == user.id,
                    Monitor.is_active == True
                ).all()
                
                if not monitors:
                    continue
                
                monitor_ids = [m.id for m in monitors]
                
                # 获取过去24小时的高威胁变化
                yesterday = datetime.utcnow() - timedelta(days=1)
                changes = db.query(ChangeDetection).filter(
                    ChangeDetection.monitor_id.in_(monitor_ids),
                    ChangeDetection.threat_level >= preferences.email_alert_threshold,
                    ChangeDetection.detected_at >= yesterday
                ).order_by(
                    ChangeDetection.threat_level.desc(),
                    ChangeDetection.detected_at.desc()
                ).limit(20).all()
                
                if not changes:
                    logger.info(f"用户 {user.email} 没有需要提醒的变化")
                    continue
                
                # 准备邮件数据
                changes_data = []
                for change in changes:
                    # 获取竞争对手名称
                    from ..database.models import Competitor
                    competitor = db.query(Competitor).filter(
                        Competitor.competitor_id == change.competitor_id
                    ).first()
                    
                    changes_data.append({
                        "competitor": competitor.display_name if competitor else change.competitor_id,
                        "url": change.url,
                        "content": change.content,
                        "threat_level": change.threat_level,
                        "why_matter": change.why_matter,
                        "suggestions": change.suggestions,
                        "detected_at": change.detected_at.strftime("%Y-%m-%d %H:%M")
                    })
                
                # 发送邮件
                success = await email_service.send_change_alert(
                    user.email,
                    user.name,
                    changes_data,
                    preferences.email_alert_threshold
                )
                
                if success:
                    # 更新最后发送时间
                    preferences.last_email_sent = datetime.utcnow()
                    db.commit()
                    logger.info(f"成功发送邮件给 {user.email}: {len(changes)} 个变化")
                else:
                    logger.error(f"发送邮件给 {user.email} 失败")
        
        logger.info("每日变化提醒邮件发送完成")
        
    except Exception as e:
        logger.error(f"发送每日变化提醒邮件失败: {e}")

async def send_immediate_alert(user_id: str, changes: List[ChangeDetection]):
    """发送即时提醒（高威胁变化）"""
    try:
        with get_db_session() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return
            
            preferences = user_preferences_crud.get_or_create_preferences(db, user_id)
            
            if not preferences.email_alerts_enabled:
                return
            
            if preferences.email_frequency != "immediate":
                return
            
            # 准备邮件数据
            changes_data = []
            for change in changes[:5]:  # 最多5个
                from ..database.models import Competitor
                competitor = db.query(Competitor).filter(
                    Competitor.competitor_id == change.competitor_id
                ).first()
                
                changes_data.append({
                    "competitor": competitor.display_name if competitor else change.competitor_id,
                    "url": change.url,
                    "content": change.content,
                    "threat_level": change.threat_level,
                    "why_matter": change.why_matter,
                    "suggestions": change.suggestions,
                    "detected_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                })
            
            # 发送邮件
            await email_service.send_change_alert(
                user.email,
                user.name,
                changes_data,
                preferences.email_alert_threshold
            )
            
            logger.info(f"发送即时提醒给 {user.email}: {len(changes)} 个高威胁变化")
            
    except Exception as e:
        logger.error(f"发送即时提醒失败: {e}")