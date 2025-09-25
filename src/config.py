# src/config.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Config:
    """集中管理配置"""

    # API Keys
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
    FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')

    # Rate Limits
    FIRECRAWL_LIMIT_PER_MIN = 10
    TAVILY_LIMIT_PER_MIN = 60

    # Concurrency
    MAX_CONCURRENT_SCRAPES = 5
    MAX_CONCURRENT_SEARCHES = 10

    # Timeouts
    SCRAPE_TIMEOUT = 30
    SEARCH_TIMEOUT = 10