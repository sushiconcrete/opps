# src/core/crawler.py
"""
Crawl4AI-based web crawler with separate concurrency pools for background and realtime crawling.

This module provides:
1. background_crawl: 70% concurrency for batch URL tracking
2. realtime_crawl: 30% concurrency for immediate user requests
Both support streaming mode with async iteration.
"""

import asyncio
from typing import List, Union, AsyncGenerator, Tuple
from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.async_dispatcher import CrawlerMonitor
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

@dataclass
class CrawlConfig:
    """Configuration for crawl operations"""
    total_concurrent: int = 30  # Total concurrent crawlers
    memory_threshold: float = 70.0  # Memory threshold percentage
    enable_monitoring: bool = False  # Enable real-time monitoring


class CrawlerManager:
    """Manages background and realtime crawling with separate concurrency pools"""
    
    def __init__(self, config: CrawlConfig = None):
        """
        Initialize crawler manager with configuration
        
        Args:
            config: CrawlConfig instance with settings
        """
        self.config = config or CrawlConfig()
        
        # Calculate concurrency allocation
        self.background_concurrent = int(self.config.total_concurrent * 0.3)
        self.realtime_concurrent = int(self.config.total_concurrent * 0.7)
        
        # Ensure at least 1 concurrent for each pool
        self.background_concurrent = max(1, self.background_concurrent)
        self.realtime_concurrent = max(1, self.realtime_concurrent)
        
    def _create_dispatcher(self, max_concurrent: int) -> MemoryAdaptiveDispatcher:
        """Create a MemoryAdaptiveDispatcher with built-in rate limiting"""
        from crawl4ai.async_dispatcher import RateLimiter
        
        # Create monitor if enabled
        monitor = None
        if self.config.enable_monitoring:
            try:
                from crawl4ai.async_dispatcher import CrawlerMonitor
                monitor = CrawlerMonitor()
            except Exception:
                monitor = None
        
        # Create dispatcher with built-in rate limiting
        return MemoryAdaptiveDispatcher(
            memory_threshold_percent=self.config.memory_threshold,
            check_interval=1.0,
            max_session_permit=max_concurrent,
            rate_limiter=RateLimiter(
                base_delay=(1.0, 2.0),  # 1-2 second delays between requests
                max_delay=30.0,         # Cap at 30 seconds
                max_retries=2           # Retry failed requests
            ),
            monitor=monitor
        )
    
    async def background_crawl(
        self, 
        urls: Union[str, List[str]]
    ) -> AsyncGenerator[object, None]:
        """
        Crawl URLs in background mode with 70% concurrency allocation
        
        Args:
            urls: Single URL or list of URLs to crawl
            
        Yields:
            Raw CrawlResult objects from crawl4ai
        """
        # Normalize URLs to list
        if isinstance(urls, str):
            urls = [urls]
        
        # Create dispatcher for background tasks
        dispatcher = self._create_dispatcher(self.background_concurrent)
        
        # Configure crawler
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,  # Fresh content for tracking
            markdown_generator=DefaultMarkdownGenerator(),
            check_robots_txt=True,
            screenshot=False,
            verbose=False,
            page_timeout=30000,  # 30 second timeout per page
            exclude_all_images=True
        )
        
        # Stream results
        async with AsyncWebCrawler() as crawler:
            results = await crawler.arun_many(
                urls=urls,
                config=config,
                dispatcher=dispatcher
            )
            
            # Yield ALL results - successful and failed
            for result in results:
                yield result
                    
    async def realtime_crawl(
        self, 
        urls: Union[str, List[str]]
    ) -> AsyncGenerator[object, None]:
        """
        Crawl URLs in realtime mode with 30% concurrency allocation
        
        Args:
            urls: Single URL or list of URLs to crawl
            
        Yields:
            Raw CrawlResult objects from crawl4ai
        """
        # Normalize URLs to list
        if isinstance(urls, str):
            urls = [urls]
        
        # Create dispatcher for realtime tasks
        dispatcher = self._create_dispatcher(self.realtime_concurrent)
        
        # Configure crawler (prioritize speed)
        config = CrawlerRunConfig(
            cache_mode=CacheMode.ENABLED,  # Use cache for speed
            markdown_generator=DefaultMarkdownGenerator(),
            check_robots_txt=False,  # Skip for speed in realtime
            screenshot=False,
            verbose=False,
            page_timeout=60000,  # 30 second timeout for archive URLs
            exclude_all_images=True
        )
        
        # Stream results
        async with AsyncWebCrawler() as crawler:
            results = await crawler.arun_many(
                urls=urls,
                config=config,
                dispatcher=dispatcher
            )
            
            # Yield ALL results - successful and failed
            for result in results:
                yield result

    # async def get_first_comparison(self, urls: List[str]) -> str:


import time

async def main():
    crawler = CrawlerManager()
    urls = [
        "https://www.ycombinator.com/",
        "https://www.google.com/",
        "https://www.apple.com/",
        "https://www.microsoft.com/",
        "https://www.amazon.com/",
        "https://www.facebook.com/",
        "https://www.twitter.com/",
        "https://www.linkedin.com/",
        "https://www.netflix.com/",
        "https://www.spotify.com/",
        "https://www.tesla.com/",
        "https://www.airbnb.com/",
        "https://www.uber.com/",
        "https://www.dropbox.com/",
        "https://www.instagram.com/",
        "https://www.pinterest.com/",
        "https://www.reddit.com/",
        "https://www.tiktok.com/",
        "https://www.youtube.com/",
        "https://www.twitch.tv/",
        "https://www.discord.com/",
        "https://www.snapchat.com/",
        "https://www.linkedin.com/",
        "https://www.netflix.com/",
        "https://www.spotify.com/",
        "https://www.tesla.com/",
        "https://www.airbnb.com/",
        "https://www.uber.com/",
        "https://www.dropbox.com/",
    ]
    
    results = []
    start_times = {url: time.time() for url in urls}  # Track start times
    
    async for result in crawler.background_crawl(urls):
        elapsed = time.time() - start_times[result.url]
        print(f"[DONE] {result.url} → {elapsed:.2f} seconds")
        results.append((result.url, elapsed))
    
    print("\n=== Crawl Summary ===")
    for url, elapsed in results:
        print(f"{url:<35} | {elapsed:.2f} seconds")
    
    return results

if __name__ == "__main__":
    results = asyncio.run(main())




    