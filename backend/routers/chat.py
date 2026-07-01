from __future__ import annotations

import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.schemas import ChatRequest, ChatResponse, Message, ResponseType, SearchContext
from backend.pipeline.shopping_pipeline import run_pipeline
from backend.services.product_service import get_paginated, has_more, enrich_product, clear_pagination
from backend.services.pipeline_logger import get_pipeline_logger

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[asyncio.Queue]] = {}

    def get_queue(self, session_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(queue)
        return queue

    def disconnect(self, session_id: str, queue: asyncio.Queue):
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(queue)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast(self, session_id: str, data: dict):
        if session_id in self.active_connections:
            for queue in list(self.active_connections[session_id]):
                await queue.put(data)

manager = ConnectionManager()

def _get_combined_query(request: ChatRequest) -> str:
    """Reconstruct the full query if the current message is answering a clarification question."""
    query = request.message
    history = request.history
    if history and len(history) >= 3:
        current_user_msg = history[-1]
        last_assistant_msg = history[-2]
        prev_user_msg = history[-3]
        if (
            current_user_msg.role == "user"
            and last_assistant_msg.role == "assistant"
            and last_assistant_msg.response_type == "NEEDS_CLARIFICATION"
            and prev_user_msg.role == "user"
        ):
            query = f"{prev_user_msg.content} {query}"
    return query


@router.get("/chat/stream/{session_id}")
async def chat_stream(session_id: str):
    async def event_generator():
        queue = manager.get_queue(session_id)
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            manager.disconnect(session_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    page_token: Optional[str] = Query(None),
):
    # Handle "show more" pagination
    if page_token:
        return await _handle_pagination(request, page_token, background_tasks)

    try:
        result = await run_pipeline(
            user_message=request.message,
            session_id=request.activeChatId,
            history=request.history,
        )

        intent = result.get("intent", "RECOMMEND")
        products = result.get("products", [])
        all_products = result.get("all_products", [])
        keywords = result.get("keywords", [])
        data_source = result.get("data_source", "live")
        detailed_intent = result.get("detailed_intent", {})
        clarification_question = result.get("clarification_question")
        clarification_options = result.get("clarification_options", [])
        generated_response = result.get("generated_response")
        comparison = result.get("comparison")

        # Automatically start the background product discovery task
        if intent in ("RECOMMEND", "COMPARE", "FOLLOW_UP", "BUNDLE") and request.activeChatId and result.get("run_background_discovery", True):
            from backend.services.discovery_task import discover_and_update_products_task
            combined_query = _get_combined_query(request)
            background_tasks.add_task(
                discover_and_update_products_task,
                session_id=request.activeChatId,
                query=combined_query,
                intent=detailed_intent
            )

        keyword_str = ", ".join(keywords[:5]) if keywords else request.message

        return _build_response(
            message=request.message,
            intent=intent,
            products=products,
            all_count=len(all_products),
            keywords_used=keyword_str,
            data_source=data_source,
            session_id=request.activeChatId,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
            generated_response=generated_response,
            comparison=comparison,
        )

    except Exception as exc:
        logger.exception("Chat pipeline error")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(exc)}")


async def _handle_pagination(request: ChatRequest, page_token: str, background_tasks: BackgroundTasks) -> ChatResponse:
    try:
        offset = int(page_token)
    except (ValueError, TypeError):
        offset = 0

    session_id = request.activeChatId or ""
    # Use the combined context-aware query for pagination
    query = _get_combined_query(request)

    # Trigger background search on Apify for pagination
    if session_id:
        try:
            from backend.services.keyword_service import KeywordService
            from backend.services.discovery_task import discover_and_update_products_task
            kw_service = KeywordService()
            detailed_intent = kw_service.extract_detailed_intent(query)
            
            background_tasks.add_task(
                discover_and_update_products_task,
                session_id=session_id,
                query=query,
                intent=detailed_intent
            )
        except Exception as e:
            logger.warning("Failed to queue background discovery task for pagination: %s", e)

    # 1. Try to get from pagination store first
    next_products = get_paginated(session_id, query, page_token)
    more_available = has_more(session_id, query, page_token)

    # 2. Fallback to querying and ranking if not in store
    if not next_products:
        # Predict category based on query to narrow ChromaDB search
        from backend.services.keyword_service import KeywordService
        kw_service = KeywordService()
        predicted_cat = kw_service._fallback_category(query)

        # Directly retrieve from ChromaDB category collections
        from backend.pipeline.shopping_pipeline import _vector_service, _recommendation_service, _apply_keyword_scores, parse_budget
        db_products = await _vector_service.search_all_collections([predicted_cat], query, n=offset + 6)
        
        # Apply keyword re-scoring & re-ranking to be consistent
        analysis = kw_service.analyze(query)
        keywords = analysis.get("keywords", [])
        _apply_keyword_scores(db_products, keywords)
        
        # Rank with budget
        budget = parse_budget(query)
        ranked = _recommendation_service.rank(db_products, query=query, budget=budget)
        
        chunk = ranked[offset:offset + 3]
        more_available = len(ranked) > offset + 3
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
    clarification_question: Optional[str] = None,
    clarification_options: Optional[List[str]] = None,
    generated_response: Optional[str] = None,
    comparison: Optional[Dict[str, Any]] = None,
) -> ChatResponse:
    import hashlib
    query_hash = hashlib.md5(message.strip().lower().encode()).hexdigest()[:8]

    product_outputs = []
    for p in products:
        product_outputs.append(enrich_product(p))

    more_available = all_count > len(product_outputs)
    follow_ups = _generate_follow_ups(intent, products, clarification_options)

    # Use generated response if available (from LLM product reference), else template
    response_message = (
        clarification_question
        or generated_response
        or _generate_message(intent, products, message)
    )

    return ChatResponse(
        message=response_message,
        response_type=_map_intent(intent),
        search_context=SearchContext(
            keywords_used=keywords_used,
            data_source=data_source,
            query_hash=query_hash,
        ),
        products=product_outputs if product_outputs else None,
        comparison=comparison,
        pagination_token=str(len(product_outputs)) if more_available else None,
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
        "NEEDS_CLARIFICATION": ResponseType.NEEDS_CLARIFICATION,
    }
    return mapping.get(intent, ResponseType.RECOMMEND)


def _generate_follow_ups(intent: str, products: List[Dict[str, Any]], clarification_options: Optional[List[str]] = None) -> List[str]:
    follow_ups = []
    if intent in ("GREETING", "GENERAL"):
        return ["Best laptop under ₹80,000", "Gym shoes and clothes", "Smartphones under ₹40,000"]
    if intent == "NEEDS_CLARIFICATION":
        return clarification_options or ["For Men", "For Women", "For Both"]
    if products:
        if len(products) >= 2:
            follow_ups.append(f"Compare {products[0].get('name', 'product 1')} and {products[1].get('name', 'product 2')}")
        follow_ups.append("Show more")
        follow_ups.append("What are the cheaper options?")
    follow_ups.extend(["Search again", "Find accessories"])
    return follow_ups
