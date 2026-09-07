from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from backend.schemas import Message
from backend.services.keyword_service import KeywordService, parse_budget, detect_gender
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.recommendation_service import RecommendationService
from backend.services.clarification_service import determine_clarification, ClarificationNeed
from backend.services.llm_gateway import gateway as _llm_gateway
from backend.services.product_service import store_pagination, clear_pagination, enrich_product
from backend.services.pipeline_logger import get_pipeline_logger
from backend.services.spelling_service import SpellingService

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

_keyword_service = KeywordService()
_embedding_service = EmbeddingService()
_vector_service = VectorService(embedding_service=_embedding_service)
_recommendation_service = RecommendationService()
_spelling_service = SpellingService()

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
You are a precise e-commerce sales assistant that answers ONLY from provided product data.

## CRITICAL RULES — YOU MUST FOLLOW THESE:
- ONLY use information from the ## Product Details section below.
- NEVER invent prices, brands, specifications, ratings, or any product details.
- NEVER mention a specification, feature, or value that is not explicitly listed in Product Details.
- If the Product Details section is empty or contains no matching product, say: "I don't have product information for that query."
- If asked about a spec not listed in the Product Details, say: "That specification is not available in the product data."
- Do NOT make assumptions about product compatibility, availability, or performance.
- Keep your response under 4 sentences unless the user explicitly asks for more detail.
- Prefer direct answers. Do not ask follow-up questions unless the query is ambiguous.

## Conversation History (last 5 turns)
{conversation_context}

## Product Details (only use data from this section)
{product_details}

## Current Question
{user_message}

Answer using ONLY the product details above. Be concise."""

_COMPARISON_PROMPT = """\
You are a precise e-commerce product comparison assistant.

## CRITICAL RULES — YOU MUST FOLLOW THESE:
- ONLY use values explicitly present in Product A and Product B sections below.
- NEVER invent prices, brands, ratings, specifications, or any product details.
- If a specification or value is not listed for a product, use "N/A" for that product's value.
- Do NOT convert units, calculate percentages, perform math, or derive values.
- Do NOT add units or formatting that is not present in the source data.
- Include a feature ONLY if its value exists for BOTH products.
- Output raw JSON only. No markdown fences, no explanation, no conversational text.

## Request
{user_message}

## Product A
{prod1}

## Product B
{prod2}

## Output Format
Return valid JSON with EXACTLY these fields:

1. "specs": A list comparing features present in BOTH products' data.
   Each object: {{"feature": "Price", "val1": "Rs 79,999", "val2": "Rs 89,999"}}
   Include Price, Brand, Rating and any overlapping specifications.
   Make feature names human-readable (e.g., "Screen Size", "Battery Capacity").
   Values must be copied VERBATIM from the product data. Do not rephrase or reformat.

2. "overview": 2-4 sentences summarizing the key factual differences
   based ONLY on the specs above. Do not add external knowledge.

3. "strengths": {{
     "product_a": ["Lower price by Rs 10,000", "Higher rating 4.5 vs 4.2"],
     "product_b": ["Better processor", "More storage 256GB vs 128GB"]
   }}
   1-3 strengths per product, each drawn from a row in specs where that product wins.
   If tied in all categories, set both to empty lists.

4. "best_choice": "Product A" or "Product B" or "Depends on your needs"
   Base on overall spec comparison. If tied, say "Depends on your needs".
"""

_COMPARE_ENTITY_PROMPT = """\
Extract the TWO products the user wants to compare.
Strip price hints, sizes, and other modifiers — keep just the product name/type.
Return ONLY valid JSON: {{"product_a": "...", "product_b": "..."}}
Use null for either if you cannot identify it.

Examples:
"Compare iPhone 15 and Samsung Galaxy S24" -> {{"product_a": "iPhone 15", "product_b": "Samsung Galaxy S24"}}
"Nike vs Adidas running shoes" -> {{"product_a": "Nike", "product_b": "Adidas"}}
"difference between laptop A and laptop B" -> {{"product_a": "laptop A", "product_b": "laptop B"}}
"Compare these two" -> {{"product_a": null, "product_b": null}}

Query: {user_message}
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

    # Run spelling correction on the user query
    corrected_message = _spelling_service.correct_query(user_message)
    if corrected_message != user_message:
        plog.info("  -> Spelling corrected: '%s' -> '%s'", user_message, corrected_message)
        user_message = corrected_message

    # Format conversation context from history (last 5 user+assistant pairs)
    conversation_context = _format_conversation_context(history) if history else ""
    is_product_reference = _references_previous_product(user_message) if history else False
    recent_products = _get_recent_products(history) if is_product_reference else []

    if conversation_context:
        plog.info("  -> conversation context: %s", conversation_context[:100].replace("\n", " | "))
    if is_product_reference:
        plog.info("  -> detected product reference, recent products: %d", len(recent_products))

    clear_pagination(session_id, user_message)

    # STEP 1 & 2: Intent detection, Keyword generation, and Category classification in parallel with Embedding generation
    plog.info("STEP 1&2 -- Parallel Intent Classification & Embedding Generation")
    
    loop = asyncio.get_running_loop()
    intent_task = loop.run_in_executor(
        None,
        _keyword_service.extract_detailed_intent,
        user_message,
        conversation_context
    )
    embedding_task = loop.run_in_executor(
        None,
        _embedding_service.generate,
        user_message
    )
    
    detailed_intent, query_embedding = await asyncio.gather(intent_task, embedding_task)
    
    intent = detailed_intent.get("intent", "RECOMMEND")
    keywords = detailed_intent.get("keywords", [])
    predicted_category = detailed_intent.get("category", "other")

    # Check for LLM failure/offline status
    if not detailed_intent.get("llm_success", False):
        plog.warning("  -> LLM failed/offline. Falling back to local vector search using pre-computed query embedding.")
        
        if intent in ("GENERAL", "GREETING") and recent_products:
            intent = "FOLLOW_UP"
            detailed_intent["intent"] = "FOLLOW_UP"
            
        if intent in ("GREETING", "GENERAL"):
            return {
                "intent": intent,
                "products": [],
                "keywords": keywords,
                "data_source": "none",
                "detailed_intent": detailed_intent,
            }
            
        budget = parse_budget(user_message)
        gender = detect_gender(user_message)
        brand_pref = detailed_intent.get("brand_preference", [])
        if intent == "RECOMMEND" and gender is not None:
            detailed_intent["gender"] = gender

        # Clarification check in fallback mode (regex-detectable only: gender, budget)
        if intent == "RECOMMEND":
            need = determine_clarification(detailed_intent, user_message, is_llm_fallback=True)
            if need is not None:
                plog.info("  -> Fallback clarification needed: %s", need.question)
                return {
                    "intent": "NEEDS_CLARIFICATION",
                    "products": [],
                    "keywords": keywords,
                    "data_source": "none",
                    "detailed_intent": detailed_intent,
                    "clarification_question": need.question,
                    "clarification_options": need.options,
                    "run_background_discovery": False,
                }

        plog.info("  -> Primary category search: %s", predicted_category)
        results = await _vector_service.search_collection(
            predicted_category, 
            embedding=query_embedding, 
            n=50,
            budget=budget,
            gender=gender,
            brand_preference=brand_pref
        )
        
        if len(results) < 5:
            search_categories = CATEGORY_FALLBACK_MAP.get(predicted_category, ["other", "fashion", "electronics"])
            plog.info("  -> Fallback search categories: %s", search_categories)
            fallback_cats = [c for c in search_categories if c != predicted_category]
            if fallback_cats:
                fallback_results = await _vector_service.search_all_collections(
                    fallback_cats, 
                    embedding=query_embedding, 
                    n=50,
                    budget=budget,
                    gender=gender,
                    brand_preference=brand_pref
                )
                seen_ids = {p["id"] for p in results}
                for p in fallback_results:
                    if p["id"] not in seen_ids:
                        results.append(p)

        
        if not results:
            plog.info("  -> No results from fallback vector search")
            return {
                "intent": intent,
                "products": [],
                "keywords": keywords,
                "data_source": "local",
                "detailed_intent": detailed_intent,
                "run_background_discovery": False,
                "generated_response": "I couldn't find any products matching your query at the moment.",
            }
            
        plog.info("  -> Fallback vector search returned %d products", len(results))
        
        _apply_keyword_scores(results, keywords)
        results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        products = results
        
        products = _recommendation_service.rank(products, query=user_message, budget=budget, brand_preference=brand_pref)
        top_products = products[:5]
        
        if session_id:
            store_pagination(session_id, user_message, products)
            
        return {
            "intent": intent,
            "products": top_products,
            "all_products": products,
            "keywords": keywords,
            "data_source": "local",
            "detailed_intent": detailed_intent,
            "run_background_discovery": False,
            "generated_response": "I'm having trouble connecting to the online AI service, but I found these matching products from the local database.",
            "comparison": None,
        }

    # Happy path: LLM succeeded!
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

    # COMPARE: extract entities before vector search
    if intent == "COMPARE":
        item_a, item_b = await _extract_compare_entities(user_message)
        if item_a and item_b:
            plog.info("  -> COMPARE entities detected: '%s' vs '%s'", item_a, item_b)
            detailed_intent["_compare_entities"] = (item_a, item_b)
        else:
            plog.info("  -> COMPARE intent detected but no specific entities. Will use top-2 products.")

    # Generalized clarification check
    if intent == "RECOMMEND":
        need = determine_clarification(detailed_intent, user_message, is_llm_fallback=False)
        if need is not None:
            plog.info("  -> Clarification needed: %s", need.question)
            return {
                "intent": "NEEDS_CLARIFICATION",
                "products": [],
                "keywords": keywords,
                "data_source": "none",
                "detailed_intent": detailed_intent,
                "clarification_question": need.question,
                "clarification_options": need.options,
            }

    # STEP 3: Vector search on local ChromaDB using pre-computed query_embedding
    plog.info("STEP 3 -- Local Vector Search (category=%s)", predicted_category)
    
    gender = detailed_intent.get("gender")
    brand_pref = detailed_intent.get("brand_preference", [])
    budget = detailed_intent.get("budget") or parse_budget(user_message)
    
    plog.info("  -> Primary category search: %s", predicted_category)
    results = await _vector_service.search_collection(
        predicted_category, 
        embedding=query_embedding, 
        n=50,
        budget=budget,
        gender=gender,
        brand_preference=brand_pref
    )
    
    if len(results) < 5:
        search_categories = CATEGORY_FALLBACK_MAP.get(predicted_category, ["other", "fashion", "electronics"])
        plog.info("  -> Primary category returned fewer than 5 products. Fetching from fallbacks: %s", search_categories)
        fallback_cats = [c for c in search_categories if c != predicted_category]
        if fallback_cats:
            fallback_results = await _vector_service.search_all_collections(
                fallback_cats, 
                embedding=query_embedding, 
                n=50,
                budget=budget,
                gender=gender,
                brand_preference=brand_pref
            )
            seen_ids = {p["id"] for p in results}
            for p in fallback_results:
                if p["id"] not in seen_ids:
                    results.append(p)


    if not results:
        plog.info("  -> No results from vector search. Falling through to synchronous online search (0 < 5).")

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
    if budget is not None:
        plog.info("  -> Parsed budget constraint: Rs %.2f", budget)
    # Rank ALL products so pagination order exactly matches top_products display order
    products = _recommendation_service.rank(products, query=user_message, budget=budget, brand_preference=brand_pref)
    top_products = products[:5]

    total_local_count = len(products)
    max_score = max(p.get("_composite_score", 0.0) for p in top_products) if top_products else 0.0
    chroma_fallback = {"top": list(top_products), "all": list(products)}

    if total_local_count >= 10:
        plog.info(
            "  -> Found %d local products (>=10). Skipping online search.",
            total_local_count,
        )
        run_background_discovery = False
        data_source = "local"
        if max_score >= 0.70:
            plog.info("  -> Found highly relevant local product(s) (max score = %.4f). Returning instantly.", max_score)

    elif total_local_count < 5:
        plog.info(
            "  -> Only %d local products found (<5). Searching online synchronously.",
            total_local_count,
        )
        from backend.services.apify_service import ApifyService
        from backend.services.discovery_task import calculate_relevance_score

        apify_service = ApifyService()
        raw_products = []
        try:
            raw_products = await apify_service.discover_products(detailed_intent)
        except Exception as e:
            plog.error("  -> Synchronous Apify discovery failed: %s", str(e))

        # Score and validate scraped products using the pre-computed query embedding
        # query_embedding is already computed and available
        accepted_products = []
        for p in raw_products:
            score = calculate_relevance_score(p, detailed_intent, query_embedding)
            p["_score"] = score
            if score >= 0.6:
                accepted_products.append(p)

        # Rank ALL scraped products so pagination order exactly matches top_products
        ranked_apify_products = _recommendation_service.rank(accepted_products, query=user_message, budget=budget, brand_preference=brand_pref)
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
        run_background_discovery = False

    else:
        plog.info(
            "  -> Found %d local products (5-9). Using local only. User can load more for online results.",
            total_local_count,
        )
        run_background_discovery = False
        data_source = "local"

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
    compare_entities = detailed_intent.get("_compare_entities")

    if intent == "COMPARE" and compare_entities and compare_entities[0] and compare_entities[1]:
        item_a, item_b = compare_entities
        plog.info("  -> Retrieving specific comparison entities: '%s' vs '%s'", item_a, item_b)
        prod_a, prod_b = await _retrieve_compare_products(
            item_a, item_b, predicted_category, query_embedding,
        )
        if prod_a and prod_b:
            comparison = await _generate_comparison([prod_a, prod_b], user_message)
            if comparison:
                plog.info("  -> Entity-based comparison generated successfully")
        elif prod_a or prod_b:
            found = prod_a or prod_b
            fallback = top_products[0] if top_products else None
            if fallback and found.get("id") != fallback.get("id"):
                pair = [found, fallback]
                comparison = await _generate_comparison(pair, user_message)
                if comparison:
                    comparison["note"] = "Only one of the requested products was found."
                    plog.info("  -> Partial comparison generated")

    if not comparison and intent == "COMPARE" and len(top_products) >= 2:
        plog.info("  -> Generating comparison from top-2 ranked products")
        comparison = await _generate_comparison(top_products[:2], user_message)
        if comparison:
            plog.info("  -> Comparison generated successfully")

    # FOLLOW_UP + COMPARE: user says "compare these two" after seeing products
    if not comparison and intent == "FOLLOW_UP" and _references_comparison(user_message) and len(recent_products) >= 2:
        plog.info("  -> FOLLOW_UP with comparison request — using recent products")
        comparison = await _generate_comparison(recent_products[:2], user_message)

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
            {"role": "system", "content": "You are a precise e-commerce sales assistant. You answer ONLY from provided product data. NEVER invent prices, brands, specifications, or any details not present in the product data. If data is missing, state that it is not available."},
            {"role": "user", "content": prompt},
        ]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _llm_gateway.call, "response_generation", messages)
        return response
    except Exception as exc:
        plog.warning("  -> Response generation failed: %s", exc)
        return None


async def _extract_compare_entities(user_message: str) -> tuple:
    """Extract two product entities from a comparison query using LLM then regex fallback."""
    try:
        prompt = _COMPARE_ENTITY_PROMPT.format(user_message=user_message)
        messages = [
            {"role": "system", "content": "You extract product names from comparison queries. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _llm_gateway.call, "compare_extraction", messages)
        if raw:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
                cleaned = cleaned.rsplit("```", 1)[0] if "```" in cleaned else cleaned
            parsed = json.loads(cleaned.strip())
            a = parsed.get("product_a")
            b = parsed.get("product_b")
            if a and b:
                return a.strip(), b.strip()
    except Exception as exc:
        plog.warning("  -> LLM entity extraction failed: %s", exc)

    return _extract_compare_entities_fallback(user_message)


def _extract_compare_entities_fallback(user_message: str) -> tuple:
    """Regex-based fallback for extracting two products from comparison query."""
    low = user_message.lower()

    m = re.search(r'\bcompare\s+(.+?)\s+(?:and|with|&)\s+(.+)', low)
    if m:
        return _clean_entity(m.group(1)), _clean_entity(m.group(2))

    m = re.search(r'\bdifference\s+between\s+(.+?)\s+and\s+(.+)', low)
    if m:
        return _clean_entity(m.group(1)), _clean_entity(m.group(2))

    m = re.search(r'(.+?)\s+(?:vs?\.?|versus)\s+(.+)', low)
    if m:
        return _clean_entity(m.group(1)), _clean_entity(m.group(2))

    return None, None


def _clean_entity(entity: str) -> str:
    entity = entity.strip().strip('"').strip("'")
    stop_phrases = [
        " under ", " below ", " within ", " around ", " budget ",
        " under rs", " under ₹", " price ", " for me", " please",
    ]
    low = entity.lower()
    for phrase in stop_phrases:
        idx = low.find(phrase)
        if idx > 0:
            entity = entity[:idx].strip()
            low = entity.lower()
    return entity if len(entity) > 1 else None


def _name_match_score(product_name: str, query_item: str) -> float:
    pn = (product_name or "").lower()
    qi = (query_item or "").lower().strip()
    if not pn or not qi:
        return 0.0
    if qi in pn or pn in qi:
        return 1.0
    pn_words = set(re.findall(r'[a-z0-9]+', pn))
    qi_words = set(re.findall(r'[a-z0-9]+', qi))
    if not qi_words:
        return 0.0
    if all(w in pn for w in qi_words):
        return 0.95
    overlap = pn_words & qi_words
    return round(len(overlap) / len(qi_words), 2)


async def _retrieve_compare_products(
    item_a: str,
    item_b: str,
    predicted_category: str,
    query_embedding: list,
) -> tuple:
    """Search for each named product across categories using text query and return best matches."""
    all_categories = list(CATEGORY_FALLBACK_MAP.keys())

    async def _find_best(item: str) -> Optional[Dict]:
        best = None
        best_score = 0.0

        for category in all_categories:
            try:
                results = await _vector_service.search_collection(
                    category,
                    embedding=None,
                    query=item,
                    n=10,
                    budget=None,
                    gender=None,
                    brand_preference=None,
                )
            except Exception:
                continue

            for p in results:
                name = p.get("name", "")
                brand = p.get("brand", "")
                combined = f"{brand} {name}"
                score = _name_match_score(combined, item)
                if score > best_score:
                    best_score = score
                    best = p

        if best and best_score >= 0.5:
            return best
        return None

    prod_a, prod_b = await asyncio.gather(_find_best(item_a), _find_best(item_b))
    return prod_a, prod_b


def _all_product_values(p: Dict) -> set:
    """Collect all known string values from a product dict for hallucination checking."""
    vals = set()
    for key in ("name", "brand", "category", "description"):
        v = p.get(key)
        if v:
            vals.add(str(v).lower())
    price = p.get("price")
    if isinstance(price, (int, float)):
        vals.add(f"rs {price:,.2f}")
        vals.add(f"rs{price:,.2f}")
        vals.add(str(price))
    rating = p.get("rating")
    if rating:
        vals.add(f"{rating}/5")
        vals.add(str(rating))
    specs = p.get("specifications") or p.get("specs") or {}
    if isinstance(specs, dict):
        for k, v in specs.items():
            vals.add(str(v).lower())
            vals.add(f"{k}: {v}".lower())
    return vals


def _validate_comparison_specs(parsed: Dict, p1: Dict, p2: Dict) -> bool:
    """Check every spec value exists in source product data to prevent hallucination."""
    p1_vals = _all_product_values(p1)
    p2_vals = _all_product_values(p2)

    def _clean(text: str) -> str:
        return text.lower().replace("rs ", "rs").replace("rs.", "rs").replace(",", "").replace(".00", "").strip()

    p1_clean = {_clean(v) for v in p1_vals}
    p2_clean = {_clean(v) for v in p2_vals}

    def _check(val: str, raw_set: set, clean_set: set) -> bool:
        val_low = val.lower().strip()
        if val_low in ("n/a", "none", "null", ""):
            return True
        if any(val_low in rv for rv in raw_set):
            return True
        val_clean = _clean(val_low)
        if val_clean in clean_set:
            return True
        if any(val_clean in cv for cv in clean_set):
            return True
        return False

    for spec in parsed.get("specs", []):
        if not _check(spec.get("val1", ""), p1_vals, p1_clean):
            plog.warning("  -> Hallucination detected: val1 '%s' not found in product 1 data", spec.get("val1"))
            return False
        if not _check(spec.get("val2", ""), p2_vals, p2_clean):
            plog.warning("  -> Hallucination detected: val2 '%s' not found in product 2 data", spec.get("val2"))
            return False
    return True


async def _generate_comparison(products: List[Dict[str, Any]], user_message: str) -> Optional[Dict[str, Any]]:
    if len(products) < 2:
        return None
    p1 = products[0]
    p2 = products[1]

    try:

        def _fmt(p: Dict) -> str:
            lines = [f"Name: {p.get('name', 'N/A')}"]
            if p.get("brand"):
                lines.append(f"Brand: {p['brand']}")
            if p.get("category"):
                lines.append(f"Category: {p['category']}")
            price = p.get("price")
            lines.append(f"Price: Rs {price:,.2f}" if isinstance(price, (int, float)) else "Price: N/A")
            mrp = p.get("mrp")
            if mrp:
                lines.append(f"MRP: Rs {mrp:,.2f}" if isinstance(mrp, (int, float)) else f"MRP: {mrp}")
            discount = p.get("discount")
            if discount:
                lines.append(f"Discount: {discount}%")
            rating = p.get("rating")
            lines.append(f"Rating: {rating}/5" if rating else "Rating: N/A")
            desc = p.get("description")
            if desc:
                lines.append(f"Description: {desc[:200]}")
            specs = p.get("specifications") or p.get("specs") or {}
            if specs and isinstance(specs, dict):
                lines.append("Specifications:")
                for k, v in specs.items():
                    lines.append(f"  - {k}: {v}")
            return "\n".join(lines)

        prod1_str = _fmt(p1)
        prod2_str = _fmt(p2)

        prompt = _COMPARISON_PROMPT.format(user_message=user_message, prod1=prod1_str, prod2=prod2_str)
        messages = [
            {"role": "system", "content": "You are a precise JSON generator. You output ONLY valid JSON based on provided data. NEVER invent or extrapolate data. Use null for missing values."},
            {"role": "user", "content": prompt},
        ]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _llm_gateway.call, "comparison", messages)
        if response:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
                cleaned = cleaned.rsplit("```", 1)[0] if "```" in cleaned else cleaned

            parsed = json.loads(cleaned.strip())
            if "specs" in parsed and "overview" in parsed:
                if _validate_comparison_specs(parsed, p1, p2):
                    parsed["products"] = products[:2]
                    return parsed
                plog.warning("  -> LLM comparison failed hallucination validation. Falling back to local.")
    except Exception as exc:
        plog.warning("  -> LLM comparison generation failed: %s", exc)

    return _local_comparison(p1, p2)


def _local_comparison(p1: Dict, p2: Dict) -> Dict:
    """Local heuristic comparison when LLM is unavailable."""
    plog.info("  -> Generating local heuristic comparison.")
    specs = []
    wins_a = 0
    wins_b = 0

    def add_spec(feature: str, val1, val2, winner: Optional[str] = None):
        specs.append({
            "feature": feature,
            "val1": str(val1) if val1 is not None else "N/A",
            "val2": str(val2) if val2 is not None else "N/A",
            "_winner": winner,
        })
        nonlocal wins_a, wins_b
        if winner == "a":
            wins_a += 1
        elif winner == "b":
            wins_b += 1

    p1_price = p1.get("price")
    p2_price = p2.get("price")
    if isinstance(p1_price, (int, float)) and isinstance(p2_price, (int, float)):
        def fmt_price(v):
            return f"Rs {v:,.2f}"
        if p1_price < p2_price:
            add_spec("Price", fmt_price(p1_price), fmt_price(p2_price), "a")
        elif p2_price < p1_price:
            add_spec("Price", fmt_price(p1_price), fmt_price(p2_price), "b")
        else:
            add_spec("Price", fmt_price(p1_price), fmt_price(p2_price))
    else:
        add_spec("Price", p1_price or "N/A", p2_price or "N/A")

    add_spec("Brand", p1.get("brand", "N/A"), p2.get("brand", "N/A"))

    r1 = p1.get("rating")
    r2 = p2.get("rating")
    if isinstance(r1, (int, float)) and isinstance(r2, (int, float)):
        if r1 > r2:
            add_spec("Rating", f"{r1}/5", f"{r2}/5", "a")
        elif r2 > r1:
            add_spec("Rating", f"{r1}/5", f"{r2}/5", "b")
        else:
            add_spec("Rating", f"{r1}/5", f"{r2}/5")
    else:
        add_spec("Rating", f"{r1}/5" if r1 else "N/A", f"{r2}/5" if r2 else "N/A")

    s1 = p1.get("specifications") or p1.get("specs") or {}
    s2 = p2.get("specifications") or p2.get("specs") or {}
    if isinstance(s1, dict) and isinstance(s2, dict):
        common_keys = [k for k in s1 if k in s2]
        for k in common_keys[:8]:
            v1, v2 = str(s1[k]), str(s2[k])
            feature_name = k.replace("_", " ").title()
            winner = None
            if v1 != v2:
                n1 = _try_float(v1)
                n2 = _try_float(v2)
                if n1 is not None and n2 is not None:
                    higher_is_better = not any(w in k.lower() for w in ["price", "cost", "weight"])
                    winner = "a" if (n1 > n2) == higher_is_better else "b"
            add_spec(feature_name, v1, v2, winner)

    strengths_a = _build_strengths(p1, specs, "a")
    strengths_b = _build_strengths(p2, specs, "b")

    p1_name = p1.get("name", "Product A")
    p2_name = p2.get("name", "Product B")
    if wins_a > wins_b:
        best_choice = "Product A"
        overview = f"**{p1_name}** is the better choice overall, winning {wins_a} vs {wins_b} key comparisons. "
    elif wins_b > wins_a:
        best_choice = "Product B"
        overview = f"**{p2_name}** is the better choice overall, winning {wins_b} vs {wins_a} key comparisons. "
    else:
        best_choice = "Depends on your needs"
        overview = f"Both **{p1_name}** and **{p2_name}** are evenly matched. "

    if isinstance(p1_price, (int, float)) and isinstance(p2_price, (int, float)):
        if p1_price < p2_price:
            overview += f"**{p1_name}** is more affordable at Rs {p1_price:,.2f} vs Rs {p2_price:,.2f}. "
        elif p2_price < p1_price:
            overview += f"**{p2_name}** is more affordable at Rs {p2_price:,.2f} vs Rs {p1_price:,.2f}. "

    if isinstance(r1, (int, float)) and isinstance(r2, (int, float)) and r1 != r2:
        higher = p1_name if r1 > r2 else p2_name
        overview += f"**{higher}** has a better rating ({max(r1, r2)}/5 vs {min(r1, r2)}/5)."

    if not overview.endswith("."):
        overview += " Review the specs table above for details."

    return {
        "specs": specs,
        "overview": overview,
        "strengths": {"product_a": strengths_a, "product_b": strengths_b},
        "best_choice": best_choice,
        "products": [p1, p2],
    }


def _try_float(v: str) -> Optional[float]:
    try:
        return float(re.sub(r'[^\d.]', '', v))
    except (ValueError, TypeError):
        return None


def _build_strengths(product: Dict, specs: List[Dict], side: str) -> List[str]:
    strengths = []
    for s in specs:
        winner = s.get("_winner")
        val = s.get(f"val{1 if side == 'a' else 2}")
        other_val = s.get(f"val{2 if side == 'a' else 1}")
        if winner == side:
            strengths.append(f"Better {s['feature'].lower()}: {val} vs {other_val}")
        elif not winner and val and val != "N/A" and val != other_val:
            strengths.append(f"{s['feature']}: {val}")
    return strengths[:3]


def _references_comparison(message: str) -> bool:
    """Check if user message is asking to compare shown products."""
    low = message.lower()
    patterns = [
        r'\bcompare\b',
        r'\bversus\b',
        r'\bvs\b',
        r'\bdifference\b',
    ]
    return any(re.search(p, low) for p in patterns)


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
        combined_primary = f"{name} {brand}"

        description = (p.get("description", "") or "").lower()
        specs = p.get("specifications") or p.get("specs") or {}
        specs_list = []
        if isinstance(specs, dict):
            for k, v in specs.items():
                specs_list.append(f"{k} {v}")
        specs_text = " ".join(specs_list).lower()
        combined_secondary = f"{description} {specs_text}"

        primary_matched = sum(1 for term in significant_terms if term in combined_primary)
        secondary_matched = sum(1 for term in significant_terms if term in combined_secondary)

        matched_count = primary_matched + (0.35 * min(secondary_matched, len(significant_terms) - primary_matched))
        ratio = matched_count / len(significant_terms)
        kw_score = round(min(0.7 * ratio, 1.0), 4)

        vec_score = p.get("_score", 0.0) or 0.0
        p["_score"] = round(0.5 * vec_score + 0.5 * kw_score, 4)

