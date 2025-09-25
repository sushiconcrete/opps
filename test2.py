#!/usr/bin/env python3
# test_proxy_tracking.py
"""测试修改后的tracking.py代理功能"""

import asyncio
import os
import logging
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_archive_proxy():
    """测试Archive代理功能"""
    try:
        from src.core.tracking import ArchiveTracker
        
        # 显示当前代理配置
        http_proxy = os.getenv('HTTP_PROXY')
        https_proxy = os.getenv('HTTPS_PROXY')
        print(f"当前代理配置:")
        print(f"  HTTP_PROXY: {http_proxy}")
        print(f"  HTTPS_PROXY: {https_proxy}")
        
        # 创建Archive跟踪器
        print("\n创建Archive跟踪器...")
        tracker = ArchiveTracker(batch_size=2)
        
        # 测试URL
        test_urls = [
            "https://www.example.com",
            "https://www.google.com"
        ]
        
        print(f"\n开始测试Archive访问: {test_urls}")
        
        results = []
        async for result in tracker.compare_stream(test_urls, day_delta=20):
            url = result.get('url', 'unknown')
            error = result.get('error')
            has_diff = 'gitdiff' in result and result['gitdiff'] != 'No changes found.'
            
            if error:
                print(f"  {url}: 错误 - {error}")
            elif has_diff:
                print(f"  {url}: 检测到变化")
            else:
                print(f"  {url}: 无变化")
            
            results.append(result)
        
        print(f"\n测试完成，处理了 {len(results)} 个URL")
        return results
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_basic_import():
    """测试基本导入"""
    try:
        print("测试模块导入...")
        from src.core.tracking import ArchiveTracker, OngoingTracker
        print("✅ 模块导入成功")
        
        # 测试代理配置函数
        from src.core.tracking import get_proxy_config
        proxy_config = get_proxy_config()
        print(f"✅ 代理配置: {proxy_config}")
        
        return True
        
    except Exception as e:
        logger.error(f"导入测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主测试函数"""
    print("=" * 50)
    print("Archive代理功能测试")
    print("=" * 50)
    
    # 第一步：测试导入
    if not await test_basic_import():
        print("❌ 基础导入失败，请检查文件路径")
        return
    
    # 第二步：测试Archive代理
    print("\n" + "=" * 30)
    print("Archive代理访问测试")
    print("=" * 30)
    
    results = await test_archive_proxy()
    
    if results:
        print("✅ Archive代理测试完成")
        
        # 统计结果
        success_count = sum(1 for r in results if not r.get('error'))
        error_count = len(results) - success_count
        
        print(f"统计: 成功 {success_count}, 错误 {error_count}")
        
    else:
        print("❌ Archive代理测试失败")

if __name__ == "__main__":
    # 确保设置了环境变量
    if not os.getenv('HTTP_PROXY') and not os.getenv('HTTPS_PROXY'):
        print("警告: 未检测到代理环境变量")
        print("请先设置: $env:HTTP_PROXY='http://127.0.0.1:7897'")
        print("           $env:HTTPS_PROXY='http://127.0.0.1:7897'")
    
    asyncio.run(main())