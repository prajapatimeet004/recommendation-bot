import httpx
import logging
import os
import asyncio
from typing import List, Optional, Dict, Any


logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS: List[str] = [
    "flipkart.com",
    "amazon.in",
    "myntra.com",
    "nykaa.com",
    "croma.com",
]

TAVILY_API_URL = "https://api.tavily.com/search"


class SearchService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    async def search_single_query(
        self,
        query: str,
        domains: Optional[List[str]] = None,
        max_results: int = 6
    ) -> List[Dict[str, Any]]:
        """Search Tavily for a single query and return list of result dicts."""
        if not self.api_key:
            logger.error("Tavily API key is missing. Skip search.")
            return []

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_domains": domains or SUPPORTED_DOMAINS,
            "max_results": max_results,
            "include_raw_content": False,
            "include_answer": False,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(TAVILY_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                
                output = []
                for r in results:
                    url = r.get("url")
                    if url:
                        output.append({
                            "url": url,
                            "title": r.get("title") or "",
                            "snippet": r.get("content") or ""
                        })
                logger.debug("Tavily search for query '%s' returned %d results", query, len(output))
                return output
            except Exception as e:
                logger.warning("Tavily search failed for query '%s': %s", query, e)
                return []

    async def search_multiple_queries(
        self,
        keywords: List[str],
        domains: Optional[List[str]] = None,
        max_results_per_query: int = 5
    ) -> List[Dict[str, Any]]:
        """Search Tavily for multiple keywords in parallel and return deduplicated results."""
        if not keywords:
            return []

        # Run search queries in parallel
        tasks = [
            self.search_single_query(kw, domains, max_results_per_query)
            for kw in keywords[:5]  # Search top 5 keywords
        ]
        results = await asyncio.gather(*tasks)

        # Merge and deduplicate while maintaining order
        seen_urls = set()
        deduplicated_results = []
        for result_list in results:
            for r in result_list:
                url = r["url"]
                norm_url = url.split("?")[0].rstrip("/").lower()
                if norm_url not in seen_urls:
                    seen_urls.add(norm_url)
                    deduplicated_results.append(r)

        logger.info(
            "Tavily multi-query search finished. Found %d deduplicated results from %d queries.",
            len(deduplicated_results),
            len(keywords[:5])
        )
        return deduplicated_results

