import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb

from backend.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "chroma_db"


class VectorService:
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
        import re
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

        loop = asyncio.get_running_loop()
        
        def _sync_store():
            now = datetime.now(timezone.utc).isoformat()
            
            for p in products:
                # Determine collection name
                cat = p.get("category") or "other"
                col = self.get_collection(cat)
                
                # Build embedding text and doc
                doc_text = self.embedding_service.build_embedding_text(p)
                
                # Metadata (needs to be flat strings/ints/floats)
                metadata = {
                    "product_id": str(p.get("id", "")),
                    "name": str(p.get("name") or ""),
                    "price": float(p.get("price") or 0.0),
                    "mrp": float(p.get("mrp") or 0.0),
                    "discount": float(p.get("discount") or 0.0),
                    "rating": float(p.get("rating") or 0.0),
                    "brand": str(p.get("brand") or ""),
                    "category": str(p.get("category") or "other"),
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
                col.upsert(
                    ids=[pid],
                    documents=[doc_text],
                    metadatas=[metadata]
                )
                
            logger.info("Successfully stored/updated %d products in ChromaDB collections.", len(products))

        await loop.run_in_executor(None, _sync_store)

    async def search_collection(
        self,
        category: str,
        query: str,
        n: int = 5
    ) -> List[Dict[str, Any]]:
        """Asynchronously searches a single category collection."""
        loop = asyncio.get_running_loop()

        def _sync_search():
            col = self.get_collection(category)
            if col.count() == 0:
                return []

            results = col.query(
                query_texts=[query],
                n_results=n,
                include=["metadatas", "distances"],
            )

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
        query: str,
        n: int = 5
    ) -> List[Dict[str, Any]]:
        """Asynchronously searches multiple collections in parallel and returns ranked, deduplicated products."""
        if not categories:
            categories = ["other"]
            
        # Ensure 'other' and 'electronics' are searched as fallbacks if searching specific categories
        search_categories = list(categories)
        for fallback in ["electronics", "other"]:
            if fallback not in search_categories:
                search_categories.append(fallback)

        tasks = [self.search_collection(cat, query, n) for cat in search_categories]
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
