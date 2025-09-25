# test_oauth.py - 测试OAuth配置
import os
import sys
from dotenv import load_dotenv

def test_oauth_config():
    """测试OAuth配置是否正确"""
    load_dotenv()
    
    print("=== OAuth配置检查 ===")
    
    # 检查Google OAuth
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    google_redirect = os.getenv("GOOGLE_REDIRECT_URI")
    
    print(f"Google Client ID: {'✅ 已设置' if google_client_id else '❌ 未设置'}")
    print(f"Google Client Secret: {'✅ 已设置' if google_client_secret else '❌ 未设置'}")
    print(f"Google Redirect URI: {google_redirect or '❌ 未设置'}")
    
    # 检查GitHub OAuth
    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    github_redirect = os.getenv("GITHUB_REDIRECT_URI")
    
    print(f"GitHub Client ID: {'✅ 已设置' if github_client_id else '❌ 未设置'}")
    print(f"GitHub Client Secret: {'✅ 已设置' if github_client_secret else '❌ 未设置'}")
    print(f"GitHub Redirect URI: {github_redirect or '❌ 未设置'}")
    
    # 检查JWT配置
    jwt_secret = os.getenv("JWT_SECRET_KEY")
    print(f"JWT Secret Key: {'✅ 已设置' if jwt_secret else '❌ 未设置'}")
    
    # 检查前端URL
    frontend_url = os.getenv("FRONTEND_URL")
    print(f"Frontend URL: {frontend_url or '❌ 未设置'}")
    
    # 总结
    google_ready = google_client_id and google_client_secret
    github_ready = github_client_id and github_client_secret
    
    print("\n=== 配置状态 ===")
    if google_ready:
        print("✅ Google OAuth 已配置")
    else:
        print("❌ Google OAuth 未完全配置")
        
    if github_ready:
        print("✅ GitHub OAuth 已配置")
    else:
        print("❌ GitHub OAuth 未完全配置")
    
    if not google_ready and not github_ready:
        print("⚠️  至少需要配置一个OAuth提供商")
        return False
        
    return True

def test_dependencies():
    """测试Python依赖"""
    print("\n=== 依赖检查 ===")
    required_packages = [
        'google-auth',
        'google-auth-oauthlib', 
        'google-auth-httplib2',
        'python-jose',
        'passlib',
        'httpx',
        'requests'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package}")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  缺少以下包，请安装:")
        print(f"pip install {' '.join(missing)}")
        return False
        
    return True

if __name__ == "__main__":
    print("OAuth配置测试工具")
    print("="*30)
    
    config_ok = test_oauth_config()
    deps_ok = test_dependencies()
    
    if config_ok and deps_ok:
        print("\n🎉 所有检查通过！OAuth应该可以正常工作")
    else:
        print("\n❌ 存在配置问题，请修复后重试")
        sys.exit(1)