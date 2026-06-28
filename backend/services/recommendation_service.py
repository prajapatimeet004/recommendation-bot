from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WEIGHTS = {
    "semantic_similarity": 0.4,
    "price_relevance": 0.3,
    "rating": 0.2,
    "completeness": 0.1,
}


class RecommendationService:
    def rank(
        self,
        products: List[Dict[str, Any]],
        query: str = "",
        budget: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        if not products:
            return []

        scored = []
        for p in products:
            score = self._compute_score(p, query, budget)
            p["_composite_score"] = round(score, 4)
            if p["_composite_score"] >= 0.1:
                scored.append(p)

        scored.sort(key=lambda x: x["_composite_score"], reverse=True)
        return scored

    def top_n(self, products: List[Dict[str, Any]], n: int = 3, query: str = "", budget: Optional[float] = None) -> List[Dict[str, Any]]:
        ranked = self.rank(products, query, budget)
        return ranked[:n]

    def _compute_score(self, product: Dict[str, Any], query: str, budget: Optional[float]) -> float:
        total = 0.0

        sim = product.get("_score", 0) or product.get("score", 0) or 0
        if isinstance(sim, (int, float)) and sim > 0:
            total += min(sim, 1.0) * WEIGHTS["semantic_similarity"]

        price_rel = self._price_relevance(product, budget)
        total += price_rel * WEIGHTS["price_relevance"]

        rating = product.get("rating", 0) or 0
        if isinstance(rating, (int, float)) and rating > 0:
            norm_rating = min(rating / 5.0, 1.0)
            total += norm_rating * WEIGHTS["rating"]

        completeness = self._completeness(product)
        total += completeness * WEIGHTS["completeness"]

        return total

    def _price_relevance(self, product: Dict[str, Any], budget: Optional[float]) -> float:
        price = product.get("price", 0)
        if not price or not isinstance(price, (int, float)):
            return 0.5
        if not budget:
            return 0.8
        if price <= budget:
            ratio = price / budget
            category = product.get("category", "").lower()
            if category in ("smartphones", "laptops"):
                if ratio < 0.30:
                    return 0.15
                if ratio < 0.50:
                    return 0.40
                if ratio < 0.70:
                    return 0.80
                return 1.0
            else:
                if ratio < 0.20:
                    return 0.40
                if ratio < 0.50:
                    return 0.70
                return 1.0
        over = price - budget
        if over <= budget * 0.1:
            return 0.7
        if over <= budget * 0.25:
            return 0.4
        return 0.1

    def _completeness(self, product: Dict[str, Any]) -> float:
        fields = 0
        total = 7
        if product.get("name"):
            fields += 1
        if product.get("price") and product.get("price", 0) > 0:
            fields += 1
        if product.get("image") or product.get("image_url"):
            fields += 1
        if product.get("rating") and product.get("rating", 0) > 0:
            fields += 1
        if product.get("specifications"):
            fields += 1
        if product.get("brand"):
            fields += 1
        if product.get("mrp") and product.get("mrp", 0) > 0:
            fields += 1
        return fields / total

