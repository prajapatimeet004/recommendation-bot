import logging
import asyncio
import numpy as np
from typing import Dict, Any, List

from backend.services.apify_service import ApifyService
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.product_service import enrich_product
from backend.routers.chat import manager

logger = logging.getLogger(__name__)
apify_service = ApifyService()
embedding_service = EmbeddingService()
vector_service = VectorService(embedding_service=embedding_service)

async def discover_and_update_products_task(
    session_id: str,
    query: str,
    intent: Dict[str, Any]
) -> None:
    logger.info("Background discovery task started for query '%s' and session '%s'", query, session_id)
    try:
        # 1. Discover products using Apify
        raw_products = await apify_service.discover_products(intent)
        if not raw_products:
            logger.info("No raw products found during discovery.")
            return

        # 2. Get query embedding for semantic similarity calculations
        query_embedding = embedding_service.generate(query)

        # 3. Score and validate products
        accepted_products = []
        for p in raw_products:
            score = calculate_relevance_score(p, intent, query_embedding)
            p["_relevance_score"] = score
            if score >= 0.6:
                accepted_products.append(p)
                logger.info("  -> ACCEPTED product '%s' with score %.4f", p.get("name"), score)
            else:
                logger.info("  -> REJECTED product '%s' with score %.4f", p.get("name"), score)

        if not accepted_products:
            logger.info("No discovered products passed the relevance threshold.")
            return

        # 4. Deduplicate accepted products within this batch and against database
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
                col = vector_service.get_collection(p["category"])
                existing = col.get(ids=[pid])
                if existing and existing.get("ids"):
                    is_duplicate = True
                    logger.info("  -> DUPLICATE (by ID) found in database: %s", p.get("name"))
            except Exception as e:
                logger.warning("Error checking duplicate for product %s: %s", pid, e)

            if not is_duplicate:
                new_products.append(p)

        if not new_products:
            logger.info("All accepted products are already in the database.")
            return

        # Generate embeddings and store
        logger.info("Storing %d new products in ChromaDB collections...", len(new_products))
        await vector_service.store_products(new_products, keywords=intent.get("keywords", []))

        # 5. Notify the frontend via SSE Event Stream
        logger.info("Broadcasting %d new products to session %s...", len(new_products), session_id)
        enriched_list = []
        for p in new_products:
            p_for_enrich = dict(p)
            p_for_enrich["_score"] = p.get("_relevance_score", 0.5)
            p_for_enrich["url"] = p.get("product_url")
            p_for_enrich["image"] = p.get("image_url")
            
            enriched = enrich_product(p_for_enrich)
            enriched_list.append(enriched.model_dump())

        notification_data = {
            "type": "new_products",
            "count": len(enriched_list),
            "products": enriched_list
        }
        await manager.broadcast(session_id, notification_data)
        logger.info("Real-time notification broadcast completed.")

    except Exception as e:
        logger.exception("Error in background discovery task: %s", e)

def calculate_relevance_score(
    product: Dict[str, Any],
    intent: Dict[str, Any],
    query_embedding: List[float]
) -> float:
    # Strict gender filtering
    intent_gender = intent.get("gender")
    if intent_gender in ("men", "women"):
        import re
        p_gender = product.get("gender")
        if not p_gender:
            name = product.get("name", "").lower()
            description = product.get("description", "").lower()
            text = f"{name} {description}"
            has_men = bool(re.search(r'\b(men|mens|male|boy|boys|gents|gentlemen|his|man|guy|guys)\b', text))
            has_women = bool(re.search(r'\b(women|womens|female|girl|girls|ladies|lady|her|woman|gal)\b', text))
            if "unisex" in text or (has_men and has_women):
                p_gender = "unisex"
            elif has_men:
                p_gender = "men"
            elif has_women:
                p_gender = "women"
            else:
                p_gender = None
        else:
            p_gender_low = str(p_gender).lower()
            if "women" in p_gender_low:
                p_gender = "women"
            elif "men" in p_gender_low:
                p_gender = "men"
            elif "unisex" in p_gender_low:
                p_gender = "unisex"
            else:
                p_gender = None

        if intent_gender == "men" and p_gender == "women":
            return 0.0
        if intent_gender == "women" and p_gender == "men":
            return 0.0

    # 1. Category match
    cat_match = 1.0 if product.get("category", "").lower() == intent.get("category", "").lower() else 0.0

    # 2. Keyword match
    keywords = intent.get("keywords", [])
    matched_kws = 0
    prod_text = f"{product.get('name', '')} {product.get('description', '')}".lower()
    for kw in keywords:
        if kw.lower() in prod_text:
            matched_kws += 1
    kw_score = matched_kws / len(keywords) if keywords else 0.5

    # 3. Budget match
    budget = intent.get("budget")
    price = product.get("price")
    budget_score = 1.0
    if budget and price:
        if price <= budget:
            ratio = price / budget
            category = product.get("category", "").lower()
            if category in ("smartphones", "laptops", "home_appliances"):
                if ratio < 0.30:
                    budget_score = 0.15
                elif ratio < 0.50:
                    budget_score = 0.40
                elif ratio < 0.70:
                    budget_score = 0.80
                else:
                    budget_score = 1.0
            else:
                budget_score = 1.0
        else:
            over = price - budget
            if over <= budget * 0.1:
                budget_score = 0.7
            elif over <= budget * 0.25:
                budget_score = 0.4
            else:
                budget_score = 0.0

    # 4. Brand match
    brands = intent.get("brand_preference", [])
    brand_score = 1.0
    if brands:
        brand_score = 0.0
        p_brand = product.get("brand", "").lower()
        for b in brands:
            if b.lower() in p_brand or p_brand in b.lower():
                brand_score = 1.0
                break

    # 5. Occasion/Style match
    occ_style_score = 1.0
    occ = intent.get("occasion")
    style = intent.get("style")
    matched_occ_style = 0
    total_occ_style = 0
    if occ:
        total_occ_style += 1
        if occ.lower() in prod_text:
            matched_occ_style += 1
    if style:
        total_occ_style += 1
        if style.lower() in prod_text:
            matched_occ_style += 1
    if total_occ_style > 0:
        occ_style_score = matched_occ_style / total_occ_style

    # 6. Semantic similarity
    doc_text = embedding_service.build_embedding_text(product)
    prod_emb = embedding_service.generate(doc_text)

    dot_product = np.dot(query_embedding, prod_emb)
    norm_query = np.linalg.norm(query_embedding)
    norm_prod = np.linalg.norm(prod_emb)
    similarity = float(dot_product / (norm_query * norm_prod)) if norm_query > 0 and norm_prod > 0 else 0.5

    # Weights: Category (0.25), Keywords (0.15), Semantic (0.30), Budget (0.20), Brand (0.05), Occasion/Style (0.05)
    composite = (
        0.25 * cat_match +
        0.15 * kw_score +
        0.30 * similarity +
        0.20 * budget_score +
        0.05 * brand_score +
        0.05 * occ_style_score
    )
    return composite
