from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.schemas import Message
from backend.services.keyword_service import KeywordService, parse_budget, detect_gender
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.recommendation_service import RecommendationService
from backend.services.llm_gateway import gateway as _llm_gateway
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


_RESPONSE_GENERATION_PROMPT = """\
You are a knowledgeable e-commerce sales assistant. Answer the user's question naturally and helpfully using the product details provided.

## Conversation History (last 5 turns)
{conversation_context}

## Product Details
{product_details}

## Current Question
{user_message}

Answer concisely and helpfully. Be specific about specifications, prices, and features. If the user asks about a specific product feature (battery life, camera, display, processor, etc.), provide exact details from the specs. Keep your response under 4 sentences unless more detail is specifically requested."""

_COMPARISON_PROMPT = """\
You are an expert e-commerce product comparison assistant.
Compare the following two products side-by-side based on the user's query: "{user_message}"

Product 1:
{prod1}

Product 2:
{prod2}

Return ONLY a valid JSON object with EXACTLY two fields:
1. "specs": A list of 3-6 objects comparing key features. Each object MUST have keys:
   - "feature": The name of the feature (e.g. "Display", "Processor", "Battery", "Material")
   - "val1": Product 1's value for this feature.
   - "val2": Product 2's value for this feature.
2. "overview": A concise markdown paragraph (3-4 sentences) summarizing the key differences and recommending which product is better for what type of user.

Ensure the output is raw JSON with no markdown formatting around it.
"""


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
        if len(history) >= 3:
            current_user_msg = history[-1]
            last_assistant_msg = history[-2]
            prev_user_msg = history[-3]
            if (
                current_user_msg.role == "user"
                and last_assistant_msg.role == "assistant"
                and last_assistant_msg.response_type == "NEEDS_CLARIFICATION"
                and prev_user_msg.role == "user"
            ):
                plog.info(
                    "  -> Clarification answer detected. Combining '%s' with previous query '%s'",
                    user_message,
                    prev_user_msg.content,
                )
                user_message = f"{prev_user_msg.content} {user_message}"

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
    # Rank ALL products so pagination order exactly matches top_products display order
    products = _recommendation_service.rank(products, query=user_message, budget=budget)
    top_products = products[:5]

    # Calculate highest local score
    max_score = max(p.get("_composite_score", 0.0) for p in top_products) if top_products else 0.0
    chroma_fallback = {"top": list(top_products), "all": list(products)}

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
                
        # Rank ALL scraped products so pagination order exactly matches top_products
        ranked_apify_products = _recommendation_service.rank(accepted_products, query=user_message, budget=budget)
        top_products = ranked_apify_products[:5]
        
        # Deduplicate and store all accepted scraped products in ChromaDB
        if accepted_products:
            new_products = []
            seen_in_batch = set()
            for p in accepted_products:
                pid = p.get("id") or p.get("product_url") or p.get("url")
                if not pid:
                    continue
                pid = str(pid).strip()
                if pid.startswith("http"):
                    pid = pid.split("?")[0].rstrip("/")
                if pid in seen_in_batch:
                    continue
                seen_in_batch.add(pid)

                is_duplicate = False
                try:
                    col = _vector_service.get_collection(p["category"])
                    existing = col.get(ids=[pid])
                    if existing and existing.get("ids"):
                         is_duplicate = True
                except Exception:
                    pass
                if not is_duplicate:
                    new_products.append(p)
            
            if new_products:
                plog.info("  -> Storing %d new crawled products in ChromaDB", len(new_products))
                await _vector_service.store_products(new_products, keywords=keywords)
                
        # If Apify returned too few products, fall back to ChromaDB results
        if not top_products or len(top_products) < 3:
            plog.info("  -> Apify returned only %d accepted products. Falling back to local ChromaDB results.", len(accepted_products))
            top_products = chroma_fallback["top"]
            products = chroma_fallback["all"]
            data_source = "local"
        else:
            # Map fields to match database schema expected by frontend for ALL products
            for p in ranked_apify_products:
                p["url"] = p.get("product_url") or p.get("url")
                p["image"] = p.get("image_url") or p.get("image")
            products = ranked_apify_products
            data_source = "live"
        run_background_discovery = True

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

    comparison = None
    if intent == "COMPARE" and len(top_products) >= 2:
        plog.info("  -> Generating side-by-side comparison for top 2 products")
        comparison = await _generate_comparison(top_products[:2], user_message)
        if comparison:
            plog.info("  -> Comparison generated successfully")

    return {
        "intent": intent,
        "products": top_products,
        "all_products": products,
        "keywords": keywords,
        "data_source": data_source,
        "detailed_intent": detailed_intent,
        "run_background_discovery": run_background_discovery,
        "generated_response": generated_response,
        "comparison": comparison,
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


async def _generate_comparison(products: List[Dict[str, Any]], user_message: str) -> Optional[Dict[str, Any]]:
    if len(products) < 2:
        return None
    p1 = products[0]
    p2 = products[1]
    try:
        import json
        prod1_str = f"Name: {p1.get('name')}\nPrice: {p1.get('price')}\nBrand: {p1.get('brand')}\nSpecs: {p1.get('specifications') or p1.get('specs')}"
        prod2_str = f"Name: {p2.get('name')}\nPrice: {p2.get('price')}\nBrand: {p2.get('brand')}\nSpecs: {p2.get('specifications') or p2.get('specs')}"
        
        prompt = _COMPARISON_PROMPT.format(user_message=user_message, prod1=prod1_str, prod2=prod2_str)
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant that outputs JSON."},
            {"role": "user", "content": prompt},
        ]
        response = _llm_gateway.call("comparison", messages)
        if response:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
                cleaned = cleaned.rsplit("```", 1)[0] if "```" in cleaned else cleaned
            
            parsed = json.loads(cleaned.strip())
            if "specs" in parsed and "overview" in parsed:
                # Add products back so the frontend has them for headers
                parsed["products"] = products[:2]
                return parsed
    except Exception as exc:
        plog.warning("  -> Comparison generation failed: %s", exc)

    # Local fallback if LLM is offline/rate-limited or call fails
    try:
        plog.info("  -> LLM comparison unavailable or failed. Generating local heuristic comparison.")
        specs_comparison = []
        # 1. Compare Price
        p1_price = p1.get('price')
        p2_price = p2.get('price')
        val1_price = f"Rs {p1_price:,.2f}" if isinstance(p1_price, (int, float)) else str(p1_price or 'N/A')
        val2_price = f"Rs {p2_price:,.2f}" if isinstance(p2_price, (int, float)) else str(p2_price or 'N/A')
        specs_comparison.append({
            "feature": "Price",
            "val1": val1_price,
            "val2": val2_price
        })
        # 2. Compare Brand
        specs_comparison.append({
            "feature": "Brand",
            "val1": str(p1.get('brand', 'Generic')),
            "val2": str(p2.get('brand', 'Generic'))
        })
        # 3. Compare Rating
        specs_comparison.append({
            "feature": "Rating",
            "val1": f"{p1.get('rating', 'N/A')}/5" if p1.get('rating') else 'N/A',
            "val2": f"{p2.get('rating', 'N/A')}/5" if p2.get('rating') else 'N/A'
        })
        
        # 4. Compare other specs from specifications dict
        s1 = p1.get('specifications') or p1.get('specs') or {}
        s2 = p2.get('specifications') or p2.get('specs') or {}
        if isinstance(s1, dict) and isinstance(s2, dict):
            all_keys = list(s1.keys())
            for k in s2.keys():
                if k not in all_keys:
                    all_keys.append(k)
            # Limit to top 6 specifications to keep it clean
            for k in all_keys[:6]:
                feature_name = k.replace("_", " ").title()
                specs_comparison.append({
                    "feature": feature_name,
                    "val1": str(s1.get(k, "N/A")),
                    "val2": str(s2.get(k, "N/A"))
                })
        
        # 5. Generate a helpful overview paragraph
        overview = f"Side-by-side comparison between **{p1.get('name')}** and **{p2.get('name')}**. "
        if isinstance(p1_price, (int, float)) and isinstance(p2_price, (int, float)):
            if p1_price == p2_price:
                overview += "Both products are priced identically. "
            else:
                diff = abs(p1_price - p2_price)
                cheaper = p1.get('name') if p1_price < p2_price else p2.get('name')
                overview += f"The **{cheaper}** is more budget-friendly, saving you Rs {diff:,.2f}. "
        if p1.get('rating') and p2.get('rating'):
            r1 = p1.get('rating')
            r2 = p2.get('rating')
            if r1 != r2:
                higher_rated = p1.get('name') if r1 > r2 else p2.get('name')
                overview += f"The **{higher_rated}** has a slightly higher user rating of {max(r1, r2)}/5 compared to {min(r1, r2)}/5. "
        overview += "Please review the specifications matrix above to choose the best option for your needs."
        
        return {
            "specs": specs_comparison,
            "overview": overview,
            "products": products[:2]
        }
    except Exception as exc:
        plog.error("  -> Local fallback comparison also failed: %s", exc)
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
