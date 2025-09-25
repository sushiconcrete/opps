# create_users_table_simple.py - 适配你现有数据库结构
import os
import sys
from pathlib import Path

# 添加backend路径
backend_dir = Path(__file__).parent / 'backend'
sys.path.insert(0, str(backend_dir))

def create_users_table():
    """使用你现有的数据库系统创建users表"""
    try:
        # 导入你现有的数据库模块
        from database import init_db, check_database_connection
        from database.models import Base, User
        from database.connection import engine
        
        print("正在检查数据库连接...")
        if not check_database_connection():
            print("❌ 数据库连接失败")
            return False
        
        print("正在创建users表...")
        
        # 只创建User表，不影响其他表
        User.__table__.create(engine, checkfirst=True)
        
        print("✅ users表创建成功")
        
        # 验证表是否存在
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'users' in tables:
            columns = inspector.get_columns('users')
            print(f"\n📋 users表结构 ({len(columns)} 列):")
            for col in columns:
                print(f"  - {col['name']}: {col['type']}")
            return True
        else:
            print("❌ users表创建失败")
            return False
            
    except Exception as e:
        print(f"❌ 创建users表时出错: {e}")
        return False

if __name__ == "__main__":
    print("=== 创建users表 ===")
    
    success = create_users_table()
    
    if success:
        print("\n🎉 users表创建完成!")
        print("\n接下来:")
        print("1. 修复app.py中的datetime使用")
        print("2. 重启后端服务器")
        print("3. 测试OAuth登录")
    else:
        print("\n❌ 创建失败")
        sys.exit(1)