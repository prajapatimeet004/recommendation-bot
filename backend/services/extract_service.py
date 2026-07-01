# pyrefly: ignore [missing-import]
import httpx
import logging
import asyncio
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class ExtractService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    async def extract_url_content(self, url: str, retries: int = 3) -> Optional[str]:
        """Extract content of a single URL using Tavily Extract with automatic retries."""
        if not self.api_key:
            logger.error("Tavily API key is missing. Skip extraction.")
            return None

        payload = {
            "api_key": self.api_key,
            "urls": [url],
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(1, retries + 1):
                try:
                    logger.info("Extracting content for URL: %s (attempt %d/%d)", url, attempt, retries)
                    resp = await client.post(TAVILY_EXTRACT_URL, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    results = data.get("results", [])
                    if results:
                        item = results[0]
                        content = item.get("raw_content") or item.get("content", "")
                        if content:
                            return content.strip()
                    
                    logger.warning("Empty content returned from Tavily Extract for URL: %s", url)
                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as e:
                    logger.warning("Attempt %d failed to extract %s: %s", attempt, url, e)
                    
                if attempt < retries:
                    # Exponential backoff (e.g. 2s, 4s)
                    wait_time = 2 ** attempt
                    logger.debug("Waiting %ds before retry for URL %s", wait_time, url)
                    await asyncio.sleep(wait_time)

            logger.error("All extraction attempts failed for URL: %s", url)
            return None

    async def extract_batch_urls(self, urls: List[str], retries: int = 3) -> Dict[str, str]:
        """Extract content for a batch of URLs in parallel and return url -> content map."""
        if not urls:
            return {}

        logger.info("Starting batch extraction of %d URLs", len(urls))
        tasks = [self.extract_url_content(url, retries) for url in urls]
        results = await asyncio.gather(*tasks)

        extracted_map = {}
        for url, content in zip(urls, results):
            if content:
                extracted_map[url] = content

        logger.info("Batch extraction finished. Extracted content for %d/%d URLs", len(extracted_map), len(urls))
        return extracted_map
