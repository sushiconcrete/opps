# src/core/global_crawler_manager.py
import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Iterable, List, Optional, Tuple, Dict
from collections import deque
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher, RateLimiter as C4RateLimiter

# External limiter: your improved version
# from src.core.rate_limiter import RateLimiter, RateLimitConfig
# If you prefer not to import, define minimal compatible stubs here:
@dataclass
class RateLimitConfig:
    max_requests: int
    time_window: float
    max_concurrent: int
    name: str

class RateLimiter:
    """Sliding-window + per-API concurrency limiter (no sleeping under locks)."""
    def __init__(self, configs: Dict[str, RateLimitConfig]):
        self.configs = configs
        self.request_times: Dict[str, deque] = {k: deque() for k in configs}
        self.locks: Dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in configs}
        self.semaphores: Dict[str, asyncio.Semaphore] = {
            k: asyncio.Semaphore(cfg.max_concurrent) for k, cfg in configs.items()
        }

    async def _await_window(self, key: str) -> None:
        cfg = self.configs[key]
        dq = self.request_times[key]
        while True:
            now = time.monotonic()
            async with self.locks[key]:
                cutoff = now - cfg.time_window
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if len(dq) < cfg.max_requests:
                    dq.append(now)
                    return
                wait_time = max(0.0, cfg.time_window - (now - dq[0]))
            if wait_time > 0:
                await asyncio.sleep(wait_time)

    async def acquire(self, key: str) -> None:
        if key not in self.configs:
            return
        # throughput window
        await self._await_window(key)
        # per-key concurrency
        sem = self.semaphores[key]
        await sem.acquire()

    def release(self, key: str) -> None:
        if key in self.semaphores:
            self.semaphores[key].release()

# ---------------- types ----------------

@dataclass
class CrawlResultEvt:
    url: str
    result: Optional[Any]
    error: Optional[BaseException]
    elapsed: float

@dataclass(order=True)
class _QueuedJob:
    # Lower priority wins. Use 0 for realtime, 1 for background.
    priority: int
    enq_time: float
    job_id: int = field(compare=False)
    urls: List[str] = field(compare=False)
    config: CrawlerRunConfig = field(compare=False)
    dispatcher: Optional[MemoryAdaptiveDispatcher] = field(compare=False)
    result_q: "asyncio.Queue[CrawlResultEvt]" = field(compare=False)
    done_evt: asyncio.Event = field(compare=False)
    inflight: int = field(default=0, compare=False)

# --------------- helpers ----------------

def _host_label(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc

def _dedup_preserve_order(urls: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

# ------------- manager ------------------

class GlobalCrawlerManager:
    """
    Process-wide crawler scheduler with:
    - global concurrency budget (hard ceiling),
    - priority queue (realtime > background),
    - round-robin draining across jobs,
    - crawler pool (stops Playwright context races),
    - per-host rate window + per-host concurrency
    """

    def __init__(
        self,
        total_concurrent: int = 30,        # global hard cap
        pool_size: int = 6,                # browser sessions in pool
        per_host_concurrent: int = 2,      # tabs per host
        default_host_rps: Tuple[int, float] = (60, 60.0),  # 60 req / 60s per host
    ):
        self._permits = asyncio.Semaphore(total_concurrent)
        self._queue: "asyncio.PriorityQueue[_QueuedJob]" = asyncio.PriorityQueue()
        self._job_id_seq = 0
        self._stop_evt = asyncio.Event()

        # crawler pool
        self._pool_size = max(1, min(pool_size, total_concurrent))
        self._crawler_pool: asyncio.Queue[AsyncWebCrawler] = asyncio.Queue()
        self._pool_ready = asyncio.Event()

        # host controls
        self._per_host_max = max(1, per_host_concurrent)
        self._per_host_sems: Dict[str, asyncio.Semaphore] = {}

        # external limiter (host-level); starts empty; added lazily per host
        self._rate = RateLimiter(configs={})
        self._default_host_rps = default_host_rps

        # worker
        self._worker_task: Optional[asyncio.Task] = None

    # -------- lifecycle --------

    async def start(self):
        if self._worker_task and not self._worker_task.done():
            return
        # spin up crawler sessions
        for _ in range(self._pool_size):
            crawler = AsyncWebCrawler()
            await crawler.__aenter__()
            await self._crawler_pool.put(crawler)
        self._pool_ready.set()
        self._worker_task = asyncio.create_task(self._worker(), name="crawler-worker")

    async def shutdown(self):
        self._stop_evt.set()
        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        # close crawlers
        while not self._crawler_pool.empty():
            crawler = await self._crawler_pool.get()
            await crawler.__aexit__(None, None, None)

    # ------- public API --------

    async def submit(
        self,
        urls: Iterable[str],
        *,
        priority: int,                     # 0=realtime, 1=background
        config: CrawlerRunConfig,
        job_concurrency_cap: int = 9,      # per-job cap
        dispatcher: Optional[MemoryAdaptiveDispatcher] = None,
    ) -> AsyncGenerator[CrawlResultEvt, None]:
        """Enqueue a job and stream results back."""
        await self.start()  # lazy-start

        urls = _dedup_preserve_order(urls)
        result_q: "asyncio.Queue[CrawlResultEvt]" = asyncio.Queue()
        done_evt = asyncio.Event()
        job_id = self._job_id_seq
        self._job_id_seq += 1

        # per-job internal dispatcher (keep retries tiny; external limiter does pacing)
        if dispatcher is None:
            dispatcher = MemoryAdaptiveDispatcher(
                memory_threshold_percent=80.0,
                check_interval=1.0,
                max_session_permit=max(1, job_concurrency_cap),
                rate_limiter=C4RateLimiter(base_delay=(0.1, 0.2), max_delay=0.5, max_retries=0),
                monitor=None,
            )

        job = _QueuedJob(
            priority=priority,
            enq_time=time.perf_counter(),
            job_id=job_id,
            urls=list(urls),
            config=config,
            dispatcher=dispatcher,
            result_q=result_q,
            done_evt=done_evt,
            inflight=0,
        )
        await self._queue.put(job)

        # Consumer: stream results until done
        while True:
            if done_evt.is_set() and result_q.empty():
                break
            try:
                ev = await asyncio.wait_for(result_q.get(), timeout=60)
                yield ev
                result_q.task_done()
            except asyncio.TimeoutError:
                # If you want a "no-progress" early stop, break here instead
                continue

    # --------- internals ----------

    def _ensure_host_limits(self, host: str):
        # per-host concurrency
        if host not in self._per_host_sems:
            self._per_host_sems[host] = asyncio.Semaphore(self._per_host_max)
        # per-host rate window (external limiter), lazy add
        if host not in self._rate.configs:
            max_req, win = self._default_host_rps
            self._rate.configs[host] = RateLimitConfig(
                max_requests=max_req, time_window=win, max_concurrent=self._per_host_max, name=host
            )
            self._rate.request_times[host] = self._rate.request_times.get(host, deque())
            self._rate.locks[host] = asyncio.Lock()
            self._rate.semaphores[host] = asyncio.Semaphore(self._per_host_max)

    async def _worker(self):
        active: List[_QueuedJob] = []

        while not self._stop_evt.is_set():
            # refill active list
            if not active:
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                    active.append(job)
                except asyncio.TimeoutError:
                    continue
            else:
                try:
                    while True:
                        job = self._queue.get_nowait()
                        active.append(job)
                except asyncio.QueueEmpty:
                    pass

            # round-robin one URL per job per cycle (priority preserved via sort)
            still_active: List[_QueuedJob] = []
            for job in sorted(active):  # priority first, then FIFO via enq_time
                if not job.urls:
                    # mark done when both url list empty AND inflight == 0
                    if job.inflight == 0:
                        job.done_evt.set()
                    continue

                # dequeue one URL
                url = job.urls.pop(0)
                job.inflight += 1
                asyncio.create_task(self._run_one(url, job), name=f"crawl:{url}")

                # keep job if more to do
                if job.urls or job.inflight > 0:
                    still_active.append(job)

            active = still_active
            await asyncio.sleep(0.01)

    async def _run_one(self, url: str, job: _QueuedJob):
        host = _host_label(url)
        self._ensure_host_limits(host)

        start = time.perf_counter()
        try:
            # ---- Gate 1: per-host rate window (external; may sleep; holds nothing else)
            await self._rate.acquire(host)
            try:
                # ---- Gate 2: per-host concurrency
                async with self._per_host_sems[host]:
                    # ---- Gate 3: global concurrency
                    async with self._permits:
                        # ---- Gate 4: borrow crawler; run; return crawler
                        await self._pool_ready.wait()
                        crawler = await self._crawler_pool.get()
                        try:
                            res = await crawler.arun(
                                url=url,
                                config=job.config,
                                dispatcher=job.dispatcher
                            )
                            ev = CrawlResultEvt(url=url, result=res, error=None,
                                                elapsed=time.perf_counter() - start)
                        finally:
                            await self._crawler_pool.put(crawler)
            finally:
                # release external limiter's per-host concurrency slot
                self._rate.release(host)

        except BaseException as e:
            ev = CrawlResultEvt(url=url, result=None, error=e, elapsed=time.perf_counter() - start)

        # push result + finalize job accounting
        await job.result_q.put(ev)
        job.inflight -= 1
        if job.inflight == 0 and not job.urls:
            job.done_evt.set()




async def test_queue_crawler():
    urls = [
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
        "https://www.shopify.com/",
        "https://www.paypal.com/",
        "https://www.adobe.com/",
        "https://www.nvidia.com/",
        "https://www.intel.com/",
        "https://www.salesforce.com/",
        "https://www.oracle.com/",
        "https://www.ibm.com/",
        "https://www.samsung.com/",
        "https://www.hp.com/",
        "https://www.dell.com/",
        "https://www.cisco.com/",
        "https://www.sony.com/",
        "https://www.asus.com/",
        "https://www.lenovo.com/",
        "https://www.xiaomi.com/",
        "https://www.huawei.com/",
        "https://www.baidu.com/",
        "https://www.alibaba.com/",
        "https://www.jd.com/",
        "https://www.tiktok.com/",
        "https://www.pinterest.com/",
        "https://www.reddit.com/",
        "https://www.quora.com/",
        "https://www.medium.com/",
        "https://www.wordpress.com/",
        "https://www.wix.com/",
        "https://www.squarespace.com/",
        "https://www.zendesk.com/",
        "https://www.slack.com/",
        "https://www.atlassian.com/",
        "https://www.trello.com/",
        "https://www.zoom.us/",
        "https://www.skype.com/",
        "https://www.discord.com/",
        "https://www.github.com/",
        "https://www.gitlab.com/",
        "https://www.bitbucket.org/",
        "https://www.digitalocean.com/",
        "https://www.heroku.com/",
        "https://www.cloudflare.com/",
        "https://www.vercel.com/",
        "https://www.netlify.com/",
        "https://www.mailchimp.com/",
        "https://www.sendgrid.com/",
        "https://www.twilio.com/",
        "https://www.stripe.com/",
        "https://www.squareup.com/",
        "https://www.zoho.com/",
        "https://www.freshdesk.com/",
        "https://www.hubspot.com/",
        "https://www.buffer.com/",
        "https://www.hootsuite.com/",
        "https://www.canva.com/",
        "https://www.figma.com/",
        "https://www.adobe.com/creativecloud.html",
        "https://www.behance.net/",
        "https://www.dribbble.com/",
        "https://www.envato.com/",
        "https://www.shutterstock.com/",
        "https://www.gettyimages.com/",
        "https://www.istockphoto.com/",
        "https://www.booking.com/",
        "https://www.expedia.com/",
        "https://www.kayak.com/",
        "https://www.tripadvisor.com/",
        "https://www.skyscanner.net/",
        "https://www.agoda.com/",
        "https://www.trivago.com/",
        "https://www.hotels.com/",
        "https://www.marriott.com/",
        "https://www.hilton.com/",
        "https://www.ihg.com/",
        "https://www.accorhotels.com/",
        "https://www.delta.com/",
        "https://www.aa.com/",
        "https://www.united.com/",
        "https://www.southwest.com/",
        "https://www.ryanair.com/",
        "https://www.lufthansa.com/",
        "https://www.emirates.com/",
        "https://www.qatarairways.com/",
        "https://www.singaporeair.com/",
        "https://www.kayak.com/flights",
        "https://www.cheaptickets.com/",
        "https://www.priceline.com/",
        "https://www.orbitz.com/",
        "https://www.cnn.com/",
        "https://www.bbc.com/",
        "https://www.nytimes.com/",
        "https://www.wsj.com/",
        "https://www.bloomberg.com/",
    ]

    mgr = GlobalCrawlerManager(total_concurrent=30, pool_size=3, per_host_concurrent=2)

    bg_cfg = CrawlerRunConfig(
        stream=False, cache_mode=CacheMode.BYPASS, check_robots_txt=False,
        page_timeout=5_000, exclude_all_images=True
    )
    rt_cfg = CrawlerRunConfig(
        stream=False, cache_mode=CacheMode.BYPASS, check_robots_txt=False,
        page_timeout=12_000, exclude_all_images=True
    )

    async def run_rt(urls):
        async for ev in mgr.submit(urls, priority=0, config=rt_cfg, job_concurrency_cap=6):
            print(f"[RT {'OK' if not ev.error else 'ERR'}] {ev.url} {ev.elapsed:.2f}s")

    async def run_bg(urls):
        async for ev in mgr.submit(urls, priority=1, config=bg_cfg, job_concurrency_cap=3):
            print(f"[BG {'OK' if not ev.error else 'ERR'}] {ev.url} {ev.elapsed:.2f}s")

    t1 = asyncio.create_task(run_rt(["https://www.google.com/",
    "https://www.apple.com/",
    "https://www.microsoft.com/"]))
    # t2 = asyncio.create_task(run_rt(["https://www.mit.edu", "https://www.stanford.edu"]))
    # t3 = asyncio.create_task(run_bg(urls))
    await asyncio.gather(t1)
    await mgr.shutdown()


if __name__ == "__main__":
    asyncio.run(test_queue_crawler())

