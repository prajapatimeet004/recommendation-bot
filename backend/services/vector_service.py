import json
import logging
import re
import time as time_module
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.errors import ChromaError

from backend.services.embedding_service import EmbeddingService
from backend.services.recommendation_service import RecommendationService
from backend.settings import settings

logger = logging.getLogger(__name__)

CACHE_DIR = Path(settings.CHROMA_DB_PATH)

_CHROMA_RETRIES = settings.CHROMA_RETRIES
_CHROMA_BACKOFF = settings.CHROMA_BACKOFF_SECONDS


def _retry_chroma(max_retries: int = _CHROMA_RETRIES, backoff: float = _CHROMA_BACKOFF):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except ChromaError as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        sleep = backoff * (2 ** attempt)
                        logger.warning("ChromaDB error (attempt %d/%d): %s. Retrying in %.1fs...", attempt + 1, max_retries, e, sleep)
                        time_module.sleep(sleep)
            raise last_exc
        return wrapper
    return decorator


class VectorService:
    _write_lock = asyncio.Lock()

    def __init__(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CACHE_DIR))
        self.embedding_service = embedding_service or EmbeddingService()

    def get_collection(self, category: str):
        """Creates or gets a ChromaDB collection for the given category name."""
        collection_name = self._normalize_collection_name(category)
        return self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_service.get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )

    def _normalize_collection_name(self, name: str) -> str:
        """Helper to ensure ChromaDB collection name is valid (lowercase alphanumeric/hyphen/underscore)."""
        if not name:
            return "other"
        
        name = name.lower().strip()
        # Replace invalid chars with underscore
        name = re.sub(r'[^a-z0-9_-]', '_', name)
        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)
        # Strip trailing underscores
        name = name.strip('_')
        
        # ChromaDB collections must be between 3 and 63 chars
        if len(name) < 3:
            name = name + "_cat"
        return name[:63]

    async def store_products(self, products: List[Dict[str, Any]], keywords: List[str] = None):
        """Asynchronously stores/updates products individually in category-based collections."""
        if not products:
            return

        async with self._write_lock:
            loop = asyncio.get_running_loop()

            @_retry_chroma()
            def _sync_store():
                now = datetime.now(timezone.utc).isoformat()

                rec_service = RecommendationService()

                for p in products:
                    cat = p.get("category") or "other"
                    col = self.get_collection(cat)

                    doc_text = self.embedding_service.build_embedding_text(p)

                    detected_gender = rec_service._detect_product_gender(p) or "unisex"

                    metadata = {
                        "product_id": str(p.get("id", "")),
                        "name": str(p.get("name") or ""),
                        "price": float(p.get("price") or 0.0),
                        "mrp": float(p.get("mrp") or 0.0),
                        "discount": float(p.get("discount") or 0.0),
                        "rating": float(p.get("rating") or 0.0),
                        "brand": str(p.get("brand") or ""),
                        "category": str(p.get("category") or "other"),
                        "gender": str(p.get("gender") or detected_gender),
                        "website": str(p.get("source") or ""),
                        "product_url": str(p.get("url") or ""),
                        "image_url": str(p.get("image") or ""),
                        "scraped_at": str(p.get("scraped_at") or now),
                        "description": str(p.get("description") or "")[:500],
                        "specs_json": json.dumps(p.get("specifications") or {}, ensure_ascii=False),
                        "availability": str(p.get("availability") or "In Stock"),
                        "keywords": ",".join(keywords) if keywords else ""
                    }

                    pid = p.get("id")
                    if not pid:
                        logger.warning("Skipping product with null/empty ID: %s", p.get("name", "unknown"))
                        continue
                    try:
                        col.upsert(
                            ids=[pid],
                            documents=[doc_text],
                            metadatas=[metadata]
                        )
                    except Exception as e:
                        logger.warning("Failed to store product '%s' (ID=%s): %s", p.get("name", "unknown"), pid, e)

                logger.info("Successfully stored/updated %d products in ChromaDB collections.", len(products))

            await loop.run_in_executor(None, _sync_store)


    async def search_collection(
        self,
        category: str,
        query: Optional[str] = None,
        n: int = 5,
        embedding: Optional[List[float]] = None,
        budget: Optional[float] = None,
        gender: Optional[str] = None,
        brand_preference: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Asynchronously searches a single category collection with metadata filters."""
        loop = asyncio.get_running_loop()

        @_retry_chroma()
        def _sync_search():
            col = self.get_collection(category)
            if col.count() == 0:
                return []

            # Construct ChromaDB native filters
            where_clauses = []
            if budget is not None:
                max_price = float(budget) * 1.10
                where_clauses.append({"price": {"$lte": max_price}})
            if gender in ("men", "women"):
                where_clauses.append({"gender": {"$in": [gender, "unisex"]}})
            if brand_preference:
                brand_list = [str(b).strip() for b in brand_preference if str(b).strip()]
                if brand_list:
                    where_clauses.append({"brand": {"$in": brand_list}})
            
            where = None
            if len(where_clauses) == 1:
                where = where_clauses[0]
            elif len(where_clauses) > 1:
                where = {"$and": where_clauses}

            query_args = {
                "n_results": n,
                "include": ["metadatas", "distances"],
            }
            if where is not None:
                query_args["where"] = where

            if embedding is not None:
                query_args["query_embeddings"] = [embedding]
            elif query is not None:
                query_args["query_texts"] = [query]
            else:
                raise ValueError("Either query or embedding must be provided to search.")

            results = col.query(**query_args)

            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            # If gender filter returned 0 results, retry without it
            if not metadatas and where is not None and gender in ("men", "women"):
                logger.info("Gender filter returned 0 results for '%s' — retrying without gender filter", gender)
                query_args.pop("where", None)
                results = col.query(**query_args)
                metadatas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]

            if not metadatas:
                return []

            products = []
            for meta, dist in zip(metadatas, distances):
                score = round(1 - dist, 4)
                
                try:
                    specs = json.loads(meta.get("specs_json", "{}"))
                except Exception:
                    specs = {}

                products.append({
                    "id": meta.get("product_id"),
                    "name": meta.get("name") or "",
                    "brand": meta.get("brand"),
                    "category": meta.get("category"),
                    "gender": meta.get("gender", "unisex"),
                    "price": float(meta.get("price") or 0.0) or None,
                    "mrp": float(meta.get("mrp") or 0.0) or None,
                    "discount": float(meta.get("discount") or 0.0) or None,
                    "rating": float(meta.get("rating") or 0.0) or None,
                    "specifications": specs,
                    "description": meta.get("description", ""),
                    "image": meta.get("image_url", ""),
                    "url": meta.get("product_url", ""),
                    "source": meta.get("website", ""),
                    "availability": meta.get("availability"),
                    "scraped_at": meta.get("scraped_at"),
                    "_score": score,
                    "_cached": True
                })
            return products

        return await loop.run_in_executor(None, _sync_search)

    async def search_all_collections(
        self,
        categories: List[str],
        query: Optional[str] = None,
        n: int = 5,
        embedding: Optional[List[float]] = None,
        budget: Optional[float] = None,
        gender: Optional[str] = None,
        brand_preference: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Asynchronously searches multiple collections in parallel and returns ranked, deduplicated products."""
        if not categories:
            categories = ["other"]
            
        search_categories = list(dict.fromkeys(categories))
        tasks = [
            self.search_collection(
                cat, 
                query=query, 
                n=n, 
                embedding=embedding, 
                budget=budget, 
                gender=gender, 
                brand_preference=brand_preference
            ) 
            for cat in search_categories
        ]
        results = await asyncio.gather(*tasks)


        # Merge and deduplicate by URL (or product_id)
        seen_ids = set()
        all_products = []
        for p_list in results:
            for p in p_list:
                pid = p.get("id")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_products.append(p)

        # Sort combined results by similarity score (descending)
        all_products.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        return all_products[:n]

    async def get_all_products(
        self,
        category: str,
        limit: int = 500,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        brands: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch ALL products from a collection without vector similarity search.

        Uses ChromaDB's get() method — no embedding computation, no HNSW traversal.
        Returns all products with full metadata, optionally filtered by price/brand.
        """
        loop = asyncio.get_running_loop()

        @_retry_chroma()
        def _sync_get():
            col = self.get_collection(category)
            if col.count() == 0:
                return []

            # Build optional metadata filters
            where_clauses = []
            if min_price is not None:
                where_clauses.append({"price": {"$gte": float(min_price)}})
            if max_price is not None:
                where_clauses.append({"price": {"$lte": float(max_price)}})
            if brands:
                brand_list = [str(b).strip() for b in brands if str(b).strip()]
                if brand_list:
                    where_clauses.append({"brand": {"$in": brand_list}})

            where = None
            if len(where_clauses) == 1:
                where = where_clauses[0]
            elif len(where_clauses) > 1:
                where = {"$and": where_clauses}

            get_args = {
                "include": ["metadatas"],
            }
            if where is not None:
                get_args["where"] = where

            results = col.get(**get_args)

            metadatas = results.get("metadatas", [])
            if not metadatas:
                return []

            products = []
            for meta in metadatas:
                try:
                    specs = json.loads(meta.get("specs_json", "{}"))
                except Exception:
                    specs = {}

                products.append({
                    "id": meta.get("product_id"),
                    "name": meta.get("name") or "",
                    "brand": meta.get("brand"),
                    "category": meta.get("category"),
                    "gender": meta.get("gender", "unisex"),
                    "price": float(meta.get("price") or 0.0) or None,
                    "mrp": float(meta.get("mrp") or 0.0) or None,
                    "discount": float(meta.get("discount") or 0.0) or None,
                    "rating": float(meta.get("rating") or 0.0) or None,
                    "specifications": specs,
                    "description": meta.get("description", ""),
                    "image": meta.get("image_url", ""),
                    "url": meta.get("product_url", ""),
                    "source": meta.get("website", ""),
                    "availability": meta.get("availability"),
                    "scraped_at": meta.get("scraped_at"),
                })

            return products[:limit] if limit else products

        return await loop.run_in_executor(None, _sync_get)
