# src/core/rate_limiter.py
import asyncio
import time
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """API rate limit configuration"""
    max_requests: int  # Maximum requests
    time_window: int  # Time window (seconds)
    max_concurrent: int  # Maximum concurrent requests
    name: str  # API name


class RateLimiter:
    """General API rate limiter with concurrency control"""

    def __init__(self, configs: Dict[str, RateLimitConfig]):
        """
        Initialize rate limiter with concurrency control

        Args:
            configs: API rate limit configuration dict, key is API identifier, value is rate limit config
        """
        self.configs = configs
        self.request_times: Dict[str, deque] = {
            api_name: deque() for api_name in configs
        }
        self.locks: Dict[str, asyncio.Lock] = {
            api_name: asyncio.Lock() for api_name in configs
        }
        self.semaphores: Dict[str, asyncio.Semaphore] = {
            api_name: asyncio.Semaphore(config.max_concurrent) 
            for api_name, config in configs.items()
        }

    async def acquire(self, api_name: str) -> None:
        """
        Sliding-window gate: reserve a slot if available; otherwise wait
        until the earliest timestamp leaves the window. Never sleep under
        the lock; use monotonic time to avoid clock jumps.
        """
        if api_name not in self.configs:
            return

        cfg = self.configs[api_name]
        dq = self.request_times[api_name]

        while True:
            async with self.locks[api_name]:
                now = time.monotonic()

                # drop expired entries
                while dq and dq[0] <= now - cfg.time_window:
                    dq.popleft()

                if len(dq) < cfg.max_requests:
                    dq.append(now)   # reserve a slot
                    return

                # how long until the oldest entry expires
                wait = cfg.time_window - (now - dq[0])

            # sleep OUTSIDE the lock
            if wait > 0:
                await asyncio.sleep(wait)

    async def execute_with_limit(self, api_name: str, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with rate limiting and concurrency control

        Args:
            api_name: API identifier
            func: Async function to execute
            *args, **kwargs: Function arguments

        Returns:
            Function execution result
        """
        if api_name not in self.configs:
            # No limits configured, execute directly
            return await func(*args, **kwargs)
        
        # Apply both concurrency control and rate limiting
        async with self.semaphores[api_name]:
            await self.acquire(api_name)
            return await func(*args, **kwargs)


# Predefined API rate limit configs
API_LIMITS = {
    "openai": RateLimitConfig(max_requests=4000, time_window=60, max_concurrent=32, name="OpenAI"),
    "tavily": RateLimitConfig(max_requests=100, time_window=60, max_concurrent=8, name="Tavily"),
    "wayback_redirect": RateLimitConfig(max_requests=1000, time_window=60, max_concurrent=12, name="Wayback Redirect Check"),
    "firecrawl": RateLimitConfig(max_requests=100, time_window=60, max_concurrent=3, name="Firecrawl"),
    "firecrawl_tracking": RateLimitConfig(max_requests=100, time_window=60, max_concurrent=2, name="Firecrawl Tracking"),
}

# Global rate limiter instance
rate_limiter = RateLimiter(API_LIMITS)