from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.embedding_service import EmbeddingService
from backend.services.vector_service import VectorService

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

FILE_CATEGORY_MAP = {
    "clothing_data.json": "fashion",
    "womens_clothing_data.json": "fashion",
    "kids_clothing_data.json": "fashion",
    "shoes_data.json": "footwear",
    "watches_data.json": "electronics",
    "phones_data.json": "smartphones",
    "laptops_5pages.json": "laptops",
}


def parse_price(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("n/a", "na", ""):
        return None
    s = re.sub(r'^[₹Rs.\s]+', '', s, flags=re.IGNORECASE)
    s = s.replace(",", "")
    s = re.sub(r'[^\d.]', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_discount(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("n/a", "na", ""):
        return None
    s = re.sub(r'[^\d.]', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_rating(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    m = re.search(r'([\d.]+)\s*out\s*of', s)
    if m:
        try:
            return min(float(m.group(1)), 5.0)
        except ValueError:
            pass
    m = re.search(r'([\d.]+)', s)
    if m:
        try:
            return min(float(m.group(1)), 5.0)
        except ValueError:
            pass
    return None


def parse_review_count(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    m = re.search(r'([\d,]+)', s)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def parse_details_to_specs(details: Dict[str, Any]) -> Dict[str, Any]:
    if not details:
        return {}

    specs = {}
    for k, v in details.items():
        k_clean = k.strip().lower()
        if k_clean in ("rating", "review count", "brand"):
            continue
        if isinstance(v, list):
            specs[k.strip()] = "; ".join(str(x) for x in v)
        elif isinstance(v, dict):
            for sk, sv in v.items():
                specs[f"{k.strip()} - {sk.strip()}"] = str(sv)
        else:
            specs[k.strip()] = str(v)
    return specs


def build_description(product_name: str, details: Dict[str, Any]) -> str:
    features = details.get("Features")
    if features and isinstance(features, list):
        return " ".join(str(f) for f in features)
    return product_name or ""


def load_json_files() -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for fname, category in FILE_CATEGORY_MAP.items():
        fpath = DATA_DIR / fname
        if not fpath.exists():
            logger.warning("File not found: %s", fpath)
            continue

        with open(fpath, encoding="utf-8") as f:
            raw_items = json.load(f)

        if not isinstance(raw_items, list):
            logger.warning("Skipping %s: not a list", fname)
            continue

        count = 0
        skipped = 0
        for item in raw_items:
            if not isinstance(item, dict):
                skipped += 1
                continue

            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                skipped += 1
                continue
            seen_urls.add(url)

            product_name = (item.get("product_name") or "").strip()
            if not product_name:
                skipped += 1
                continue

            pricing = item.get("pricing") or {}
            details = item.get("details") or {}

            selling_price = parse_price(pricing.get("selling_price"))
            mrp = parse_price(pricing.get("mrp"))
            discount = parse_discount(pricing.get("discount"))
            rating = parse_rating(details.get("Rating"))
            brand = (details.get("Brand") or "").strip() or None
            image_url = (item.get("image_url") or "").strip()
            specs = parse_details_to_specs(details)
            description = build_description(product_name, details)

            products.append({
                "id": hashlib.md5(url.encode()).hexdigest(),
                "name": product_name,
                "brand": brand or "Generic",
                "category": category,
                "price": selling_price,
                "mrp": mrp,
                "discount": discount,
                "rating": rating,
                "specifications": specs,
                "description": description,
                "image": image_url,
                "url": url,
                "source": "amazon.in",
                "availability": "In Stock" if selling_price else "Out of Stock",
            })
            count += 1

        logger.info("Loaded %d products from %s (skipped %d)", count, fname, skipped)

    logger.info("Total loaded: %d products", len(products))
    return products


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

    embed_service = EmbeddingService()
    vector_service = VectorService(embedding_service=embed_service)

    logger.info("Loading product data from %s", DATA_DIR)
    products = load_json_files()

    if not products:
        logger.error("No products loaded. Aborting.")
        return

    logger.info("Storing %d products in ChromaDB...", len(products))
    await vector_service.store_products(products, keywords=[])

    logger.info("Done! Stored %d products across category collections.", len(products))


if __name__ == "__main__":
    asyncio.run(main())
