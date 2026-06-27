from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from backend.services.pipeline_logger import get_pipeline_logger

logger = get_pipeline_logger()
_db_logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "chroma_db"
COLLECTION_NAME = "product_cache"
CACHE_TTL_DAYS = 7
MIN_CACHE_HITS = 3

SIMILARITY_THRESHOLD = 0.82


class ProductCache:
    """
    Semantic product cache backed by ChromaDB with ONNX-based embeddings.

    - Similarity threshold: 0.82 (minimum cosine similarity for a cache hit)
    - TTL: 7 days — stale entries trigger a Tavily refresh
    """

    def __init__(self) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CACHE_DIR))
        self._embed_fn = DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        count = self._collection.count()
        logger.info(
            "ProductCache ready — collection '%s' has %d document(s)",
            COLLECTION_NAME,
            count,
        )

    def search_similar(
        self,
        query: str,
        n: int = 5,
        where: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info("Cache CHECK: query='%s' (requesting top %d, threshold=%.2f)", query, n, SIMILARITY_THRESHOLD)

        if self._collection.count() == 0:
            logger.info("Cache MISS — collection is empty")
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=n,
            where=where,
            include=["metadatas", "distances"],
        )

        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not metadatas:
            logger.info("Cache MISS — no similar documents found")
            return []

        products = []
        for meta, dist in zip(metadatas, distances):
            score = round(1 - dist, 4)
            if score < SIMILARITY_THRESHOLD:
                logger.info("  -> SKIP (score=%.4f < %.2f): %s", score, SIMILARITY_THRESHOLD, meta.get("name", "?"))
                continue

            specs = {}
            try:
                specs = json.loads(meta.get("specs_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                specs = {}
            tags = []
            try:
                tags = json.loads(meta.get("tags_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                tags = []

            products.append({
                "id": meta.get("id", ""),
                "name": meta.get("name", ""),
                "price": float(meta.get("price", 0)),
                "mrp": float(meta.get("mrp", 0)) if meta.get("mrp") else None,
                "discount": float(meta.get("discount", 0)) if meta.get("discount") else None,
                "brand": meta.get("brand", ""),
                "rating": float(meta.get("rating", 0)),
                "category": meta.get("category", ""),
                "description": meta.get("description", ""),
                "specifications": specs,
                "tags": tags,
                "image_url": meta.get("image_url", ""),
                "source_url": meta.get("source_url", ""),
                "source": meta.get("source", ""),
                "_score": score,
                "_cached": True,
                "_cached_at": meta.get("timestamp", ""),
            })

        if products:
            logger.info(
                "Cache HIT — found %d product(s) above threshold (score range: %.3f – %.3f)",
                len(products),
                products[-1]["_score"],
                products[0]["_score"],
            )
        else:
            logger.info("Cache MISS — no products above %.2f threshold", SIMILARITY_THRESHOLD)

        return products

    def is_stale(self, days: int = CACHE_TTL_DAYS) -> bool:
        all_meta = self._collection.get(include=["metadatas"])
        for meta in all_meta.get("metadatas", []):
            if meta and "timestamp" in meta:
                try:
                    ts = datetime.fromisoformat(meta["timestamp"])
                    age = (datetime.now(timezone.utc) - ts).days
                    if age < days:
                        return False
                except (ValueError, TypeError):
                    continue
        return True

    def store_products(
        self,
        products: List[Dict[str, Any]],
        query: str,
    ) -> int:
        if not products:
            logger.info("Cache STORE — no products to store")
            return 0

        now = datetime.now(timezone.utc).isoformat()
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, str]] = []

        for p in products:
            doc_text = (
                f"{p.get('name', '')} "
                f"{p.get('description', '')} "
                f"{json.dumps(p.get('specifications', p.get('specs', {})), ensure_ascii=False)} "
                f"{p.get('category', '')} "
                f"{' '.join(p.get('tags', []))}"
            )
            pid = p.get("id", f"prod-{abs(hash(doc_text))}")
            ids.append(pid)
            documents.append(doc_text)
            metadatas.append({
                "id": pid,
                "name": p.get("name", ""),
                "price": str(p.get("price", 0)),
                "mrp": str(p.get("mrp", 0) or ""),
                "discount": str(p.get("discount", 0) or ""),
                "brand": p.get("brand", ""),
                "rating": str(p.get("rating", 0)),
                "category": p.get("category", ""),
                "description": p.get("description", "")[:500],
                "specs_json": json.dumps(p.get("specifications", p.get("specs", {})), ensure_ascii=False),
                "tags_json": json.dumps(p.get("tags", [])),
                "image_url": p.get("image_url", ""),
                "source_url": p.get("product_url", p.get("source_url", "")),
                "source": p.get("source", ""),
                "query": query,
                "timestamp": now,
            })

        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(
            "Cache STORE — inserted/updated %d product(s) from query '%s'",
            len(products),
            query,
        )
        return len(products)

    def count(self) -> int:
        return self._collection.count()

    def delete_old(self, days: int = CACHE_TTL_DAYS) -> int:
        all_meta = self._collection.get(include=["metadatas"])
        to_delete = []
        for i, meta in enumerate(all_meta.get("metadatas", [])):
            if meta and "timestamp" in meta:
                try:
                    ts = datetime.fromisoformat(meta["timestamp"]).timestamp()
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(meta["timestamp"])).days
                    if age >= days:
                        to_delete.append(all_meta["ids"][i])
                except (ValueError, IndexError, TypeError):
                    continue
        if to_delete:
            self._collection.delete(ids=to_delete)
            logger.info(
                "Cache CLEANUP — removed %d expired entries (>%d days old)",
                len(to_delete),
                days,
            )
        return len(to_delete)
