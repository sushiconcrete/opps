# src/core/tracking.py
"""
增强版本：Archive tracking utilities for website change detection
集成了数据库内容存储功能，支持持久化的增量比较
添加了代理支持以解决Archive.org访问问题
"""
import asyncio
import difflib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Union, AsyncGenerator, Sequence
from waybackpy import WaybackMachineCDXServerAPI
from .firecrawl_wrapper import RateLimitedFirecrawl
from .rate_limiter import rate_limiter
import requests
import os
from dotenv import load_dotenv
from firecrawl.v2.types import Document
import logging

# ===== 新增：导入数据库内容存储 =====
from backend.database import content_cache

load_dotenv()

logger = logging.getLogger(__name__)

# ===== 新增：代理配置函数 =====
def get_proxy_config() -> Optional[Dict[str, str]]:
    """获取代理配置"""
    http_proxy = os.getenv('HTTP_PROXY')
    https_proxy = os.getenv('HTTPS_PROXY')
    
    if http_proxy or https_proxy:
        return {
            'http': http_proxy,
            'https': https_proxy or http_proxy
        }
    return None

class ArchiveTracker:
    """Handles website archive comparison with optimized batching"""
    
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        # Firecrawl wrapper for all page scrapes (realtime bucket)
        self.fcw = RateLimitedFirecrawl()
        self.tag = "archive_tracking"  # 专用标签用于归档跟踪
        self.maxAge = 43200000
        
        # ===== 新增：代理配置和超时设置 =====
        self.proxies = get_proxy_config()
        self.timeout = 90  # 增加超时时间，给代理更多时间
        
        # 记录代理配置状态
        if self.proxies:
            logger.info(f"Archive跟踪器已配置代理: HTTP={self.proxies.get('http', 'None')}")
        else:
            logger.info("Archive跟踪器未配置代理，将使用直连")

    async def _get_archive_batch(self, urls: List[str], target_date: str) -> List[Optional[Dict]]:
        """Get archive info for a batch of URLs with proper rate limiting"""
        results = []
        for url in urls:
            archive_info = await self.get_nearest_archive(url, target_date)
            results.append(archive_info)
        return results
    
    async def get_nearest_archive(self, url: str, target_date: str) -> Optional[Dict]:
        """Get archive nearest to a specific date using direct Wayback URL construction with proxy support"""
        def _sync_get_nearest():
            # Convert target_date to Wayback timestamp format
            target_dt = datetime.strptime(target_date, '%Y%m%d')
            wayback_timestamp = target_dt.strftime('%Y%m%d%H%M%S')
            
            # Construct Wayback URL directly
            archive_url = f"https://web.archive.org/web/{wayback_timestamp}/{url}"
            
            # ===== 新增：记录请求信息 =====
            logger.debug(f"请求Archive URL: {archive_url}")
            if self.proxies:
                logger.debug(f"使用代理: {self.proxies}")
            
            try:
                # ===== 修改：添加代理支持和更好的错误处理 =====
                response = requests.get(
                    archive_url, 
                    allow_redirects=True, 
                    timeout=self.timeout,
                    proxies=self.proxies,  # 添加代理配置
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                )
                
                if response.status_code == 200:
                    # Extract actual timestamp from final URL
                    final_url = response.url
                    if '/web/' in final_url:
                        # Extract timestamp from final URL
                        parts = final_url.split('/web/')[1].split('/')[0]
                        actual_timestamp = parts
                        actual_dt = datetime.strptime(actual_timestamp, '%Y%m%d%H%M%S')
                        days_diff = abs((actual_dt.date() - target_dt.date()).days)
                        
                        logger.debug(f"Archive访问成功: {url} -> {final_url}")
                        
                        return {
                            'archive_url': final_url,
                            'timestamp': actual_timestamp,
                            'actual_date': actual_dt.strftime('%Y-%m-%d %H:%M:%S'),
                            'requested_date': target_dt.strftime('%Y-%m-%d'),
                            'days_difference': days_diff,
                            'original_url': url,
                            'status_code': '200',
                            'mimetype': 'text/html'
                        }
                elif response.status_code == 404:
                    logger.warning(f"Archive中未找到 {url} 在 {target_date} 的记录")
                else:
                    logger.warning(f"Archive访问返回状态码 {response.status_code} for {url}")
                
                return None
                
            except requests.exceptions.ProxyError as e:
                logger.error(f"代理连接错误 {url}: {e}")
                return None
            except requests.exceptions.ConnectTimeout as e:
                logger.error(f"连接超时 {url}: {e}")
                return None
            except requests.exceptions.ReadTimeout as e:
                logger.error(f"读取超时 {url}: {e}")
                return None
            except requests.exceptions.SSLError as e:
                logger.error(f"SSL错误 {url}: {e}")
                return None
            except Exception as e:
                logger.warning(f"Archive访问出错 {url}: {e}")
                return None
        
        try:
            return await rate_limiter.execute_with_limit("wayback_redirect", asyncio.to_thread, _sync_get_nearest)
        except Exception as e:
            logger.warning(f"Rate limiter执行失败 {url}: {e}")
            return None
    
    async def _create_diff_result(self, url: str, current_md: Optional[str], previous_md: Optional[str]) -> Dict:
        """Create result dictionary with diff or error message - shared by both classes"""
        if not current_md and not previous_md:
            return {"url": url, "gitdiff": "No changes found.", "error": "Both current and previous content unavailable"}
        elif not current_md:
            return {"url": url, "gitdiff": "No changes found.", "error": "Current content unavailable"}
        elif not previous_md:
            return {"url": url, "gitdiff": "No changes found.", "error": "Previous content unavailable"}
        
        # Generate diff
        file1 = previous_md.splitlines(keepends=True)
        file2 = current_md.splitlines(keepends=True)
        delta = difflib.unified_diff(file1, file2, fromfile='old.md', tofile='new.md', lineterm='')
        gitdiff = ''.join(delta)
        
        if not gitdiff.strip():
            return {"url": url, "gitdiff": "No changes found.", "error": "Content identical"}
        else:
            return {"url": url, "gitdiff": gitdiff}
    
    async def compare(self, urls: List[str], day_delta: int) -> Dict[str, Dict]:
        """Collect-and-return version built on top of compare_stream.

        For backward compatibility, aggregates streaming results into a dict.
        """
        results: Dict[str, Dict] = {}
        async for item in self.compare_stream(urls, day_delta):
            results[item.get("url")] = item
        return results

    async def compare_stream(self, urls: List[str], day_delta: int) -> AsyncGenerator[Dict, None]:
        """Asynchronously stream per-URL diffs as soon as each pair completes.

        Behavior:
        - Yields one result dict per URL (unordered within batch; earliest-first via as_completed).
        - Each result contains at least: {"url", "gitdiff", maybe "error"}.
        - Respects global rate limits via the Firecrawl wrapper; uses a local semaphore to bound
          the number of in-flight URL pairs in this pipeline.
        """
        target_date = (datetime.now() - timedelta(days=day_delta)).strftime("%Y%m%d")
        import time

        def _extract_markdown(res) -> Optional[str]:
            return getattr(res, 'markdown', None) if res is not None else None

        for i in range(0, len(urls), self.batch_size):
            batch_urls = urls[i:i + self.batch_size]
            batch_start_time = time.perf_counter()

            # Local fan-out to avoid creating too many tasks at once
            local_sem = asyncio.Semaphore(self.batch_size)

            async def _process_one(url: str) -> Dict:
                async with local_sem:
                    # Kick off current scrape immediately
                    current_task = asyncio.create_task(self.fcw.scrape(url, formats=['markdown'], maxAge = self.maxAge))

                    # Resolve archive URL (rate limited by wayback_redirect bucket inside get_nearest_archive)
                    archive_info = await self.get_nearest_archive(url, target_date)
                    archived_md: Optional[str] = None

                    if archive_info and 'archive_url' in archive_info:
                        archive_url = archive_info['archive_url']
                        try:
                            archived_res = await self.fcw.scrape(archive_url, formats=['markdown'], maxAge = self.maxAge)
                        except Exception as e:
                            logger.warning(f"抓取Archive内容失败 {archive_url}: {e}")
                            archived_res = None
                        archived_md = _extract_markdown(archived_res)

                    # Await current result (it may already be done)
                    try:
                        current_res = await current_task
                    except Exception as e:
                        logger.warning(f"抓取当前内容失败 {url}: {e}")
                        current_res = None
                    current_md = _extract_markdown(current_res)

                    # Compute diff and return
                    diff = await self._create_diff_result(url, current_md, archived_md)
                    return {**diff}

            tasks = [asyncio.create_task(_process_one(u)) for u in batch_urls]

            # Stream completion within the batch: as soon as a URL pair is ready, we proceed
            for fut in asyncio.as_completed(tasks):
                item = await fut
                # Stream to caller immediately
                yield item
            batch_end_time = time.perf_counter()
            logger.info(f"Archive batch {i // self.batch_size + 1}: processed {len(batch_urls)} URLs in {batch_end_time - batch_start_time:.2f} seconds")


class OngoingTracker:
    """增强版本：支持持久化内容存储的持续网站变化检测"""
    
    def __init__(self, batch_size: int = 10, tag: Optional[str] = "default"):
        self.batch_size = batch_size
        self._tag = tag
        self.fcw = RateLimitedFirecrawl()
        self.maxAge = 300000
        # ===== 新增：内容存储管理器 =====
        self.content_manager = content_cache

    # ===== 新增：数据库内容存储方法 =====
    async def get_previous_scrapes(self, urls: List[str], tag: Optional[str] = None) -> Dict[str, str]:
        """从数据库获取之前的内容
        
        Args:
            urls: URL列表
            tag: 内容标签，用于区分不同的跟踪任务
            
        Returns:
            URL到内容的映射字典
        """
        tag_to_use = tag if tag is not None else self._tag
        
        try:
            previous_content = await self.content_manager.get_previous_content(urls, tag_to_use)
            logger.info(f"从数据库获取历史内容: {len(previous_content)} 个URL有历史记录 (标签: {tag_to_use})")
            return previous_content
        except Exception as e:
            logger.error(f"获取历史内容失败: {e}")
            return {}
    
    async def save_current_scrapes(self, results: Dict[str, str], tag: Optional[str] = None) -> None:
        """保存当前内容到数据库
        
        Args:
            results: URL到内容的映射字典
            tag: 内容标签
        """
        tag_to_use = tag if tag is not None else self._tag
        
        try:
            await self.content_manager.save_current_content(results, tag_to_use)
            logger.info(f"保存当前内容到数据库: {len(results)} 个URL (标签: {tag_to_use})")
        except Exception as e:
            logger.error(f"保存当前内容失败: {e}")

    async def _create_diff_result(self, url: str, current_md: Optional[str], previous_md: Optional[str]) -> Dict:
        """Create result dictionary with diff or error message - shared by both classes"""
        if not current_md and not previous_md:
            return {"url": url, "gitdiff": "No changes found.", "error": "Both current and previous content unavailable"}
        elif not current_md:
            return {"url": url, "gitdiff": "No changes found.", "error": "Current content unavailable"}
        elif not previous_md:
            return {"url": url, "gitdiff": "First-time tracking - no previous content", "error": "Archive content unavailable"}
        
        # Generate diff
        file1 = previous_md.splitlines(keepends=True)
        file2 = current_md.splitlines(keepends=True)
        delta = difflib.unified_diff(file1, file2, fromfile='old.md', tofile='new.md', lineterm='')
        gitdiff = ''.join(delta)
        
        if not gitdiff.strip():
            return {"url": url, "gitdiff": "No changes found.", "error": "Content identical"}
        else:
            return {"url": url, "gitdiff": gitdiff}

    # ===== 增强版本：支持数据库存储的流式跟踪 =====
    async def ongoing_tracking_stream_with_persistence(
        self, 
        urls: Union[str, List[str]], 
        tag: Optional[str] = None,
        save_content: bool = True
    ) -> AsyncGenerator[Dict, None]:
        """流式比较结果并支持持久化存储
        
        Args:
            urls: 要跟踪的URL(s)
            tag: 内容标签
            save_content: 是否保存内容到数据库
            
        Yields:
            包含变化信息的字典
        """
        if isinstance(urls, str):
            urls = [urls]
        
        tag_to_use = tag if tag is not None else self._tag
        
        # 分批处理
        for i in range(0, len(urls), self.batch_size):
            batch_urls = urls[i:i + self.batch_size]
            
            # ===== 步骤1：获取历史内容 =====
            previous_batch = await self.get_previous_scrapes(batch_urls, tag_to_use)
            
            # ===== 步骤2：抓取当前内容并进行比较 =====
            current_content = {}
            
            # 使用Firecrawl批量抓取当前内容
            async for result in self.fcw.batch_scrape_stream(
                batch_urls, 
                formats=['markdown'], 
                maxAge=self.maxAge
            ):
                url = None
                markdown_content = None
                
                # 处理不同的结果格式
                if isinstance(result, Document):
                    url = getattr(result, 'url', None) or getattr(result.metadata, 'url', None)
                    markdown_content = getattr(result, 'markdown', None)
                elif isinstance(result, dict):
                    url = result.get('url')
                    markdown_content = result.get('markdown')
                elif hasattr(result, 'url'):
                    url = result.url
                    markdown_content = getattr(result, 'markdown', None)
                
                if url and markdown_content:
                    current_content[url] = markdown_content
                    
                    # 获取历史内容进行比较
                    previous_content = previous_batch.get(url)
                    
                    # 生成差异结果
                    diff_result = await self._create_diff_result(url, markdown_content, previous_content)
                    
                    # 立即流式输出结果
                    yield diff_result
                
                elif url:
                    # 处理失败的抓取
                    error_result = await self._create_diff_result(url, None, previous_batch.get(url))
                    yield error_result
            
            # ===== 步骤3：保存当前内容到数据库 =====
            if save_content and current_content:
                await self.save_current_scrapes(current_content, tag_to_use)

    # ===== 保持向后兼容的原始方法 =====
    async def ongoing_tracking_stream(self, urls: Union[str, List[str]], tag: Optional[str] = None) -> AsyncGenerator[Dict, None]:
        """向后兼容的流式跟踪方法"""
        async for result in self.ongoing_tracking_stream_with_persistence(urls, tag, save_content=True):
            yield result

    async def track_stream(
        self,
        urls: List[str],
        *,
        tag: Optional[str] = None,
        modes: Optional[Sequence[str]] = None,
    ) -> AsyncGenerator[Dict, None]:
        """Stream change-tracking results with local fan-out using Firecrawl wrapper.

        - Batches URLs using `batch_size` to bound local fan-out.
        - Uses `scrape_with_change_tracking` (global `firecrawl_tracking` bucket) to yield
          results as they complete within each batch.
        - Normalizes results to a dict with at least `url` and optional `diff`/`markdown`.
        """
        eff_tag = tag or self._tag or "default"
        eff_modes: Sequence[str] = list(modes) if modes is not None else ["git-diff"]

        for i in range(0, len(urls), self.batch_size):
            chunk = urls[i : i + self.batch_size]
            # Delegate streaming for this chunk to the wrapper; it yields as tasks complete
            async for res in self.fcw.scrape_with_change_tracking(
                chunk, tag=eff_tag, modes=eff_modes, maxAge=self.maxAge
            ):
                yield res

    # ===== 新增：内容管理功能 =====
    async def get_content_history(self, url: str, tag: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """获取URL的内容历史记录
        
        Args:
            url: 要查询的URL
            tag: 内容标签
            limit: 返回记录数量限制
            
        Returns:
            历史记录列表，按时间倒序
        """
        tag_to_use = tag if tag is not None else self._tag
        
        try:
            history = await self.content_manager.get_content_history(url, tag_to_use, limit)
            logger.info(f"获取内容历史: {url} 有 {len(history)} 条记录")
            return history
        except Exception as e:
            logger.error(f"获取内容历史失败: {e}")
            return []
    
    async def cleanup_old_content(self, days_to_keep: int = 30, tag: Optional[str] = None) -> int:
        """清理旧的内容记录
        
        Args:
            days_to_keep: 保留多少天的记录
            tag: 内容标签，为None时清理所有标签
            
        Returns:
            清理的记录数量
        """
        try:
            if tag is None:
                # 清理所有标签的旧记录
                cleaned_count = await self.content_manager.cleanup_old_content(days_to_keep)
            else:
                # 清理特定标签的旧记录
                cleaned_count = await self.content_manager.cleanup_old_content_by_tag(days_to_keep, tag)
            
            logger.info(f"清理旧内容记录完成: {cleaned_count} 条记录被清理")
            return cleaned_count
        except Exception as e:
            logger.error(f"清理旧内容记录失败: {e}")
            return 0
    
    async def get_tracking_statistics(self, tag: Optional[str] = None) -> Dict:
        """获取跟踪统计信息
        
        Args:
            tag: 内容标签，为None时获取全局统计
            
        Returns:
            统计信息字典
        """
        try:
            if tag is None:
                stats = await self.content_manager.get_global_statistics()
            else:
                stats = await self.content_manager.get_tag_statistics(tag)
            
            return stats
        except Exception as e:
            logger.error(f"获取跟踪统计失败: {e}")
            return {"error": str(e)}

# ===== 新增：批量跟踪管理器 =====
class BatchTrackingManager:
    """批量跟踪管理器，支持多个跟踪任务的协调"""
    
    def __init__(self):
        self.active_trackers: Dict[str, OngoingTracker] = {}
        self.content_manager = content_cache
    
    async def create_tracker(self, tracker_id: str, tag: str, batch_size: int = 10) -> OngoingTracker:
        """创建新的跟踪器
        
        Args:
            tracker_id: 跟踪器唯一标识
            tag: 内容标签
            batch_size: 批处理大小
            
        Returns:
            创建的跟踪器实例
        """
        if tracker_id in self.active_trackers:
            logger.warning(f"跟踪器 {tracker_id} 已存在，将被替换")
        
        tracker = OngoingTracker(batch_size=batch_size, tag=tag)
        self.active_trackers[tracker_id] = tracker
        
        logger.info(f"创建跟踪器: {tracker_id} (标签: {tag}, 批大小: {batch_size})")
        return tracker
    
    async def remove_tracker(self, tracker_id: str) -> bool:
        """移除跟踪器
        
        Args:
            tracker_id: 跟踪器标识
            
        Returns:
            是否成功移除
        """
        if tracker_id in self.active_trackers:
            del self.active_trackers[tracker_id]
            logger.info(f"移除跟踪器: {tracker_id}")
            return True
        return False
    
    async def get_all_statistics(self) -> Dict[str, Dict]:
        """获取所有跟踪器的统计信息
        
        Returns:
            跟踪器ID到统计信息的映射
        """
        stats = {}
        for tracker_id, tracker in self.active_trackers.items():
            try:
                stats[tracker_id] = await tracker.get_tracking_statistics(tracker._tag)
            except Exception as e:
                stats[tracker_id] = {"error": str(e)}
        
        return stats
    
    async def cleanup_all_old_content(self, days_to_keep: int = 30) -> Dict[str, int]:
        """清理所有跟踪器的旧内容
        
        Args:
            days_to_keep: 保留天数
            
        Returns:
            跟踪器ID到清理数量的映射
        """
        cleanup_results = {}
        for tracker_id, tracker in self.active_trackers.items():
            try:
                cleaned_count = await tracker.cleanup_old_content(days_to_keep, tracker._tag)
                cleanup_results[tracker_id] = cleaned_count
            except Exception as e:
                cleanup_results[tracker_id] = 0
                logger.error(f"清理跟踪器 {tracker_id} 的旧内容失败: {e}")
        
        return cleanup_results

# ===== 全局实例 =====
batch_tracking_manager = BatchTrackingManager()

# ===== 测试函数 =====
async def test_enhanced_tracking():
    """测试增强版跟踪功能"""
    urls = [
        "https://www.ycombinator.com/",
        "https://www.stripe.com/", 
        "https://www.google.com/",
        "https://www.apple.com/",
    ]
    
    # 创建跟踪器
    tracker = OngoingTracker(tag="test_enhanced")
    
    logger.info("开始增强版跟踪测试...")
    
    # 第一次跟踪（建立基线）
    logger.info("第一次跟踪（建立基线）:")
    first_results = []
    async for result in tracker.ongoing_tracking_stream_with_persistence(urls, save_content=True):
        logger.info(f"结果: {result.get('url')} - {result.get('error', '有变化')}")
        first_results.append(result)
    
    # 等待一小段时间
    await asyncio.sleep(2)
    
    # 第二次跟踪（应该能看到历史比较）
    logger.info("\n第二次跟踪（增量比较）:")
    second_results = []
    async for result in tracker.ongoing_tracking_stream_with_persistence(urls, save_content=True):
        logger.info(f"结果: {result.get('url')} - {result.get('error', '有变化')}")
        second_results.append(result)
    
    # 获取统计信息
    stats = await tracker.get_tracking_statistics()
    logger.info(f"\n跟踪统计: {stats}")
    
    return first_results, second_results

# ===== 新增：代理测试函数 =====
async def test_archive_with_proxy():
    """测试Archive访问（含代理支持）"""
    urls = ["https://www.example.com", "https://www.google.com"]
    
    tracker = ArchiveTracker(batch_size=2)
    
    logger.info("测试Archive访问（含代理支持）...")
    
    results = []
    async for result in tracker.compare_stream(urls, day_delta=20):
        logger.info(f"Archive结果: {result.get('url')} - {result.get('error', 'OK')}")
        results.append(result)
    
    return results

if __name__ == "__main__":  
    # 测试增强版跟踪功能
    asyncio.run(test_enhanced_tracking())
    
    # 测试Archive代理功能
    asyncio.run(test_archive_with_proxy())