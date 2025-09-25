"""
Firecrawl wrapper: single exit with bucketed concurrency.

User path (share 3 concurrency via bucket "firecrawl"):
- scrape
- batch_scrape_rate_limited (local fan-out cap to avoid task explosion)
- batch_scrape_stream (AsyncGenerator, yields as results complete)

Background path (share 2 concurrency via bucket "firecrawl_tracking"):
- scrape_with_change_tracking (AsyncGenerator)

Note: Concurrency limits are enforced by src/core/rate_limiter.py API_LIMITS
  - firecrawl.max_concurrent = 3
  - firecrawl_tracking.max_concurrent = 2
This file does NOT modify global limiter configs; it only routes calls
to the proper bucket and provides a local fan-out bound in batch.
"""

from firecrawl import AsyncFirecrawl
from .rate_limiter import rate_limiter
from .request_ctx import get_user_id
from typing import Optional, Sequence, Union, AsyncGenerator
from dotenv import load_dotenv
load_dotenv()
import os
import asyncio
from typing import List
from collections import defaultdict


class RateLimitedFirecrawl:
    def __init__(self):
        self.firecrawl = AsyncFirecrawl(api_key=os.getenv("FIRECRAWL_API_KEY"))
        self.firecrawl_tracking = AsyncFirecrawl(api_key=os.getenv("FIRECRAWL_API_KEY_TRACKING"))
        # Optional per-user concurrency cap (low coupling via ContextVar)
        # Set FIRECRAWL_USER_MAX (e.g., 2) to enforce fairness when user_id is present.
        self._user_max = int(os.getenv("FIRECRAWL_USER_MAX", "0"))
        self._user_sems = defaultdict(lambda: asyncio.Semaphore(self._user_max if self._user_max > 0 else 1))

    def _maybe_get_user_sem(self):
        """Return (sem, has_sem) for current user if per-user cap is enabled and user_id is set.

        If FIRECRAWL_USER_MAX <= 0 or user_id is not set, return (None, False) to skip gating.
        """
        if self._user_max <= 0:
            return None, False
        uid = get_user_id()
        if uid is None:
            return None, False
        return self._user_sems[uid], True

    async def scrape(self, *args, **kwargs):
        """User-facing realtime scrape (bucket: firecrawl, 3 concurrency)."""
        sem, has = self._maybe_get_user_sem()
        if has:
            async with sem:
                return await rate_limiter.execute_with_limit(
                    "firecrawl",
                    self.firecrawl.scrape,
                    *args,
                    **kwargs,
                )
        return await rate_limiter.execute_with_limit(
            "firecrawl",
            self.firecrawl.scrape,
            *args,
            **kwargs,
        )
    
    async def batch_scrape_rate_limited(
        self,
        urls: Sequence[str],
        *,
        local_concurrency: int = 50,
        **kwargs,
    ) -> List[object]:
        """User-facing batch scrape (bucket: firecrawl, 3 concurrency).

        Adds a local fan-out cap to avoid creating too many concurrent
        tasks at once. The true provider-facing concurrency is still
        enforced by the global rate limiter bucket.
        """
        sem = asyncio.Semaphore(local_concurrency)

        async def _one(u: str):
            async with sem:
                # Apply optional per-user gate if enabled and user_id is set
                user_sem, has = self._maybe_get_user_sem()
                if has:
                    async with user_sem:
                        return await rate_limiter.execute_with_limit(
                            "firecrawl",
                            self.firecrawl.scrape,
                            u,
                            **kwargs,
                        )
                return await rate_limiter.execute_with_limit(
                    "firecrawl",
                    self.firecrawl.scrape,
                    u,
                    **kwargs,
                )

        tasks = [asyncio.create_task(_one(url)) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def batch_scrape_stream(
        self,
        urls: Union[str, Sequence[str]],
        *,
        local_concurrency: int = 50,
        **kwargs,
    ) -> AsyncGenerator[object, None]:
        """User-facing realtime batch scrape as a stream (bucket: firecrawl).

        - Accepts a single URL (yields one result) or a sequence of URLs
          (yields results as they complete).
        - Respects realtime bucket limits (shared 3 concurrency) and applies
          optional per-user gating if enabled. A local fan-out semaphore
          prevents spawning too many tasks at once.
        """
        if isinstance(urls, str):
            urls = [urls]

        sem = asyncio.Semaphore(local_concurrency)

        async def _one(u: str):
            async with sem:
                user_sem, has = self._maybe_get_user_sem()
                try:
                    if has:
                        async with user_sem:
                            return await rate_limiter.execute_with_limit(
                                "firecrawl",
                                self.firecrawl.scrape,
                                u,
                                **kwargs,
                            )
                    return await rate_limiter.execute_with_limit(
                        "firecrawl",
                        self.firecrawl.scrape,
                        u,
                        **kwargs,
                    )
                except Exception as e:
                    return {"url": u, "error": str(e)}

        tasks = [asyncio.create_task(_one(u)) for u in urls]
        for fut in asyncio.as_completed(tasks):
            result = await fut
            yield result
    
    async def scrape_with_change_tracking(
        self,
        urls: Union[str, Sequence[str]],
        *,
        tag: str,
        modes: Optional[Sequence[str]] = None,
        **kwargs,
    ) -> AsyncGenerator[object, None]:
        """Background tracking scrape (bucket: firecrawl_tracking, 2 concurrency).

        - Accepts a single URL (yields one result) or a sequence of URLs
          (yields results as they complete).
        - Uses the `firecrawl_tracking` rate-limit bucket so concurrency stays
          compliant with configured background limits.
        - Intentionally does NOT apply per-user gating; this path uses a
          dedicated background channel and relies solely on the global bucket.
        """
        if modes is None:
            modes = ["git-diff"]

        async def _scrape_one(u: str):
            local_formats = [
                'markdown',
                {
                    'type': 'change_tracking',
                    'modes': list(modes),
                    'tag': tag,
                }
            ]
            # No per-user gating here; rely solely on global tracking bucket
            try:
                return await rate_limiter.execute_with_limit(
                    "firecrawl_tracking",
                    self.firecrawl_tracking.scrape,
                    u,
                    formats=local_formats,
                    tag=tag,
                    **kwargs,
                )
            except Exception as e:
                # Swallow errors to keep the stream alive; surface per-URL error info
                return {"url": u, "error": str(e)}

        if isinstance(urls, str):
            result = await _scrape_one(urls)
            yield result
            return

        tasks = [asyncio.create_task(_scrape_one(u)) for u in urls]
        for done in asyncio.as_completed(tasks):
            res = await done
            yield res

    def __getattr__(self, name):
        return getattr(self.firecrawl, name)
