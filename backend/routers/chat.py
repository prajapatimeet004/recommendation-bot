from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.schemas import ChatRequest, ChatResponse, Message, ResponseType, SearchContext
from backend.pipeline.shopping_pipeline import run_pipeline
from backend.services.product_service import get_paginated, has_more, enrich_product, clear_pagination
from backend.services.product_cache import ProductCache
from backend.services.pipeline_logger import get_pipeline_logger

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    page_token: Optional[str] = Query(None),
):
    tavily_key = os.environ.get("TAVILY_API_KEY", "")

    # Handle "show more" pagination
    if page_token:
        return await _handle_pagination(request, page_token)

    try:
        result = await run_pipeline(
            user_message=request.message,
            session_id=request.activeChatId,
            tavily_api_key=tavily_key,
        )

        intent = result.get("intent", "RECOMMEND")
        products = result.get("products", [])
        all_products = result.get("all_products", [])
        keywords = result.get("keywords", [])
        data_source = result.get("data_source", "live")

        keyword_str = ", ".join(keywords[:5]) if keywords else request.message

        return _build_response(
            message=request.message,
            intent=intent,
            products=products,
            all_count=len(all_products),
            keywords_used=keyword_str,
            data_source=data_source,
            session_id=request.activeChatId,
        )

    except Exception as exc:
        logger.exception("Chat pipeline error")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(exc)}")


async def _handle_pagination(request: ChatRequest, page_token: str) -> ChatResponse:
    try:
        offset = int(page_token)
    except (ValueError, TypeError):
        offset = 0

    # Predict category based on query to narrow ChromaDB search
    from backend.services.keyword_service import KeywordService
    kw_service = KeywordService()
    predicted_cat = kw_service._fallback_category(request.message)

    # Directly retrieve from ChromaDB category collections
    from backend.pipeline.shopping_pipeline import _vector_service
    db_products = await _vector_service.search_all_collections([predicted_cat], request.message, n=offset + 6)
    
    chunk = db_products[offset:offset + 3]
    more_available = len(db_products) > offset + 3

    next_products = [enrich_product(p) for p in chunk]

    return ChatResponse(
        message=f"Showing more products for '{request.message}'.",
        response_type=ResponseType.RECOMMEND,
        products=next_products if next_products else None,
        pagination_token=str(offset + 3) if more_available and next_products else None,
        total_products=len(next_products),
        data_freshness="cached",
    )

def _build_response(
    message: str,
    intent: str,
    products: List[Dict[str, Any]],
    all_count: int,
    keywords_used: str,
    data_source: str,
    session_id: str,
) -> ChatResponse:
    import hashlib
    query_hash = hashlib.md5(message.strip().lower().encode()).hexdigest()[:8]

    product_outputs = []
    for p in products:
        product_outputs.append(enrich_product(p))

    more_available = all_count > 3
    follow_ups = _generate_follow_ups(intent, products)

    return ChatResponse(
        message=_generate_message(intent, products, message),
        response_type=_map_intent(intent),
        search_context=SearchContext(
            keywords_used=keywords_used,
            data_source=data_source,
            query_hash=query_hash,
        ),
        products=product_outputs if product_outputs else None,
        pagination_token="3" if more_available else None,
        total_products=len(product_outputs),
        follow_up_questions=follow_ups,
        followUps=follow_ups,
        data_freshness=data_source,
    )


def _generate_message(intent: str, products: List[Dict[str, Any]], query: str) -> str:
    if intent in ("GREETING", "GENERAL"):
        return "Hello! I'm your AI Shopping Assistant. Tell me what you're looking for — clothes, electronics, fitness gear, or anything else — and I'll find the best products for you!"
    if not products:
        return f"I couldn't find specific products for '{query}'. Try different keywords or be more specific."
    if intent == "BUNDLE":
        names = [p.get("name", "a product") for p in products[:3]]
        return f"Here's a curated bundle for you: {', '.join(names)}. I've selected items that work well together."
    names = [p.get("name", "a product") for p in products[:3]]
    if len(names) == 1:
        name_str = names[0]
    elif len(names) == 2:
        name_str = f"{names[0]} and {names[1]}"
    else:
        name_str = f"{names[0]}, {names[1]}, and {names[2]}"
    return f"Here are {len(products)} great options for '{query}': {name_str}. They're ranked by relevance, price fit, and ratings."


def _map_intent(intent: str) -> ResponseType:
    mapping = {
        "RECOMMEND": ResponseType.RECOMMEND,
        "COMPARE": ResponseType.COMPARE,
        "FOLLOW_UP": ResponseType.RECOMMEND,
        "BUNDLE": ResponseType.BUNDLE,
        "GENERAL": ResponseType.GENERAL,
        "EXPLAIN": ResponseType.EXPLAIN,
        "GREETING": ResponseType.GREETING,
    }
    return mapping.get(intent, ResponseType.RECOMMEND)


def _generate_follow_ups(intent: str, products: List[Dict[str, Any]]) -> List[str]:
    follow_ups = []
    if intent in ("GREETING", "GENERAL"):
        return ["Best laptop under ₹80,000", "Gym shoes and clothes", "Smartphones under ₹40,000"]
    if products:
        if len(products) >= 2:
            follow_ups.append(f"Compare {products[0].get('name', 'product 1')} and {products[1].get('name', 'product 2')}")
        follow_ups.append("Show more")
        follow_ups.append("What are the cheaper options?")
    follow_ups.extend(["Search again", "Find accessories"])
    return follow_ups
