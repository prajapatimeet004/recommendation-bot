import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from backend.services.vector_service import VectorService

logger = logging.getLogger(__name__)


class CacheService:
    def __init__(
        self,
        vector_service: VectorService,
        similarity_threshold: float = 0.82,
        ttl_days: int = 7,
        min_cache_hits: int = 3
    ) -> None:
        self.vector_service = vector_service
        self.similarity_threshold = similarity_threshold
        self.ttl_days = ttl_days
        self.min_cache_hits = min_cache_hits

    async def get_cached_products(
        self,
        query: str,
        categories: List[str],
        limit: int = 15
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Queries ChromaDB collections corresponding to categories.
        Returns products if they pass similarity threshold and are not stale.
        """
        logger.info(
            "Cache CHECK: query='%s' inside collections %s (threshold=%.2f, ttl=%d days)",
            query,
            categories,
            self.similarity_threshold,
            self.ttl_days
        )

        products = await self.vector_service.search_all_collections(categories, query, n=limit)
        if not products:
            logger.info("Cache MISS: collections are empty or no records found.")
            return None

        valid_products = []
        now = datetime.now(timezone.utc)

        for p in products:
            # Check similarity score
            score = p.get("_score", 0.0)
            if score < self.similarity_threshold:
                logger.debug("Skipping cached product '%s': score %.4f < %.2f", p.get("name"), score, self.similarity_threshold)
                continue

            # Check staleness
            scraped_at_str = p.get("scraped_at")
            is_stale = True
            if scraped_at_str:
                try:
                    scraped_at = datetime.fromisoformat(scraped_at_str)
                    age_days = (now - scraped_at).days
                    if age_days < self.ttl_days:
                        is_stale = False
                except Exception as e:
                    logger.warning("Failed to parse scraped_at timestamp '%s': %s", scraped_at_str, e)
            
            if is_stale:
                logger.debug("Skipping cached product '%s': stale or missing timestamp.", p.get("name"))
                continue

            valid_products.append(p)

        # Cache hit threshold: must have at least min_cache_hits (3) valid products
        if len(valid_products) >= self.min_cache_hits:
            logger.info("Cache HIT: Found %d valid, fresh product(s) in cache.", len(valid_products))
            return valid_products

        logger.info(
            "Cache MISS: Found only %d valid product(s) (minimum required is %d). Proceed to search live.",
            len(valid_products),
            self.min_cache_hits
        )
        return None
