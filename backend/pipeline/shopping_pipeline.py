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
from backend.services.jina_reranker import JinaReranker
from backend.settings import settings

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

_keyword_service = KeywordService()
_embedding_service = EmbeddingService()
_vector_service = VectorService(embedding_service=_embedding_service)
_recommendation_service = RecommendationService()
_spelling_service = SpellingService()
_jina_reranker = JinaReranker(embedding_service=_embedding_service)

CATEGORY_FALLBACK_MAP = {
    "smartphones": ["smartphones", "electronics", "other"],
    "laptops": ["laptops", "electronics", "other"],
    "fashion": ["fashion", "footwear", "other"],
    "beauty": ["beauty", "fashion", "other"],
    "footwear": ["footwear", "fashion", "other"],
    "home_appliances": ["home_appliances", "electronics", "other"],
    "electronics": ["electronics", "smartphones", "laptops", "other"],
    "other": ["other", "fashion", "footwear"],
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

_GENERAL_QUERY_PROMPT = """\
You are an e-commerce assistant that answers questions about the store's product catalog.

## CRITICAL RULES:
- ONLY use information from the ## Product Catalog section below.
- NEVER invent prices, brands, specifications, ratings, or any product details.
- If the catalog data doesn't contain enough information to answer, say: "I don't have enough product data to answer that question."
- Keep your response under 3 sentences unless the user asks for more detail.
- Be helpful and conversational. Mention specific product names, prices, and brands when relevant.

## Product Catalog
{product_catalog}

## Current Question
{user_message}

Answer the question using ONLY the product catalog above. Be concise and helpful."""

_EXPLAIN_PRODUCT_PROMPT = """\
You are an e-commerce product expert. Answer questions about a specific product using the provided details.

## CRITICAL RULES:
- ONLY use information from the ## Product Details section below.
- NEVER invent prices, brands, specifications, ratings, or any product details.
- If a specification is not listed, say: "That specification is not available in our data."
- Be helpful and conversational. Mention specific specs, features, and values when relevant.
- Keep your response under 4 sentences unless the user asks for more detail.

## Product Details
{product_details}

## User Question
{user_message}

Answer the question using ONLY the product details above. Be helpful and specific."""

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
            if intent == "GREETING":
                return {
                    "intent": intent,
                    "products": [],
                    "keywords": keywords,
                    "data_source": "none",
                    "detailed_intent": detailed_intent,
                }
            # GENERAL in fallback mode: parse query and fetch products (no LLM response)
            parsed_query = _parse_general_query(user_message)
            general_products = await _fetch_general_query_products(parsed_query)
            return {
                "intent": intent,
                "products": general_products[:5] if general_products else [],
                "all_products": general_products,
                "keywords": keywords,
                "data_source": "local",
                "detailed_intent": detailed_intent,
                "run_background_discovery": False,
                "generated_response": "Here are the results based on your query.",
                "comparison": None,
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
                    if p["id"] not in seen_ids and p.get("_score", 0) > 0.3:
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

        if settings.JINA_RERANK_ENABLED and results:
            plog.info("  -> Jina Reranker (fallback path)")
            results = await _jina_reranker.rerank(query=user_message, products=results)
            alpha = settings.JINA_RERANK_ALPHA
            for p in results:
                jina_s = p.get("_jina_score", 0.0)
                existing_s = p.get("_score", 0.0)
                p["_score"] = round(alpha * jina_s + (1 - alpha) * existing_s, 4)

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
        if intent == "GREETING":
            plog.info("  -> GREETING intent — returning empty pipeline")
            return {
                "intent": intent,
                "products": [],
                "keywords": keywords,
                "data_source": "none",
                "detailed_intent": detailed_intent,
            }

        # GENERAL: parse query, fetch products, generate LLM response
        plog.info("  -> GENERAL intent — parsing catalog query")
        parsed_query = _parse_general_query(user_message)
        plog.info("  -> Parsed query: metric=%s, direction=%s, category=%s",
                   parsed_query["metric"], parsed_query["direction"], parsed_query["category"])

        general_products = await _fetch_general_query_products(parsed_query)
        plog.info("  -> Fetched %d products for general query", len(general_products))

        generated_response = await _generate_general_response(
            user_message, general_products, parsed_query
        )
        plog.info("  -> Generated general response: %s", (generated_response or "")[:100])

        return {
            "intent": intent,
            "products": general_products[:5] if general_products else [],
            "all_products": general_products,
            "keywords": keywords,
            "data_source": "local",
            "detailed_intent": detailed_intent,
            "run_background_discovery": False,
            "generated_response": generated_response,
            "comparison": None,
        }

    # EXPLAIN: answer product-specific questions
    if intent == "EXPLAIN":
        plog.info("  -> EXPLAIN intent — parsing product question")
        product_name = _parse_product_name(user_message)
        if product_name:
            plog.info("  -> Extracted product name: '%s'", product_name)
            explain_products = await _fetch_product_by_name(product_name)
            plog.info("  -> Fetched %d products for explain query", len(explain_products))

            generated_response = await _generate_explain_response(
                user_message, explain_products
            )
            plog.info("  -> Generated explain response: %s", (generated_response or "")[:100])

            return {
                "intent": intent,
                "products": explain_products[:3] if explain_products else [],
                "all_products": explain_products,
                "keywords": keywords,
                "data_source": "local",
                "detailed_intent": detailed_intent,
                "run_background_discovery": False,
                "generated_response": generated_response,
                "comparison": None,
            }
        else:
            plog.info("  -> EXPLAIN intent but no product name extracted. Falling through to vector search.")

    # COMPARE: extract entities before vector search
    if intent == "COMPARE":
        item_a, item_b = await _extract_compare_entities(user_message)
        if item_a and item_b:
            plog.info("  -> COMPARE entities detected: '%s' vs '%s'", item_a, item_b)
            detailed_intent["_compare_entities"] = (item_a, item_b)
        else:
            plog.info("  -> COMPARE intent detected but no specific entities. Will use top-2 products.")

    # SPECIAL HANDLING FOR COMPARE INTENT: Skip vector search, use recent products
    if intent == "COMPARE":
        plog.info("  -> COMPARE intent detected — skipping vector search, matching from recent products")
        
        # Get comparison entities from LLM extraction
        compare_entities = detailed_intent.get("_compare_entities")
        comparison_products = None
        
        if compare_entities and compare_entities[0] and compare_entities[1]:
            item_a, item_b = compare_entities
            plog.info("  -> Matching extracted entities against recent products: '%s' vs '%s'", item_a, item_b)
            
            # Try to match against recent products using fuzzy name matching
            if recent_products and len(recent_products) >= 2:
                from difflib import SequenceMatcher
                
                def _match_product_in_recent(target_name: str, candidates: list) -> dict | None:
                    best_match = None
                    best_score = 0.0
                    for cand in candidates:
                        cand_name = f"{cand.get('brand', '')} {cand.get('name', '')}".strip()
                        score = SequenceMatcher(None, target_name.lower(), cand_name.lower()).ratio()
                        if score > best_score:
                            best_score = score
                            best_match = cand
                    # Threshold of 0.3 for fuzzy matching
                    return best_match if best_score >= 0.3 else None
                
                prod_a = _match_product_in_recent(item_a, recent_products)
                prod_b = _match_product_in_recent(item_b, recent_products)
                
                if prod_a and prod_b:
                    comparison_products = [prod_a, prod_b]
                    plog.info("  -> Matched both products from recent products (score >= 0.3)")
                elif prod_a or prod_b:
                    plog.info("  -> Matched only one product from recent products, will try DB fallback")
        
        # If not matched from recent products, try DB lookup
        if not comparison_products and compare_entities and compare_entities[0] and compare_entities[1]:
            item_a, item_b = compare_entities
            plog.info("  -> Falling back to DB lookup for: '%s' vs '%s'", item_a, item_b)
            prod_a, prod_b = await _retrieve_compare_products(
                item_a, item_b, predicted_category, query_embedding,
            )
            if prod_a and prod_b:
                comparison_products = [prod_a, prod_b]
                plog.info("  -> Both products found via DB lookup")
            elif prod_a or prod_b:
                # Use found product + first recent product as fallback
                found = prod_a or prod_b
                fallback = recent_products[0] if recent_products else None
                if fallback and found.get("id") != fallback.get("id"):
                    comparison_products = [found, fallback]
                    plog.info("  -> Partial match: using found product + recent fallback")
        
        # If still no comparison products, use top 2 recent products
        if not comparison_products and recent_products and len(recent_products) >= 2:
            comparison_products = recent_products[:2]
            plog.info("  -> Using top 2 recent products for comparison")
        
        # Generate comparison if we have products
        if comparison_products and len(comparison_products) >= 2:
            comparison = await _generate_comparison(comparison_products[:2], user_message)
            if comparison:
                plog.info("  -> Comparison generated successfully for COMPARE intent")
                # Return early with empty products to prevent showing product cards
                return {
                    "intent": intent,
                    "products": [],
                    "all_products": [],
                    "keywords": keywords,
                    "data_source": "local",
                    "detailed_intent": detailed_intent,
                    "run_background_discovery": False,
                    "generated_response": None,
                    "comparison": comparison,
                }
        
        # If we couldn't generate comparison, fall through to normal flow but with empty products
        plog.warning("  -> Could not generate comparison for COMPARE intent")
        return {
            "intent": intent,
            "products": [],
            "all_products": [],
            "keywords": keywords,
            "data_source": "local",
            "detailed_intent": detailed_intent,
            "run_background_discovery": False,
            "generated_response": None,
            "comparison": None,
        }

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
                if p["id"] not in seen_ids and p.get("_score", 0) > 0.3:
                    results.append(p)


        if not results:
            plog.info("  -> No results from vector search across all collections")
            return {
                "intent": intent,
                "products": [],
                "keywords": keywords,
                "data_source": "local",
                "detailed_intent": detailed_intent,
                "run_background_discovery": False,
                "generated_response": (
                    "Sorry, we don't currently have this product in our catalog. "
                    "Here's what we offer: Smartphones, Laptops, Clothing, Shoes, Beauty, and Electronics. "
                    "Would you like to explore any of these categories?"
                ),
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

    # STEP 4.5: Jina Reranker (optional)
    if settings.JINA_RERANK_ENABLED and products:
        plog.info("STEP 4.5 -- Jina Reranker v3")
        products = await _jina_reranker.rerank(query=user_message, products=products)
        alpha = settings.JINA_RERANK_ALPHA
        for p in products:
            jina_s = p.get("_jina_score", 0.0)
            existing_s = p.get("_score", 0.0)
            p["_score"] = round(alpha * jina_s + (1 - alpha) * existing_s, 4)
        plog.info("  -> After Jina blend, top score: %.4f", products[0].get("_score", 0.0) if products else 0.0)

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


# ---------------------------------------------------------------------------
# GENERAL query helpers — answer catalog questions like "most expensive product"
# ---------------------------------------------------------------------------

# Category keyword mapping for natural language queries
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "smartphones": ["phone", "smartphone", "mobile", "iphone", "android"],
    "laptops": ["laptop", "notebook", "macbook", "computer"],
    "fashion": ["clothes", "clothing", "shirt", "tshirt", "dress", "jeans", "pants", "jacket", "hoodie", "sweater", "kurti", "saree", "lehenga", "shorts", "trousers"],
    "footwear": ["shoe", "shoes", "sneaker", "sneakers", "boots", "sandals", "slippers", "footwear"],
    "beauty": ["makeup", "cosmetics", "skincare", "perfume", "lipstick", "foundation", "moisturizer", "sunscreen", "beauty"],
    "electronics": ["headphones", "earphones", "earbuds", "watch", "smartwatch", "speaker", "camera", "gadget", "electronics", "accessories"],
    "home_appliances": ["fan", "AC", "refrigerator", "washing machine", "microwave", "home appliance"],
}

# Metric keyword mapping
_METRIC_KEYWORDS: Dict[str, List[str]] = {
    "price": ["price", "expensive", "cost", "costly", "cheap", "cheapest", "budget", "rupee", "rs", "₹", "affordable"],
    "rating": ["rating", "rated", "review", "best rated", "top rated", "stars", "highest rated"],
    "discount": ["discount", "off", "sale", "deal", "offer", "percentage off"],
}

# Direction keyword mapping
_DIRECTION_KEYWORDS: Dict[str, List[str]] = {
    "max": ["most", "highest", "top", "best", "expensive", "priciest", "costliest", "maximum"],
    "min": ["least", "lowest", "cheapest", "budget", "affordable", "minimum", "cheapest"],
    "count": ["how many", "count", "number", "total", "many"],
    "list": ["list", "show", "all", "every", "each", "which", "what are"],
    "exists": ["do you have", "do you sell", "is there", "available", "stock"],
}


def _parse_general_query(user_message: str) -> Dict[str, Any]:
    """Parse a GENERAL query to extract metric, direction, and category.

    Handles questions like:
    - "What is the most expensive product?" → price, max, all categories
    - "What is the cheapest laptop?" → price, min, laptops
    - "How many products do you have?" → count, count, all
    - "Do you sell headphones?" → exists, exists, electronics
    - "What are the best rated phones?" → rating, max, smartphones
    - "Show me all watches" → list, list, electronics
    """
    low = user_message.lower()

    # Detect category first (most specific match)
    category = None
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # Use word boundary matching for short keywords to avoid false positives
            if len(kw) <= 3:
                if re.search(r'\b' + re.escape(kw) + r'\b', low):
                    category = cat
                    break
            else:
                if kw in low:
                    category = cat
                    break
        if category:
            break

    # Detect direction FIRST (more specific patterns override defaults)
    direction = "list"  # default
    metric = "price"  # default

    # --- Direction detection (order matters: most specific first) ---

    # Count queries
    if re.search(r'\b(how many|count|number of|total|total number)\b', low):
        metric = "count"
        direction = "count"

    # Existence queries
    elif re.search(r'\b(do you (have|sell|stock|carry|offer)|is there|are there|available|in stock)\b', low):
        metric = "exists"
        direction = "exists"

    # Max queries: "most expensive", "highest rated", "best", "top"
    elif re.search(r'\b(most|highest|top|best|maximum|max|priciest|costliest)\b', low):
        direction = "max"

    # Min queries: "cheapest", "lowest", "least", "budget", "affordable"
    elif re.search(r'\b(cheapest|lowest|least|budget|affordable|minimum|min|lowest priced)\b', low):
        direction = "min"

    # List queries: "show me", "list", "all", "what are"
    elif re.search(r'\b(show|list|all|every|each|what are|which|display)\b', low):
        direction = "list"

    # --- Metric detection (based on keywords present) ---

    # Price-related
    if re.search(r'\b(price|expensive|cost|costly|cheap|cheapest|budget|rupee|rs\.?|₹|affordable|priced|pricing)\b', low):
        metric = "price"

    # Rating-related
    elif re.search(r'\b(rating|rated|review|stars|best rated|top rated|highest rated|quality)\b', low):
        metric = "rating"

    # Discount-related
    elif re.search(r'\b(discount|off|sale|deal|offer|percentage|cashback)\b', low):
        metric = "discount"

    # Override for expensive/cheap (always price + max/min)
    if re.search(r'\b(expensive|costly|priciest|costliest|high priced|premium)\b', low):
        metric = "price"
        direction = "max"
    elif re.search(r'\b(cheap|cheapest|affordable|budget|low priced|less expensive)\b', low):
        metric = "price"
        direction = "min"

    return {
        "metric": metric,
        "direction": direction,
        "category": category,
    }


async def _fetch_general_query_products(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch products from the database based on parsed query intent.

    Uses get_all_products() to fetch ALL products without vector similarity,
    then sorts/filters in Python for accurate results.
    """
    metric = parsed.get("metric", "price")
    direction = parsed.get("direction", "list")
    category = parsed.get("category")

    # For count queries, fetch ALL products from each category
    if metric == "count" or direction == "count":
        all_products = []
        categories = list(_CATEGORY_KEYWORDS.keys())
        for cat in categories:
            try:
                results = await _vector_service.get_all_products(cat, limit=1000)
                all_products.extend(results)
            except Exception:
                pass
        return all_products

    if direction == "exists":
        # Fetch ALL products from the suspected category (or first 3)
        cats_to_search = [category] if category else list(_CATEGORY_KEYWORDS.keys())[:3]
        all_products = []
        for cat in cats_to_search:
            try:
                results = await _vector_service.get_all_products(cat, limit=1000)
                all_products.extend(results)
            except Exception:
                pass
        return all_products

    # For price/rating/discount queries, fetch ALL products from relevant categories
    cats_to_search = [category] if category else list(_CATEGORY_KEYWORDS.keys())
    all_products = []
    for cat in cats_to_search:
        try:
            results = await _vector_service.get_all_products(cat, limit=1000)
            all_products.extend(results)
        except Exception:
            pass

    if not all_products:
        return []

    # Sort by the relevant metric
    if metric == "price":
        all_products.sort(key=lambda p: p.get("price") or 0, reverse=(direction == "max"))
    elif metric == "rating":
        all_products.sort(key=lambda p: p.get("rating") or 0, reverse=(direction == "max"))
    elif metric == "discount":
        all_products.sort(key=lambda p: p.get("discount") or 0, reverse=(direction == "max"))

    # Return top result for max/min, or top 5 for list
    if direction in ("max", "min"):
        return all_products[:1]
    return all_products[:5]


def _format_catalog_for_general(products: List[Dict[str, Any]], parsed: Dict[str, Any]) -> str:
    """Format product data for the general query LLM prompt."""
    if not products:
        return "No products found in the catalog."

    metric = parsed.get("metric", "price")
    direction = parsed.get("direction", "list")
    category = parsed.get("category")

    lines = []
    if direction == "count":
        # Group by category for count queries
        cat_counts: Dict[str, int] = {}
        for p in products:
            cat = p.get("category", "other")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        lines.append(f"Total products in catalog: {len(products)}")
        for cat, count in cat_counts.items():
            lines.append(f"  - {cat}: {count} products")
        return "\n".join(lines)

    if direction == "exists":
        if products:
            cats = set(p.get("category", "unknown") for p in products)
            return f"Yes, we have products in these categories: {', '.join(cats)}. Found {len(products)} matching products."
        return "No matching products found in the catalog."

    # For max/min/list, format product details
    for i, p in enumerate(products[:10], 1):
        name = p.get("name", "Unknown")
        brand = p.get("brand", "Unknown")
        price = p.get("price", "N/A")
        cat = p.get("category", "other")
        rating = p.get("rating", "N/A")
        discount = p.get("discount")
        price_str = f"Rs {price:,.0f}" if isinstance(price, (int, float)) and price else "N/A"
        rating_str = f"{rating}/5" if rating else "N/A"
        line = f"{i}. {brand} {name} | Category: {cat} | Price: {price_str} | Rating: {rating_str}"
        if discount:
            line += f" | Discount: {discount}%"
        lines.append(line)

    return "\n".join(lines)


async def _generate_general_response(
    user_message: str,
    products: List[Dict[str, Any]],
    parsed: Dict[str, Any],
) -> Optional[str]:
    """Use LLM to generate a response for a GENERAL catalog query."""
    try:
        catalog_text = _format_catalog_for_general(products, parsed)
        prompt = _GENERAL_QUERY_PROMPT.format(
            product_catalog=catalog_text,
            user_message=user_message,
        )
        messages = [
            {"role": "system", "content": "You are a helpful e-commerce assistant. You answer questions about the store's product catalog using ONLY the provided product data. Be concise and mention specific product names, prices, and brands when relevant."},
            {"role": "user", "content": prompt},
        ]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _llm_gateway.call, "response_generation", messages)
        return response
    except Exception as exc:
        plog.warning("  -> General query response generation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# EXPLAIN query helpers — answer product-specific questions
# ---------------------------------------------------------------------------

def _parse_product_name(user_message: str) -> Optional[str]:
    """Extract a product name from the user's question."""
    low = user_message.lower()

    # Common patterns for product questions
    patterns = [
        r'(?:tell me about|explain|describe|what is|what are the (?:specs|features|details))\s+(.+?)(?:\?|$)',
        r'(?:how is|how does|how good is)\s+(.+?)(?:\?|$)',
        r'(?:show me|details of|information about)\s+(.+?)(?:\?|$)',
        r'(.+?)(?:\s+specs|\s+features|\s+details|\s+price|\s+rating)(?:\?|$)',
    ]

    for pattern in patterns:
        match = re.search(pattern, low)
        if match:
            name = match.group(1).strip()
            # Clean up common fillers
            fillers = ['the', 'a', 'an', 'this', 'that', 'your', 'my', 'some', 'any']
            words = name.split()
            cleaned = [w for w in words if w not in fillers]
            if cleaned:
                return ' '.join(cleaned)

    # Fallback: check if any known brand/product keyword is mentioned
    brand_keywords = [
        'iphone', 'samsung', 'galaxy', 'oneplus', 'pixel', 'redmi', 'realme', 'xiaomi',
        'macbook', 'dell', 'hp', 'lenovo', 'asus', 'acer',
        'nike', 'adidas', 'puma', 'reebok',
        'sony', 'jbl', 'bose', 'boat',
        'loreal', 'maybelline', 'mac', 'nike',
    ]
    for brand in brand_keywords:
        if brand in low:
            # Extract surrounding context as product name
            idx = low.index(brand)
            start = max(0, idx - 20)
            end = min(len(user_message), idx + len(brand) + 30)
            snippet = user_message[start:end].strip()
            # Clean up
            snippet = re.sub(r'[?.!,]', '', snippet).strip()
            return snippet

    return None


async def _fetch_product_by_name(product_name: str) -> List[Dict[str, Any]]:
    """Search for a specific product by name across all categories."""
    if not product_name:
        return []

    # Search across all categories
    all_products = []
    categories = list(_CATEGORY_KEYWORDS.keys())

    for cat in categories:
        try:
            results = await _vector_service.search_collection(
                cat,
                query=product_name,
                n=10,
                embedding=_embedding_service.generate(product_name),
            )
            all_products.extend(results)
        except Exception:
            pass

    if not all_products:
        return []

    # Sort by relevance score
    all_products.sort(key=lambda p: p.get("_score", 0), reverse=True)

    # Return top matches (score > 0.3 indicates reasonable match)
    good_matches = [p for p in all_products if p.get("_score", 0) > 0.3]
    return good_matches[:5] if good_matches else all_products[:3]


def _format_product_for_explain(products: List[Dict[str, Any]]) -> str:
    """Format product details for the EXPLAIN LLM prompt."""
    if not products:
        return "No product found matching the query."

    lines = []
    for i, p in enumerate(products[:3], 1):  # Max 3 products
        name = p.get("name", "Unknown")
        brand = p.get("brand", "Unknown")
        price = p.get("price", "N/A")
        mrp = p.get("mrp")
        rating = p.get("rating")
        discount = p.get("discount")
        category = p.get("category", "other")
        description = p.get("description", "")
        specs = p.get("specifications", {})
        source = p.get("source", "")
        url = p.get("url", "")
        availability = p.get("availability", "In Stock")

        price_str = f"Rs {price:,.0f}" if isinstance(price, (int, float)) and price else "N/A"
        mrp_str = f"Rs {mrp:,.0f}" if isinstance(mrp, (int, float)) and mrp else "N/A"
        rating_str = f"{rating}/5" if rating else "N/A"

        lines.append(f"--- Product {i} ---")
        lines.append(f"Name: {brand} {name}")
        lines.append(f"Category: {category}")
        lines.append(f"Price: {price_str}")
        if mrp and price and mrp > price:
            lines.append(f"MRP: {mrp_str}")
        if discount:
            lines.append(f"Discount: {discount}%")
        lines.append(f"Rating: {rating_str}")
        lines.append(f"Availability: {availability}")
        lines.append(f"Source: {source}")
        if url:
            lines.append(f"URL: {url}")
        if description:
            lines.append(f"Description: {description}")
        if specs:
            lines.append("Specifications:")
            for key, val in specs.items():
                lines.append(f"  - {key}: {val}")
        lines.append("")

    return "\n".join(lines)


async def _generate_explain_response(
    user_message: str,
    products: List[Dict[str, Any]],
) -> Optional[str]:
    """Use LLM to generate a response for a product-specific question."""
    try:
        product_text = _format_product_for_explain(products)
        prompt = _EXPLAIN_PRODUCT_PROMPT.format(
            product_details=product_text,
            user_message=user_message,
        )
        messages = [
            {"role": "system", "content": "You are a helpful e-commerce product expert. You answer questions about specific products using ONLY the provided product data. Be concise and mention specific specs, features, and values when relevant."},
            {"role": "user", "content": prompt},
        ]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _llm_gateway.call, "response_generation", messages)
        return response
    except Exception as exc:
        plog.warning("  -> Explain product response generation failed: %s", exc)
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

