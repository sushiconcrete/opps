"""
邮件服务模块
支持Gmail SMTP，预留Amazon SES接口
"""
import os
import logging
import asyncio
from typing import List, Dict, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib
from jinja2 import Template
from datetime import datetime

logger = logging.getLogger(__name__)

class EmailService:
    """邮件服务基类"""
    
    def __init__(self):
        self.provider = os.getenv("EMAIL_PROVIDER", "gmail")  # gmail or ses
        self.sender_email = os.getenv("EMAIL_SENDER", "noreply@example.com")
        self.sender_name = os.getenv("EMAIL_SENDER_NAME", "OPP Agent")
        
        # Gmail SMTP配置
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        
        # 邮件模板
        self.change_alert_template = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; }
        .content { background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }
        .change-card { background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .threat-level { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .threat-high { background: #ff4757; color: white; }
        .threat-medium { background: #ffa502; color: white; }
        .threat-low { background: #2ed573; color: white; }
        .button { display: inline-block; padding: 12px 24px; background: #667eea; color: white; text-decoration: none; border-radius: 6px; margin-top: 20px; }
        .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">🎯 OPP Change Radar Alert</h1>
            <p style="margin: 10px 0 0 0;">{{ date }}</p>
        </div>
        
        <div class="content">
            <h2>Hi {{ user_name }},</h2>
            <p>We've detected <strong>{{ changes_count }}</strong> significant changes from your tracked competitors that exceed your alert threshold of {{ threshold }}.</p>
            
            {% for change in changes %}
            <div class="change-card">
                <div style="display: flex; justify-content: space-between; align-items: start;">
                    <h3 style="margin: 0 0 10px 0;">{{ change.competitor }}</h3>
                    <span class="threat-level {% if change.threat_level >= 7 %}threat-high{% elif change.threat_level >= 4 %}threat-medium{% else %}threat-low{% endif %}">
                        Threat: {{ change.threat_level }}/10
                    </span>
                </div>
                <p><strong>Change:</strong> {{ change.content }}</p>
                <p><strong>Why it matters:</strong> {{ change.why_matter }}</p>
                <p><strong>Suggested action:</strong> {{ change.suggestions }}</p>
                <p style="color: #999; font-size: 12px;">Detected: {{ change.detected_at }}</p>
            </div>
            {% endfor %}
            
            <center>
                <a href="{{ dashboard_url }}" class="button">View Full Dashboard</a>
            </center>
        </div>
        
        <div class="footer">
            <p>You're receiving this because you enabled email alerts for changes above threat level {{ threshold }}.</p>
            <p><a href="{{ settings_url }}">Manage notification settings</a></p>
        </div>
    </div>
</body>
</html>
        """
    
    async def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str, 
        text_content: Optional[str] = None
    ) -> bool:
        """发送邮件"""
        if self.provider == "gmail":
            return await self._send_gmail(to_email, subject, html_content, text_content)
        elif self.provider == "ses":
            return await self._send_ses(to_email, subject, html_content, text_content)
        else:
            logger.error(f"未知的邮件提供商: {self.provider}")
            return False
    
    async def _send_gmail(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str, 
        text_content: Optional[str] = None
    ) -> bool:
        """通过Gmail SMTP发送邮件"""
        try:
            if not self.smtp_username or not self.smtp_password:
                logger.error("Gmail SMTP凭据未配置")
                return False
            
            # 创建邮件
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.sender_name} <{self.smtp_username}>"
            message["To"] = to_email
            
            # 添加文本和HTML内容
            if text_content:
                text_part = MIMEText(text_content, "plain")
                message.attach(text_part)
            
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)
            
            # 发送邮件
            async with aiosmtplib.SMTP(
                hostname=self.smtp_host,
                port=self.smtp_port,
                use_tls=False,
                start_tls=True
            ) as smtp:
                await smtp.login(self.smtp_username, self.smtp_password)
                await smtp.send_message(message)
            
            logger.info(f"邮件发送成功: {to_email} - {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Gmail发送失败: {e}")
            return False
    
    async def _send_ses(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str, 
        text_content: Optional[str] = None
    ) -> bool:
        """通过Amazon SES发送邮件（预留接口）"""
        logger.info("Amazon SES集成待实现")
        # TODO: 实现Amazon SES集成
        # import boto3
        # client = boto3.client('ses', region_name=os.getenv('AWS_REGION', 'us-east-1'))
        return False
    
    async def send_change_alert(
        self, 
        user_email: str,
        user_name: str,
        changes: List[Dict],
        threshold: float
    ) -> bool:
        """发送变化提醒邮件"""
        try:
            # 准备模板数据
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
            template_data = {
                "user_name": user_name,
                "date": datetime.now().strftime("%B %d, %Y"),
                "changes_count": len(changes),
                "threshold": threshold,
                "changes": changes[:10],  # 最多显示10个
                "dashboard_url": frontend_url,
                "settings_url": f"{frontend_url}#settings"
            }
            
            # 渲染模板
            template = Template(self.change_alert_template)
            html_content = template.render(**template_data)
            
            # 简单文本版本
            text_content = f"""
OPP Change Radar Alert

Hi {user_name},

We've detected {len(changes)} significant changes from your tracked competitors 
that exceed your alert threshold of {threshold}.

View full details at: {frontend_url}

You're receiving this because you enabled email alerts.
            """
            
            # 发送邮件
            subject = f"🎯 OPP Alert: {len(changes)} High-Priority Changes Detected"
            return await self.send_email(user_email, subject, html_content, text_content)
            
        except Exception as e:
            logger.error(f"发送变化提醒邮件失败: {e}")
            return False

# 全局邮件服务实例
email_service = EmailService()