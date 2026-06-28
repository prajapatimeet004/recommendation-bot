from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.schemas import Message
from backend.services.keyword_service import KeywordService, parse_budget, detect_gender
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.recommendation_service import RecommendationService
from backend.services.llm_gateway import LLMGateway
from backend.services.product_service import store_pagination, clear_pagination, enrich_product
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
    "beauty": ["beauty", "fashion", "other"],
    "footwear": ["footwear", "fashion", "other"],
    "home_appliances": ["home_appliances", "electronics", "other"],
    "electronics": ["electronics", "smartphones", "laptops", "other"],
    "other": ["other", "fashion", "electronics"],
}


_llm_gateway = LLMGateway()

_RESPONSE_GENERATION_PROMPT = """\
You are a knowledgeable e-commerce sales assistant. Answer the user's question naturally and helpfully using the product details provided.

## Conversation History (last 5 turns)
{conversation_context}

## Product Details
{product_details}

## Current Question
{user_message}

Answer concisely and helpfully. Be specific about specifications, prices, and features. If the user asks about a specific product feature (battery life, camera, display, processor, etc.), provide exact details from the specs. Keep your response under 4 sentences unless more detail is specifically requested."""


async def run_pipeline(
    user_message: str,
    session_id: str = "",
    history: List[Message] = None,
    **kwargs,
) -> Dict[str, Any]:
    plog.info("")
    plog.info("=" * 60)
    plog.info("LOCAL SHOPPING PIPELINE — query='%s'", user_message)
    plog.info("=" * 60)

    if history:
        plog.info("  -> history has %d messages, extracting context", len(history))

    # Format conversation context from history (last 5 user+assistant pairs)
    conversation_context = _format_conversation_context(history) if history else ""
    is_product_reference = _references_previous_product(user_message) if history else False
    recent_products = _get_recent_products(history) if is_product_reference else []

    if conversation_context:
        plog.info("  -> conversation context: %s", conversation_context[:100].replace("\n", " | "))
    if is_product_reference:
        plog.info("  -> detected product reference, recent products: %d", len(recent_products))

    clear_pagination(session_id, user_message)

    # STEP 1 & 2: Intent detection, Keyword generation, and Category classification
    plog.info("STEP 1&2 -- Intent + Keywords + Category classification")
    detailed_intent = _keyword_service.extract_detailed_intent(
        user_message,
        conversation_context=conversation_context,
    )
    intent = detailed_intent.get("intent", "RECOMMEND")
    keywords = detailed_intent.get("keywords", [])
    predicted_category = detailed_intent.get("category", "other")

    if intent in ("GENERAL", "GREETING") and recent_products:
        plog.info("  -> Overriding %s -> FOLLOW_UP because conversation has products", intent)
        intent = "FOLLOW_UP"
        detailed_intent["intent"] = "FOLLOW_UP"

    if intent in ("GREETING", "GENERAL"):
        plog.info("  -> Non-shopping intent=%s — returning empty pipeline", intent)
        return {
            "intent": intent,
            "products": [],
            "keywords": keywords,
            "data_source": "none",
            "detailed_intent": detailed_intent,
        }

    if intent in ("COMPARE", "FOLLOW_UP", "BUNDLE", "EXPLAIN"):
        plog.info("  -> Special intent=%s — passing through", intent)

    # Gender detection for fashion/footwear/beauty categories
    if intent == "RECOMMEND" and predicted_category in ("fashion", "footwear", "beauty"):
        gender = detect_gender(user_message)
        if gender is None:
            plog.info("  -> Gender not specified in query for category=%s — asking clarification", predicted_category)
            return {
                "intent": "NEEDS_CLARIFICATION",
                "products": [],
                "keywords": keywords,
                "data_source": "none",
                "detailed_intent": detailed_intent,
                "clarification_question": "Are you looking for Men's or Women's products?",
                "clarification_options": ["Men", "Women", "Both"],
            }
        detailed_intent["gender"] = gender

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

    # STEP 5: Composite Scoring, Ranking, and Top 5 Selection
    plog.info("STEP 5 -- Scoring & Ranking")
    budget = parse_budget(user_message)
    if budget is not None:
        plog.info("  -> Parsed budget constraint: Rs %.2f", budget)
    top_products = _recommendation_service.top_n(products, n=5, query=user_message, budget=budget)

    # Calculate highest local score
    max_score = max(p.get("_composite_score", 0.0) for p in top_products) if top_products else 0.0

    if max_score >= 0.70:
        plog.info("  -> Found highly relevant local product(s) (max score = %.4f). Returning instantly.", max_score)
        run_background_discovery = True
        data_source = "local"
    else:
        plog.info("  -> No highly relevant local products found (max score = %.4f). Falling back to synchronous Apify discovery.", max_score)
        from backend.services.apify_service import ApifyService
        from backend.services.discovery_task import calculate_relevance_score
        
        apify_service = ApifyService()
        raw_products = []
        try:
            raw_products = await apify_service.discover_products(detailed_intent)
        except Exception as e:
            plog.error("  -> Synchronous Apify discovery failed: %s", str(e))
            
        # Score and validate scraped products
        query_embedding = _embedding_service.generate(user_message)
        accepted_products = []
        for p in raw_products:
            score = calculate_relevance_score(p, detailed_intent, query_embedding)
            p["_score"] = score
            if score >= 0.6:
                accepted_products.append(p)
                
        # Rank and select top 5 from scraped products
        top_products = _recommendation_service.top_n(accepted_products, n=5, query=user_message, budget=budget)
        
        # Deduplicate and store all accepted scraped products in ChromaDB
        if accepted_products:
            new_products = []
            for p in accepted_products:
                is_duplicate = False
                try:
                    col = _vector_service.get_collection(p["category"])
                    existing = col.get(ids=[p["id"]])
                    if existing and existing.get("ids"):
                         is_duplicate = True
                except Exception:
                    pass
                if not is_duplicate:
                    new_products.append(p)
            
            if new_products:
                plog.info("  -> Storing %d new crawled products in ChromaDB", len(new_products))
                await _vector_service.store_products(new_products, keywords=keywords)
                
        # Map fields to match database schema expected by frontend
        for p in top_products:
            p["url"] = p.get("product_url") or p.get("url")
            p["image"] = p.get("image_url") or p.get("image")
        products = accepted_products
        run_background_discovery = True
        data_source = "live"

    if session_id:
        store_pagination(session_id, user_message, products)

    # Generate LLM response if user is referencing previous products
    generated_response = None
    if is_product_reference and recent_products and intent not in ("GREETING", "GENERAL"):
        product_context = _format_product_context(recent_products)
        generated_response = await _generate_product_response(
            user_message, conversation_context, product_context
        )
        if generated_response:
            plog.info("  -> generated LLM response: %s", generated_response[:80])

    return {
        "intent": intent,
        "products": top_products,
        "all_products": products,
        "keywords": keywords,
        "data_source": data_source,
        "detailed_intent": detailed_intent,
        "run_background_discovery": run_background_discovery,
        "generated_response": generated_response,
    }


def _format_conversation_context(history: List[Message], max_pairs: int = 5) -> str:
    """Format last N user+assistant message pairs as conversation context text."""
    if not history:
        return ""
    chat = [m for m in history if m.role in ("user", "assistant")]
    recent = chat[-(max_pairs * 2):]
    lines = [f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in recent]
    return "\n".join(lines)


def _references_previous_product(message: str) -> bool:
    """Quick regex check if user message references previously shown products."""
    low = message.lower()
    patterns = [
        r'\b(this|that|those|it|them|the one|the first|the second|the third)\b',
        r'\btell me more\b',
        r'\bwhat about\b',
        r'\bhow about\b',
        r'\baccessor(y|ies)\b',
        r'\bcompatible\b',
        r'\bfor (this|that|it|the|my)\b',
        r'\bdetail(s)?\b',
        r'\bspec(s|ifications)?\b',
        r'\bdescribe\b',
        r'\bexplain\b',
        r'\bcompare\b',
        r'\bversus\b',
        r'\bvs\b',
        r'\bdifference\b',
    ]
    return any(re.search(p, low) for p in patterns)


def _get_recent_products(history: List[Message]) -> List[Dict[str, Any]]:
    """Get products from the last assistant message that has products."""
    for msg in reversed(history):
        if msg.role == "assistant" and msg.products:
            return msg.products
    return []


def _format_product_context(products: List[Dict[str, Any]]) -> str:
    """Format product details for LLM context injection."""
    if not products:
        return ""
    lines = []
    for i, p in enumerate(products[:5], 1):
        name = p.get("name", "Unknown")
        brand = p.get("brand", "")
        price = p.get("price", "N/A")
        rating = p.get("rating", "N/A")
        specs = p.get("specs", {})
        specs_str = "; ".join(f"{k}: {v}" for k, v in specs.items()) if isinstance(specs, dict) else str(specs)
        lines.append(f"Product {i}: {brand} {name} | Price: Rs {price} | Rating: {rating}/5 | Specs: {specs_str}")
    return "\n".join(lines)


async def _generate_product_response(
    user_message: str,
    conversation_context: str,
    product_details: str,
) -> Optional[str]:
    """Use LLM to generate a natural response about a previously shown product."""
    try:
        prompt = _RESPONSE_GENERATION_PROMPT.format(
            conversation_context=conversation_context,
            product_details=product_details,
            user_message=user_message,
        )
        messages = [
            {"role": "system", "content": "You are a knowledgeable e-commerce sales assistant."},
            {"role": "user", "content": prompt},
        ]
        response = _llm_gateway.call("response_generation", messages)
        return response
    except Exception as exc:
        plog.warning("  -> Response generation failed: %s", exc)
        return None


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
