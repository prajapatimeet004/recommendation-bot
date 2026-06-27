from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from backend.models.product import ProductOutput

logger = logging.getLogger(__name__)

_PAGINATION_STORE: Dict[str, List[Dict[str, Any]]] = {}


def _make_key(session_id: str, query: str) -> str:
    raw = f"{session_id}:{query.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def store_pagination(session_id: str, query: str, products: List[Dict[str, Any]]) -> str:
    key = _make_key(session_id, query)
    _PAGINATION_STORE[key] = list(products)
    return key


def get_paginated(session_id: str, query: str, page_token: str, page_size: int = 3) -> List[ProductOutput]:
    key = _make_key(session_id, query)
    products = _PAGINATION_STORE.get(key, [])
    try:
        offset = int(page_token)
    except (ValueError, TypeError):
        return []
    chunk = products[offset:offset + page_size]
    return [_to_output(p) for p in chunk]


def has_more(session_id: str, query: str, page_token: str) -> bool:
    key = _make_key(session_id, query)
    products = _PAGINATION_STORE.get(key, [])
    try:
        offset = int(page_token) + 3
    except (ValueError, TypeError):
        return False
    return offset < len(products)


def clear_pagination(session_id: str, query: str) -> None:
    key = _make_key(session_id, query)
    _PAGINATION_STORE.pop(key, None)


def _to_output(product: Dict[str, Any]) -> ProductOutput:
    raw_score = product.get("_score", 0) or product.get("score", 0) or 0
    sim_score = round(raw_score * 100, 1) if isinstance(raw_score, (int, float)) else None

    # Resolve urls and images
    p_url = product.get("url") or product.get("product_url") or product.get("source_url", "")
    p_image = product.get("image") or product.get("image_url") or ""

    return ProductOutput(
        id=product.get("id") or p_url or f"prod-{abs(hash(str(product.get('name', ''))))}",
        name=product.get("name", ""),
        brand=product.get("brand"),
        price=product.get("price"),
        mrp=product.get("mrp"),
        discount=product.get("discount"),
        currency=product.get("currency", "INR"),
        image_url=p_image,
        product_url=p_url,
        rating=product.get("rating"),
        specifications=product.get("specifications", product.get("specs", {})),
        description=product.get("description", ""),
        category=product.get("category"),
        tags=product.get("tags", []),
        source=product.get("source", ""),
        similarity_score=sim_score,
        # Schema matching fields
        image=p_image,
        url=p_url,
        availability=product.get("availability"),
        scraped_at=product.get("scraped_at")
    )


def enrich_product(product: Dict[str, Any]) -> ProductOutput:
    return _to_output(product)


def deduplicate(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for p in products:
        name = p.get("name", "").lower().strip()[:60]
        url = (p.get("url") or p.get("product_url") or p.get("source_url", "")).split("?")[0].rstrip("/")
        key = name or url
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique

