# src/core/tracking.py
"""
Archive tracking utilities for website change detection
"""
import asyncio
import difflib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Union, AsyncGenerator
from waybackpy import WaybackMachineCDXServerAPI
from crawler import CrawlerManager
from repository import ContentStorage
from rate_limiter import rate_limiter
import requests





class ArchiveTracker:
    """Handles website archive comparison with optimized batching"""
    
    def __init__(self, batch_size: int = 10):
        self.batch_size = batch_size
        # Reuse a single crawler facade; underlying manager is global-pooled.
        self.crawler = CrawlerManager()

    async def _crawl_batch(self, urls: List[str]) -> Dict[str, str]:
        """Crawl a batch of URLs and return successful results"""
        results = {}
        async for result in self.crawler.realtime_crawl(urls):
            if result.success and result.markdown:
                results[result.url] = result
        return results
    
    async def _get_archive_batch(self, urls: List[str], target_date: str) -> List[Optional[Dict]]:
        """Get archive info for a batch of URLs with proper rate limiting"""
        results = []
        for url in urls:
            archive_info = await self.get_nearest_archive(url, target_date)
            results.append(archive_info)
        return results
    
    async def get_nearest_archive(self, url: str, target_date: str) -> Optional[Dict]:
        """Get archive nearest to a specific date using direct Wayback URL construction"""
        def _sync_get_nearest():

            
            # Convert target_date to Wayback timestamp format
            target_dt = datetime.strptime(target_date, '%Y%m%d')
            wayback_timestamp = target_dt.strftime('%Y%m%d%H%M%S')
            
            # Construct Wayback URL directly
            archive_url = f"https://web.archive.org/web/{wayback_timestamp}/{url}"
            
            try:
                # Make request with redirect following to get final URL
                response = requests.get(archive_url, allow_redirects=True, timeout=10)
                
                if response.status_code == 200:
                    # Extract actual timestamp from final URL
                    final_url = response.url
                    if '/web/' in final_url:
                        # Extract timestamp from final URL
                        parts = final_url.split('/web/')[1].split('/')[0]
                        actual_timestamp = parts
                        actual_dt = datetime.strptime(actual_timestamp, '%Y%m%d%H%M%S')
                        days_diff = abs((actual_dt.date() - target_dt.date()).days)
                        
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
                return None
            except Exception as e:
                print(f"Error getting nearest archive for {url}: {e}")
                return None
        
        try:
            return await rate_limiter.execute_with_limit("wayback_redirect", asyncio.to_thread, _sync_get_nearest)
        except Exception as e:
            print(f"Error getting nearest archive for {url}: {e}")
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
            return {"url": url, "gitdiff": "No changes found", "error": "Content identical"}
        else:
            return {"url": url, "gitdiff": gitdiff}
    
    async def compare(self, urls: List[str], day_delta: int) -> Dict[str, Dict]:
        """Compare current URLs with their nearest archived versions"""
        current_results = {}
        archived_results = {}
        target_date = (datetime.now() - timedelta(days=day_delta)).strftime("%Y%m%d")
        
        # Process URLs in batches
        import time

        for i in range(0, len(urls), self.batch_size):
            batch_urls = urls[i:i + self.batch_size]

            batch_start_time = time.perf_counter()

            # Get current versions
            current_batch = await self._crawl_batch(batch_urls)
            current_results.update(current_batch)
            
            # Get archive URLs with rate limiting
            archive_infos = await self._get_archive_batch(batch_urls, target_date)
            
            # Build clean mapping: archive_url -> original_url
            archive_to_original = {}
            archive_urls = []
            
            for j, info in enumerate(archive_infos):
                if not isinstance(info, Exception) and info:
                    archive_url = info['archive_url']
                    original_url = batch_urls[j]
                    archive_to_original[archive_url] = original_url
                    archive_urls.append(archive_url)
            
            # Crawl archive versions and map using clean mapping
            if archive_urls:
                archive_batch = await self._crawl_batch(archive_urls)
                for archive_url, content in archive_batch.items():
                    original_url = archive_to_original.get(archive_url)
                    if original_url:
                        archived_results[original_url] = content

            batch_end_time = time.perf_counter()
            print(f"Batch {i // self.batch_size + 1}: processed {len(batch_urls)} URLs in {batch_end_time - batch_start_time:.2f} seconds. Downstream agent start.")
            
        
        # Generate comparison results
        results = {}
        for url in urls:
            current_result = current_results.get(url)
            archived_result = archived_results.get(url)
            
            current_md = current_result.markdown.raw_markdown if current_result and current_result.markdown else None
            archived_md = archived_result.markdown.raw_markdown if archived_result and archived_result.markdown else None
            
            result = await self._create_diff_result(url, current_md, archived_md)
            results[url] = {**result}
        return results

class OngoingTracker:
    """Handles ongoing website change detection: Use firecrawl change_tracking for now. Later piviot to crawl4ai may apply."""
    def __init__(self, batch_size: int = 10, tag: Optional[str] = "default"):
        self.batch_size = batch_size
        self._tag = tag
        self.crawler = CrawlerManager()
        self.storage = ContentStorage()

    async def get_previous_scrapes(self, urls: List[str], tag: Optional[str] = None) -> Dict[str, str]:
        """Get previous results from storage"""
        tag_to_use = tag if tag is not None else self._tag
        return await self.storage.get_previous_content(urls, tag_to_use)
    
    async def save_current_scrapes(self, results: Dict[str, str], tag: Optional[str] = None) -> None:
        """Save current results to storage"""
        tag_to_use = tag if tag is not None else self._tag
        await self.storage.save_current_content(results, tag_to_use)

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
            return {"url": url, "gitdiff": "No changes found", "error": "Content identical"}
        else:
            return {"url": url, "gitdiff": gitdiff}

    async def ongoing_tracking_stream(self, urls: Union[str, List[str]], tag: Optional[str] = None) -> AsyncGenerator[Dict, None]:
        """Stream comparison results with batched processing"""
        if isinstance(urls, str):
            urls = [urls]
        # Process in batches
        for i in range(0, len(urls), self.batch_size):
            batch_urls = urls[i:i + self.batch_size]
            # Get previous content for this batch
            previous_batch = await self.get_previous_scrapes(batch_urls, tag)
            
            # Stream current results for this batch
            ready_to_save = {}
            async for result in self.crawler.background_crawl(batch_urls):
                if result.success:
                    previous_content = previous_batch.get(result.url)
                    if not previous_content:
                        diff_result = await self._create_diff_result(
                            result.url, 
                            result.markdown, 
                            None # Previous content is None, so we can't compare
                        )
                    else:
                        diff_result = await self._create_diff_result(
                            result.url, 
                            result.markdown, 
                            previous_content # Previous content is not None, so we can compare
                        )
                    ready_to_save[result.url] = result
                    yield diff_result
            await self.save_current_scrapes(ready_to_save, tag)

    

async def test_ArchiveTracker():
    tracker = ArchiveTracker()
    urls = [
        "https://www.ycombinator.com/",
        "https://www.stripe.com/", 
        "https://www.google.com/",
        "https://www.apple.com/",
        "https://www.github.com/",
        "https://www.reddit.com/",
        "https://www.amazon.com/",
        # "https://www.microsoft.com/",
        # "https://www.facebook.com/",
        # "https://www.twitter.com/",
        # "https://www.instagram.com/",
        # "https://www.linkedin.com/",
        # "https://www.youtube.com/",
    ]
    # archive_tasks = [tracker.get_nearest_archive(url, "20250101") for url in urls]
    # archive_infos = await asyncio.gather(*archive_tasks, return_exceptions=True)
    # for info in archive_infos:
    #     print(info)
    import time
    
    start_time = time.time()
    results = await tracker.compare(urls, day_delta=100)
    elapsed = time.time() - start_time
    
    print(f"Total time: {elapsed:.2f} seconds for {len(urls)} URLs")
    return results





if __name__ == "__main__":  
    # asyncio.run(test_ArchiveTracker()) # 13 urls:Total time: 97.84 seconds for 13 URLs
    asyncio.run(test_ArchiveTracker())