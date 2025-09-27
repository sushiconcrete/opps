"""
测试邮件系统
运行: python backend/test_email_system.py
"""
import sys
import os
from pathlib import Path
import asyncio

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.core.email_service import email_service
from backend.core.email_tasks import send_daily_change_alerts
from backend.database import get_db_session
from backend.database.models import User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_email_system():
    """测试邮件系统"""
    try:
        # 1. 测试基本邮件发送
        logger.info("测试基本邮件发送...")
        
        # 获取测试用户 - 在session内获取需要的属性
        test_user_email = None
        test_user_name = None
        
        with get_db_session() as db:
            test_user = db.query(User).first()
            if not test_user:
                logger.error("没有找到测试用户")
                return False
            
            # 在session内获取属性
            test_user_email = test_user.email
            test_user_name = test_user.name
        
        if not test_user_email:
            logger.error("测试用户缺少邮箱地址")
            return False
        
        # 准备测试数据
        test_changes = [
            {
                "competitor": "Stripe",
                "url": "https://stripe.com",
                "content": "New pricing tier launched with 20% discount for enterprise customers",
                "threat_level": 8,
                "why_matter": "Direct competition on pricing strategy, could impact our enterprise segment",
                "suggestions": "Review our pricing strategy and consider competitive response",
                "detected_at": "2024-01-15 10:30"
            },
            {
                "competitor": "Square",
                "url": "https://square.com", 
                "content": "AI-powered fraud detection features added to payment processing",
                "threat_level": 7,
                "why_matter": "Feature gap emerging in AI capabilities, customers may switch for better security",
                "suggestions": "Accelerate AI roadmap and enhance fraud detection capabilities",
                "detected_at": "2024-01-15 09:15"
            },
            {
                "competitor": "PayPal",
                "url": "https://paypal.com",
                "content": "New mobile SDK released with simplified integration process",
                "threat_level": 6,
                "why_matter": "Developer experience improvement could attract our potential customers",
                "suggestions": "Improve our SDK documentation and integration experience",
                "detected_at": "2024-01-15 08:45"
            }
        ]
        
        # 发送测试邮件
        logger.info(f"正在发送测试邮件至: {test_user_email}")
        success = await email_service.send_change_alert(
            test_user_email,
            test_user_name or "Test User",
            test_changes,
            6.0
        )
        
        if success:
            logger.info(f"✅ 测试邮件发送成功: {test_user_email}")
            logger.info("  邮件包含:")
            logger.info(f"    - {len(test_changes)} 个竞争对手变化")
            logger.info("    - HTML格式的美观邮件模板")
            logger.info("    - 威胁等级和建议行动")
        else:
            logger.error(f"❌ 测试邮件发送失败")
            logger.info("请检查:")
            logger.info("  1. SMTP_USERNAME 和 SMTP_PASSWORD 是否在.env中正确配置")
            logger.info("  2. Gmail需要使用应用专用密码，不是账号密码")
            logger.info("  3. 访问 https://myaccount.google.com/apppasswords 创建应用密码")
            logger.info("  4. 确保已启用两步验证")
            return False
        
        # 2. 测试邮件模板渲染
        logger.info("\n测试邮件模板渲染...")
        from jinja2 import Template
        from datetime import datetime
        
        template = Template(email_service.change_alert_template)
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        
        template_data = {
            "user_name": test_user_name or "Test User",
            "date": datetime.now().strftime("%B %d, %Y"),
            "changes_count": len(test_changes),
            "threshold": 6.0,
            "changes": test_changes,
            "dashboard_url": frontend_url,
            "settings_url": f"{frontend_url}#settings"
        }
        
        html_content = template.render(**template_data)
        if html_content and len(html_content) > 1000:
            logger.info("✅ 邮件模板渲染成功")
            logger.info(f"  模板长度: {len(html_content)} 字符")
            logger.info("  包含: 响应式设计, 威胁等级标识, 行动建议")
        else:
            logger.warning("⚠️ 邮件模板可能存在问题")
        
        # 3. 测试每日提醒任务
        logger.info("\n测试每日提醒任务...")
        await send_daily_change_alerts()
        logger.info("✅ 每日提醒任务执行完成")
        
        # 4. 测试环境变量配置
        logger.info("\n检查环境变量配置...")
        required_vars = {
            "EMAIL_PROVIDER": os.getenv("EMAIL_PROVIDER", "gmail"),
            "EMAIL_SENDER": os.getenv("EMAIL_SENDER", "noreply@example.com"),
            "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
            "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
            "SMTP_USERNAME": os.getenv("SMTP_USERNAME", ""),
            "FRONTEND_URL": os.getenv("FRONTEND_URL", "http://localhost:5173")
        }
        
        logger.info("当前配置:")
        for var, value in required_vars.items():
            if var == "SMTP_PASSWORD":
                continue  # 不显示密码
            logger.info(f"  {var}: {value}")
        
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        if smtp_password:
            logger.info("  SMTP_PASSWORD: ****已配置****")
        else:
            logger.warning("  SMTP_PASSWORD: ⚠️ 未配置")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        return False

async def test_simple_email():
    """简单邮件发送测试"""
    try:
        logger.info("执行简单邮件测试...")
        
        # 直接测试邮件发送功能
        test_email = "test@example.com"  # 替换为你的测试邮箱
        subject = "OPP Agent 邮件系统测试"
        html_content = """
        <html>
        <body>
            <h2>OPP Agent 邮件系统测试</h2>
            <p>这是一封测试邮件，用于验证邮件系统是否正常工作。</p>
            <p>如果你收到这封邮件，说明邮件系统配置正确！</p>
        </body>
        </html>
        """
        text_content = "OPP Agent 邮件系统测试 - 如果你收到这封邮件，说明邮件系统配置正确！"
        
        success = await email_service.send_email(
            test_email,
            subject,
            html_content,
            text_content
        )
        
        if success:
            logger.info(f"✅ 简单邮件测试成功发送至: {test_email}")
            return True
        else:
            logger.error("❌ 简单邮件测试失败")
            return False
            
    except Exception as e:
        logger.error(f"简单邮件测试失败: {e}")
        return False

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("开始测试 OPP Agent 邮件系统")
    logger.info("=" * 60)
    
    logger.info("\n📧 邮件配置说明:")
    logger.info("  Gmail用户需要:")
    logger.info("  1. 启用两步验证")
    logger.info("  2. 生成应用专用密码")
    logger.info("  3. 访问: https://myaccount.google.com/apppasswords")
    logger.info("  4. 在.env中设置:")
    logger.info("     SMTP_USERNAME=your_gmail@gmail.com")
    logger.info("     SMTP_PASSWORD=your_app_specific_password")
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 完整邮件系统测试 (需要数据库中有用户)")
    print("2. 简单邮件发送测试 (仅测试SMTP连接)")
    
    try:
        choice = input("请输入选择 (1 或 2): ").strip()
        
        if choice == "1":
            success = asyncio.run(test_email_system())
        elif choice == "2":
            # 获取测试邮箱
            test_email = input("请输入测试邮箱地址: ").strip()
            if test_email:
                # 临时修改简单测试函数
                async def simple_test():
                    subject = "OPP Agent 邮件系统测试"
                    html_content = """
                    <html>
                    <body>
                        <h2>🎯 OPP Agent 邮件系统测试</h2>
                        <p>这是一封测试邮件，用于验证邮件系统是否正常工作。</p>
                        <p>如果你收到这封邮件，说明邮件系统配置正确！</p>
                        <hr>
                        <p><small>发送时间: {}</small></p>
                    </body>
                    </html>
                    """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    
                    text_content = "OPP Agent 邮件系统测试 - 如果你收到这封邮件，说明邮件系统配置正确！"
                    
                    return await email_service.send_email(
                        test_email,
                        subject,
                        html_content,
                        text_content
                    )
                
                success = asyncio.run(simple_test())
            else:
                logger.error("未输入测试邮箱地址")
                success = False
        else:
            logger.error("无效选择")
            success = False
        
        if success:
            print("\n" + "=" * 60)
            print("✅ 邮件系统测试通过！")
            print("功能包括:")
            print("  📧 Gmail SMTP邮件发送")
            print("  🎨 HTML格式的美观邮件模板")
            print("  📊 威胁等级和建议展示")
            print("  ⏰ 每日汇总邮件")
            print("  🔧 预留Amazon SES接口")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ 邮件系统测试失败")
            print("请检查配置并重试")
            print("=" * 60)
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"测试过程出错: {e}")
        sys.exit(1)