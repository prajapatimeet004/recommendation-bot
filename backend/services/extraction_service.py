from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.services.pipeline_logger import get_pipeline_logger
from backend.services.regex_parser import parse_products
from backend.models.product import ExtractedProduct

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()


class ExtractionService:
    """
    Extracts structured product data from TavilyResult objects using a
    pure regex + rule-based parser. No LLM calls are made for extraction.

    The parser handles Amazon.in, Flipkart, Myntra, Nykaa, Croma, and Ajio.
    """

    def __init__(self) -> None:
        pass

    def extract_products(
        self,
        tavily_results: list,
        max_price: Optional[float] = None,
        query: str = "",
        keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not tavily_results:
            logger.warning("ExtractionService received empty result list")
            return []

        plog.info(
            "REGEX EXTRACTION -- %d page(s)",
            len(tavily_results),
        )

        for i, r in enumerate(tavily_results):
            content_preview = (getattr(r, "raw_content", None) or getattr(r, "content", None) or "")[:200].replace("\n", " | ")
            plog.info(
                "  -> PAGE %d: [%.2f] %s | %s",
                i + 1,
                getattr(r, "score", 0),
                getattr(r, "title", "")[:80] or "no title",
                getattr(r, "url", "")[:100],
            )
            plog.info("       content: %s", content_preview)

        products = parse_products(tavily_results)

        if max_price is not None:
            before = len(products)
            products = [p for p in products if p.price is None or p.price <= max_price]
            plog.info("  -> price_filter: %d -> %d (max=%.0f)", before, len(products), max_price)

        validated = []
        for p in products:
            validated.append(p.model_dump(exclude_none=False))

        self._score_products(validated, query, keywords or [])

        if not validated:
            plog.info("  -> regex returned 0 products")
        else:
            plog.info("  -> regex extracted %d product(s)", len(validated))
            for i, p in enumerate(validated):
                plog.info(
                    "    -> [%d]: %s | Rs %s | brand=%s | rating=%s | source=%s | _score=%.4f",
                    i + 1,
                    p.get("name", "?"),
                    p.get("price", "?"),
                    p.get("brand", "?"),
                    p.get("rating", "?"),
                    p.get("source", "?"),
                    p.get("_score", 0),
                )

        return validated

    def _score_products(self, products: List[Dict], query: str, keywords: List[str]) -> None:
        if not products or not query:
            for p in products or []:
                p["_score"] = p.get("_score", 0.5)
            return

        all_terms = set()
        for text in [query] + (keywords or []):
            all_terms.update(re.findall(r'[a-zA-Z0-9]+', text.lower()))
        significant_terms = {t for t in all_terms if len(t) > 2}

        if not significant_terms:
            for p in products:
                p["_score"] = p.get("_score", 0.5)
            return

        for p in products:
            name = (p.get("name", "") or "").lower()
            brand = (p.get("brand", "") or "").lower()
            desc = (p.get("description", "") or "").lower()
            combined_text = f"{name} {brand} {desc}"

            matched = sum(1 for term in significant_terms if term in combined_text)
            total = len(significant_terms)
            ratio = matched / total if total > 0 else 0
            score = 0.3 + 0.7 * ratio
            p["_score"] = round(min(score, 1.0), 4)
