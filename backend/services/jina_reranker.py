import logging
import time as time_module
from typing import Any, Dict, List, Optional

import httpx

from backend.services.embedding_service import EmbeddingService
from backend.settings import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.jina.ai/v1/rerank"
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0


class JinaReranker:
    def __init__(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        self._embedding_service = embedding_service or EmbeddingService()

    async def rerank(
        self,
        query: str,
        products: List[Dict[str, Any]],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not products:
            return []

        if not settings.JINA_API_KEY:
            logger.warning("JINA_API_KEY not set — skipping Jina reranking")
            return products

        top_n = top_n or settings.JINA_RERANK_TOP_N
        docs = [self._embedding_service.build_embedding_text(p) for p in products]

        payload = {
            "model": settings.JINA_RERANK_MODEL,
            "query": query,
            "documents": docs,
            "top_n": min(top_n, len(docs)),
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {settings.JINA_API_KEY}",
            "Content-Type": "application/json",
        }

        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(_API_URL, json=payload, headers=headers)

                if resp.status_code == 429:
                    sleep = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Jina rate limit hit (attempt %d/%d). Retrying in %.1fs...", attempt + 1, _MAX_RETRIES, sleep)
                    time_module.sleep(sleep)
                    continue

                resp.raise_for_status()
                data = resp.json()

                results = data.get("results", [])
                if not results:
                    logger.warning("Jina reranker returned empty results — keeping original order")
                    return products

                index_to_score = {r["index"]: r["relevance_score"] for r in results}

                for i, p in enumerate(products):
                    p["_jina_score"] = round(index_to_score.get(i, 0.0), 4)

                reranked = sorted(products, key=lambda x: x.get("_jina_score", 0.0), reverse=True)

                logger.info("Jina reranker scored %d products (top score: %.4f)", len(reranked), reranked[0].get("_jina_score", 0.0))
                return reranked

            except httpx.HTTPStatusError as e:
                last_exc = e
                logger.warning("Jina API HTTP error (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES, e)
            except Exception as e:
                last_exc = e
                logger.warning("Jina reranker error (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES, e)

            if attempt < _MAX_RETRIES - 1:
                sleep = _BACKOFF_BASE * (2 ** attempt)
                time_module.sleep(sleep)

        logger.error("Jina reranker failed after %d attempts: %s — returning original order", _MAX_RETRIES, last_exc)
        return products
