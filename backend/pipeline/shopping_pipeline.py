from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.services.keyword_service import KeywordService
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.recommendation_service import RecommendationService
from backend.services.product_service import store_pagination, clear_pagination
from backend.services.pipeline_logger import get_pipeline_logger

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

_keyword_service = KeywordService()
_embedding_service = EmbeddingService()
_vector_service = VectorService(embedding_service=_embedding_service)
_recommendation_service = RecommendationService()

CATEGORY_FALLBACK_MAP = {
    "smartphones": ["smartphones", "electronics", "other"],
    "laptops": ["laptops", "electronics", "other"],
    "fashion": ["fashion", "footwear", "other"],
    "beauty": ["fashion", "other"],
    "footwear": ["footwear", "fashion", "other"],
    "home_appliances": ["electronics", "other"],
    "electronics": ["electronics", "smartphones", "laptops", "other"],
    "other": ["other", "fashion", "electronics"],
}


async def run_pipeline(
    user_message: str,
    session_id: str = "",
    **kwargs,
) -> Dict[str, Any]:
    plog.info("")
    plog.info("=" * 60)
    plog.info("LOCAL SHOPPING PIPELINE — query='%s'", user_message)
    plog.info("=" * 60)

    clear_pagination(session_id, user_message)

    # STEP 1 & 2: Intent detection, Keyword generation, and Category classification
    plog.info("STEP 1&2 -- Intent + Keywords + Category classification")
    analysis = _keyword_service.analyze(user_message)
    intent = analysis.get("intent", "RECOMMEND")
    keywords = analysis.get("keywords", [])
    predicted_category = analysis.get("category", "other")

    if intent in ("GREETING", "GENERAL"):
        plog.info("  -> Non-shopping intent=%s — returning empty pipeline", intent)
        return {
            "intent": intent,
            "products": [],
            "keywords": keywords,
            "data_source": "none",
        }

    if intent in ("COMPARE", "FOLLOW_UP", "BUNDLE", "EXPLAIN"):
        plog.info("  -> Special intent=%s — passing through", intent)

    # STEP 3: Vector search on local ChromaDB
    plog.info("STEP 3 -- Local Vector Search (category=%s)", predicted_category)
    search_categories = CATEGORY_FALLBACK_MAP.get(predicted_category, ["other", "fashion", "electronics"])
    plog.info("  -> Search categories: %s", search_categories)

    results = await _vector_service.search_all_collections(search_categories, user_message, n=50)

    if not results:
        plog.info("  -> No results from vector search")
        return {
            "intent": intent,
            "products": [],
            "keywords": keywords,
            "data_source": "local",
        }

    plog.info("  -> Vector search returned %d products", len(results))

    # STEP 4: Keyword re-scoring & re-ranking
    plog.info("STEP 4 -- Keyword Re-scoring & Re-ranking")
    _apply_keyword_scores(results, keywords)

    results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    products = results

    plog.info("  -> Top %d products:", min(3, len(products)))
    for i, p in enumerate(products[:3]):
        plog.info(
            "    -> [%d] score=%.4f | %s | Rs %s | %s",
            i + 1,
            p.get("_score", 0.0),
            p.get("name", "?"),
            p.get("price", "?"),
            p.get("source", "?"),
        )

    # STEP 5: Composite Scoring, Ranking, and Top 3 Selection
    plog.info("STEP 5 -- Scoring & Ranking")
    top3 = _recommendation_service.top_n(products, n=3, query=user_message)

    if session_id:
        store_pagination(session_id, user_message, products)

    return {
        "intent": intent,
        "products": top3,
        "all_products": products,
        "keywords": keywords,
        "data_source": "local",
    }


def _apply_keyword_scores(products: List[Dict[str, Any]], keywords: List[str]) -> None:
    if not products or not keywords:
        for p in products or []:
            p["_score"] = p.get("_score", 0.5)
        return

    all_terms = set()
    for kw in keywords:
        all_terms.update(re.findall(r'[a-zA-Z0-9]+', kw.lower()))
    significant_terms = {t for t in all_terms if len(t) > 2}

    if not significant_terms:
        for p in products:
            p["_score"] = p.get("_score", 0.5)
        return

    for p in products:
        name = (p.get("name", "") or "").lower()
        brand = (p.get("brand", "") or "").lower()
        combined = f"{name} {brand}"

        matched = sum(1 for term in significant_terms if term in combined)
        ratio = matched / len(significant_terms)
        kw_score = round(min(0.3 + 0.7 * ratio, 1.0), 4)

        vec_score = p.get("_score", 0.0) or 0.0
        p["_score"] = round(0.4 * vec_score + 0.6 * kw_score, 4)
