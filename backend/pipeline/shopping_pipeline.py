from __future__ import annotations

import logging
import os
import re
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


from backend.services.keyword_service import KeywordService
from backend.services.search_service import SearchService
from backend.services.extract_service import ExtractService
from backend.services.product_parser import ProductParser
from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService
from backend.services.cache_service import CacheService
from backend.services.product_repository import ProductRepository
from backend.services.recommendation_service import RecommendationService
from backend.services.product_service import store_pagination, clear_pagination
from backend.services.pipeline_logger import get_pipeline_logger
from backend.services.local_database_service import LocalDatabaseService

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

# Dependency injection / Singleton initialization
_keyword_service = KeywordService()
_search_service = SearchService()
_extract_service = ExtractService()
_embedding_service = EmbeddingService()
_vector_service = VectorService(embedding_service=_embedding_service)
_product_parser = ProductParser(extract_service=_extract_service, vector_service=_vector_service)
_cache_service = CacheService(vector_service=_vector_service)
_product_repository = ProductRepository(vector_service=_vector_service)
_local_db_service = LocalDatabaseService(embedding_service=_embedding_service)
_recommendation_service = RecommendationService()


def _filter_search_results(
    search_results: List[Dict[str, Any]],
    keywords: List[str],
    query: str
) -> List[Dict[str, Any]]:
    if not search_results:
        return []
    
    stop_words = {
        'buy', 'online', 'best', 'price', 'in', 'the', 'and', 'for', 'with', 'under', 
        'from', 'at', 'store', 'shop', 'latest', 'of', 'to', 'show', 'list', 'trousers', 
        'pants', 'clothing', 'wear'
    }
    
    tokens = set()
    for text in [query] + keywords:
        clean_words = re.findall(r'\b\w{3,}\b', text.lower())
        tokens.update(clean_words)
        
    match_tokens = tokens - stop_words
    if not match_tokens:
        match_tokens = tokens
        
    if not match_tokens:
        return search_results

    filtered = []
    for res in search_results:
        url = res.get("url", "").lower()
        title = res.get("title", "").lower()
        snippet = res.get("snippet", "").lower()
        
        is_relevant = False
        for token in match_tokens:
            if token in url or token in title or token in snippet:
                is_relevant = True
                break
                
        if is_relevant:
            filtered.append(res)
        else:
            logger.info("Rejecting URL that does not match search criteria: %s (Title: %s)", url, res.get("title"))
            
    return filtered


async def run_pipeline(
    user_message: str,
    session_id: str = "",
    tavily_api_key: str = "",
) -> Dict[str, Any]:
    if tavily_api_key:
        # Override key in search and extract services if provided
        _search_service.api_key = tavily_api_key
        _extract_service.api_key = tavily_api_key

    plog.info("")
    plog.info("=" * 60)
    plog.info("ASYNC SHOPPING PIPELINE — query='%s'", user_message)
    plog.info("=" * 60)

    clear_pagination(session_id, user_message)

    # STEP 1 & 2: Intent detection, Keyword generation, and Category classification
    plog.info("STEP 1&2 -- Intent + Keywords + Category classification")
    analysis = _keyword_service.analyze(user_message)
    intent = analysis.get("intent", "RECOMMEND")
    keywords = analysis.get("keywords", [])
    predicted_category = analysis.get("category", "other")

    # Handle non-recommend intents
    if intent in ("GREETING", "GENERAL"):
        plog.info("  -> Non-shopping intent=%s — returning empty pipeline", intent)
        return {
            "intent": intent,
            "products": [],
            "keywords": keywords,
            "data_source": "none",
        }

    if intent in ("COMPARE", "FOLLOW_UP", "BUNDLE", "EXPLAIN"):
        plog.info("  -> Special intent=%s — passing through", intent)

    products = []
    data_source = "none"

    # STEP 2.5: Search local database first
    plog.info("STEP 2.5 -- Searching local JSON database in data/ directory")
    local_products = await _local_db_service.search_local(
        query=user_message,
        keywords=keywords,
        category=predicted_category,
        min_score=0.55
    )

    if local_products:
        plog.info("  -> LOCAL DATABASE HIT — Found %d matching products, skipping online search.", len(local_products))
        data_source = "local_db"
        products = local_products
    else:
        plog.info("  -> LOCAL DATABASE MISS — trying semantic cache (ChromaDB)")
        # STEP 3: Search ChromaDB first (Similarity cache)
        plog.info("STEP 3 -- ChromaDB Cache Search (threshold=0.82)")
        search_categories = [predicted_category]
        cached_products = await _cache_service.get_cached_products(user_message, search_categories)

        if cached_products:
            plog.info("  -> CACHE HIT — %d products found, skipping Tavily search.", len(cached_products))
            data_source = "cached"
            products = cached_products

    if not products:
        plog.info("  -> CACHE & LOCAL MISS — searching Tavily")
        data_source = "live"

        # STEP 4: Tavily URL Search
        plog.info("STEP 4 -- Tavily URL Search")
        search_results = await _search_service.search_multiple_queries(keywords)
        
        if search_results:
            _dump_to_file("backend/logs/tavily_raw.jsonl", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "search_results",
                "query": user_message,
                "keywords": keywords,
                "results": search_results
            })

        if search_results:
            # Reject URLs that don't match the query keywords
            filtered_results = _filter_search_results(search_results, keywords, user_message)
            plog.info("Filtered Tavily search URLs: %d -> %d", len(search_results), len(filtered_results))
            search_results = filtered_results

        if not search_results:
            plog.info("  -> Tavily returned 0 search results — returning empty list")
            products = []
        else:
            # STEP 5 & 6: Determine Page Type & Extract/Parse products from each URL concurrently
            plog.info("STEP 5&6 -- Async Page Type Detection + Extract & Parse (%d URLs)", len(search_results))
            
            async def process_url(res: Dict[str, Any]) -> List[Dict[str, Any]]:
                url = res["url"]
                title = res.get("title") or ""
                snippet = res.get("snippet") or ""
                try:
                    page_type = _product_parser.determine_page_type(url)
                    if page_type == "product":
                        logger.info("Visiting product URL with Selenium: %s", url)
                        try:
                            from backend.services.selenium_scraper import scrape_with_selenium_async
                            selenium_res = await scrape_with_selenium_async(url)
                            if selenium_res and selenium_res.get("name"):
                                _dump_to_file("backend/logs/tavily_raw.jsonl", {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "type": "selenium_content",
                                    "url": url,
                                    "scraped": selenium_res
                                })
                                raw_dict = {
                                    "name": selenium_res["name"],
                                    "price": selenium_res["price"],
                                    "specifications": selenium_res["specifications"],
                                    "url": url,
                                    "source": _product_parser._resolve_domain(url),
                                    "image": f"https://images.unsplash.com/photo-1523275335684-37898b6baf30?q=80&w=200",  # default/fallback image
                                    "availability": "In Stock" if selenium_res["price"] else "Out of Stock"
                                }
                                try:
                                    prod = _product_parser.normalize_product(raw_dict, default_category=predicted_category, query=user_message)
                                    if prod:
                                        return [prod]
                                except Exception as ex:
                                    logger.warning("Failed to normalize Selenium product for %s: %s", url, ex)
                        except Exception as se_err:
                            logger.warning("Selenium scraper execution failed for %s: %s", url, se_err)
                        logger.info("Selenium scraper failed or returned no name. Falling back to Tavily Extract for: %s", url)

                    content = await _extract_service.extract_url_content(url)
                    
                    if content:
                        _dump_to_file("backend/logs/tavily_raw.jsonl", {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "type": "extract_content",
                            "url": url,
                            "content_length": len(content),
                            "content": content
                        })

                    # Check for bot detection / captcha / empty / short pages
                    is_blocked = False
                    if content:
                        content_lower = content.lower()
                        if "captcha" in content_lower or "robot check" in content_lower or "automate your access" in content_lower:
                            is_blocked = True
                            logger.warning("Detected robot check/captcha blocking for URL: %s", url)

                    if not content or is_blocked or len(content) < 1000:
                        if page_type == "category":
                            # Fallback: Extract multiple products from the search snippet!
                            logger.info("Category extract failed or blocked for %s. Falling back to parsing search snippet.", url)
                            fallback_content = f"Page Title: {title}\nSearch Results Page Snippet:\n{snippet}"
                            return await _product_parser.parse_category_page(
                                url=url,
                                content=fallback_content,
                                default_category=predicted_category,
                                page_limit=1,
                                query=user_message
                            )
                        else:
                            # Fallback: Single product page regex extraction
                            logger.info("Product page extract failed or blocked for %s. Falling back to regex parsing on snippet/title.", url)
                            from backend.services.regex_parser import parse_product
                            content_fallback = (title + "\n" + snippet) if snippet else title
                            regex_prod = parse_product(content_fallback, url, fallback_title=title, fallback_snippet=snippet)
                            if regex_prod:
                                raw_dict = regex_prod.model_dump()
                                raw_dict["url"] = raw_dict.get("product_url") or url
                                raw_dict["image"] = raw_dict.get("image_url")
                                try:
                                    prod = _product_parser.normalize_product(raw_dict, default_category=predicted_category, query=user_message)
                                    return [prod] if prod else []
                                except Exception as ex:
                                    logger.warning("Failed to normalize regex fallback product for %s: %s", url, ex)
                            # Create synthetic fallback product
                            if title and len(title) > 5:
                                from backend.services.regex_parser import _clean_product_name, _clean_price, _extract_brand
                                name_candidate = _clean_product_name(title)
                                if name_candidate:
                                    price_candidate = _clean_price(snippet) or _clean_price(title)
                                    brand_candidate = _extract_brand(title, name_candidate)
                                    synthetic_raw = {
                                        "name": name_candidate,
                                        "brand": brand_candidate or "Generic",
                                        "price": price_candidate,
                                        "url": url,
                                        "source": _product_parser._resolve_domain(url),
                                        "description": snippet or title,
                                        "availability": "In Stock" if price_candidate else "Out of Stock"
                                    }
                                    try:
                                        prod = _product_parser.normalize_product(synthetic_raw, default_category=predicted_category, query=user_message)
                                        return [prod] if prod else []
                                    except Exception as ex:
                                        logger.warning("Failed to normalize synthetic fallback product for %s: %s", url, ex)
                            return []

                    # Double check page type using content representation
                    if page_type == "product" and _product_parser.determine_page_type(url, content) == "category":
                        page_type = "category"

                    if page_type == "product":
                        prod = await _product_parser.parse_single_product(url, content, default_category=predicted_category, query=user_message)
                        return [prod] if prod else []
                    else:
                        # Extracts all products and crawls paginated lists recursively
                        return await _product_parser.parse_category_page(url, content, default_category=predicted_category, query=user_message)
                except Exception as e:
                    logger.warning("Error processing URL %s: %s", url, e)
                    return []

            tasks = [process_url(res) for res in search_results]
            nested_results = await asyncio.gather(*tasks)

            # Flatten list of extracted products
            extracted_products = []
            for p_list in nested_results:
                extracted_products.extend(p_list)

            # Deduplicate by name and URL
            products = _deduplicate_pipeline_products(extracted_products)
            
            # Compute similarity score comparing product keywords with generated LLM keywords
            _score_products(products, user_message, keywords)
            
            # Store freshly extracted normalized products in separate file
            if products:
                _dump_to_file("backend/logs/extracted_products.jsonl", {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "query": user_message,
                    "products": products
                })

            plog.info("  -> Extracted %d deduplicated live product(s)", len(products))

            # STEP 7: Store in ChromaDB
            if products:
                plog.info("STEP 7 -- Store in ChromaDB category collections (%d products)", len(products))
                await _product_repository.save_products(products, keywords)
            else:
                plog.info("  -> live scrape returned 0 products")

    if not products:
        plog.info("  -> No products found at all")
        return {
            "intent": intent,
            "products": [],
            "keywords": keywords,
            "data_source": "none",
        }

    # STEP 8: Composite Scoring, Ranking, and Top 3 Selection
    plog.info("STEP 8 -- Scoring & Ranking")
    top3 = _recommendation_service.top_n(products, n=3, query=user_message)

    plog.info("  -> Top %d products:", len(top3))
    for i, p in enumerate(top3):
        sim = p.get("_score", 0.0) or p.get("similarity_score", 0.0) or 0.0
        comp = p.get("_composite_score", 0.0) or 0.0
        plog.info(
            "    -> [%d] score=%.4f (comp=%.4f) | %s | Rs %s | %s",
            i + 1,
            sim,
            comp,
            p.get("name", "?"),
            p.get("price", "?"),
            p.get("source", "?"),
        )

    # Store all matched products in pagination store for "show more" queries
    if session_id:
        store_pagination(session_id, user_message, products)

    return {
        "intent": intent,
        "products": top3,
        "all_products": products,
        "keywords": keywords,
        "data_source": data_source,
    }


def _deduplicate_pipeline_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicates list of products by clean product name and primary URL."""
    seen_keys = set()
    unique_products = []
    
    for p in products:
        if not p:
            continue
        
        name = (p.get("name") or "").lower().strip()[:60]
        # Remove query parameters from URL for deduplication key
        url = (p.get("url") or p.get("product_url") or "").split("?")[0].rstrip("/").lower()
        
        key = name or url
        if key and key not in seen_keys:
            seen_keys.add(key)
            unique_products.append(p)
            
    return unique_products


def _score_products(products: List[Dict[str, Any]], query: str, keywords: List[str]) -> None:
    """Computes similarity score comparing product content against LLM-generated keywords."""
    if not products or not keywords:
        for p in products or []:
            p["_score"] = p.get("_score", 0.5)
        return

    for p in products:
        name = (p.get("name", "") or "").lower()
        brand = (p.get("brand", "") or "").lower()
        desc = (p.get("description", "") or "").lower()
        specs = str(p.get("specifications", {})).lower()
        combined_text = f"{name} {brand} {desc} {specs}"

        matched_kws = 0
        for kw in keywords:
            kw_clean = kw.lower().strip()
            if kw_clean in combined_text:
                matched_kws += 1

        ratio = matched_kws / len(keywords)
        score = 0.3 + 0.7 * ratio
        p["_score"] = round(min(score, 1.0), 4)


def _dump_to_file(filepath: str, data: Any) -> None:
    """Helper to dump raw/debug metadata response logging into separate log files."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Failed to dump data to %s: %s", filepath, e)


