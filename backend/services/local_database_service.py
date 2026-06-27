import os
import re
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

CATEGORY_TO_FILES = {
    "smartphones": ["phones_data.json"],
    "laptops": ["laptops_5pages.json"],
    "clothing": ["clothing_data.json", "kids_clothing_data.json", "womens_clothing_data.json"],
    "shoes": ["shoes_data.json"],
    "watches": ["watches_data.json"]
}

class LocalDatabaseService:
    def __init__(self, data_dir: str = "data", embedding_service: Optional[Any] = None):
        self.data_dir = data_dir
        self.embedding_service = embedding_service
        self._cached_products: Dict[str, List[Dict[str, Any]]] = {}

    def _load_file_products(self, filename: str) -> List[Dict[str, Any]]:
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            logger.warning("Local database file not found: %s", filepath)
            return []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            logger.error("Failed to load local json database %s: %s", filepath, e)
            return []

        category = "general"
        for cat, files in CATEGORY_TO_FILES.items():
            if filename in files:
                category = cat
                break

        products = []
        for p in raw_data:
            try:
                normalized = self._normalize_local_product(p, category)
                if normalized:
                    products.append(normalized)
            except Exception as e:
                logger.debug("Failed to normalize local product item: %s", e)
                continue

        logger.info("Loaded %d products from local file: %s", len(products), filename)
        return products

    def _normalize_local_product(self, p: Dict[str, Any], category: str) -> Optional[Dict[str, Any]]:
        name = p.get("product_name") or p.get("name") or ""
        if not name:
            return None

        url = p.get("url") or p.get("product_url") or ""
        
        # Parse prices
        pricing = p.get("pricing") or {}
        selling_price_str = pricing.get("selling_price") or str(p.get("price") or "")
        price = self._parse_numeric_price(selling_price_str)
            
        mrp_str = pricing.get("mrp") or str(p.get("mrp") or "")
        mrp = self._parse_numeric_price(mrp_str)

        discount_str = pricing.get("discount") or str(p.get("discount") or "")
        discount = self._parse_numeric_price(discount_str)

        # Rating
        details = p.get("details") or {}
        rating_str = details.get("Rating") or str(p.get("rating") or "")
        rating = None
        if rating_str:
            match = re.search(r'(\d+\.?\d*)', rating_str)
            if match:
                rating = float(match.group(1))

        # Brand
        brand = details.get("Brand") or p.get("brand") or "Generic"

        # Features / Description
        features = details.get("Features") or p.get("description") or []
        description = "\n".join(features) if isinstance(features, list) else str(features)

        parsed = urlparse(url)
        source = parsed.netloc.replace("www.", "") or "local"

        specifications = p.get("specifications") or {}
        if not specifications:
            ram_match = re.search(r'(\d+\s*GB\s*RAM)', name, re.IGNORECASE)
            if ram_match:
                specifications["ram"] = ram_match.group(1)
            storage_match = re.search(r'(\d+\s*GB\s*Storage)', name, re.IGNORECASE)
            if storage_match:
                specifications["storage"] = storage_match.group(1)

        import hashlib
        prod_id = hashlib.md5((name + url).encode("utf-8")).hexdigest()

        return {
            "id": prod_id,
            "name": name,
            "brand": brand,
            "category": category,
            "price": price,
            "mrp": mrp,
            "discount": discount,
            "rating": rating,
            "specifications": specifications,
            "description": description,
            "image": p.get("image_url") or p.get("image") or "",
            "url": url,
            "source": source,
            "availability": "In Stock" if price else "Out of Stock",
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }

    def _parse_numeric_price(self, text: str) -> Optional[float]:
        if not text:
            return None
        text_clean = text.replace(",", "").replace("₹", "").strip()
        digits = re.findall(r'\d+\.?\d*', text_clean)
        if digits:
            try:
                return float(digits[0])
            except ValueError:
                return None
        return None

    def get_products_for_category(self, category: str) -> List[Dict[str, Any]]:
        # Map predicted category to files
        filenames = CATEGORY_TO_FILES.get(category, [])
        if not filenames:
            # Fallback: list all json files in data_dir
            try:
                filenames = [f for f in os.listdir(self.data_dir) if f.endswith(".json")]
            except Exception:
                filenames = []

        all_products = []
        for fn in filenames:
            if fn not in self._cached_products:
                self._cached_products[fn] = self._load_file_products(fn)
            all_products.extend(self._cached_products[fn])
        return all_products

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5
        if magnitude_a > 0 and magnitude_b > 0:
            return dot_product / (magnitude_a * magnitude_b)
        return 0.0

    async def search_local(
        self,
        query: str,
        keywords: List[str],
        category: str,
        min_score: float = 0.55
    ) -> List[Dict[str, Any]]:
        """Performs a hybrid search (keyword search + vector search) over local database files."""
        products = self.get_products_for_category(category)
        if not products or not keywords:
            return []

        # 1. Keyword search (filter stage)
        candidates = []
        for p in products:
            name = p["name"].lower()
            brand = p["brand"].lower()
            desc = p["description"].lower()
            combined = f"{name} {brand} {desc}"

            matched_kws = 0
            for kw in keywords:
                kw_clean = kw.lower().strip()
                if kw_clean in combined:
                    matched_kws += 1

            if matched_kws > 0:
                ratio = matched_kws / len(keywords)
                p["_score"] = round(0.3 + 0.7 * ratio, 4)
                candidates.append(p)

        if not candidates:
            logger.info("No local candidate products matched the keywords.")
            return []

        # Sort by keyword score and take top 40 to run vector similarity
        candidates.sort(key=lambda x: x["_score"], reverse=True)
        top_candidates = candidates[:40]

        # 2. Vector search (refinement stage)
        if self.embedding_service:
            try:
                query_vector = self.embedding_service.generate(query)
                texts_to_embed = [f"{p['name']} {p['brand']} {p['description']}" for p in top_candidates]
                product_vectors = self.embedding_service.generate_batch(texts_to_embed)

                scored_products = []
                for p, p_vector in zip(top_candidates, product_vectors):
                    sim = self._cosine_similarity(query_vector, p_vector)
                    
                    # Compute composite score
                    kw_score = p["_score"]
                    composite = 0.6 * sim + 0.4 * kw_score
                    p["_composite_score"] = round(composite, 4)
                    
                    if composite >= min_score:
                        scored_products.append(p)

                # Sort by composite score
                scored_products.sort(key=lambda x: x["_composite_score"], reverse=True)
                logger.info("Found %d local products matching query '%s' above min_score=%f", len(scored_products), query, min_score)
                return scored_products
            except Exception as e:
                logger.error("Error during vector similarity matching for local products: %s", e)
                # Fallback to keyword matching scores only
                for p in top_candidates:
                    p["_composite_score"] = p["_score"]
                return [p for p in top_candidates if p["_score"] >= min_score]

        # If no embedding service, fallback to keyword scores
        for p in top_candidates:
            p["_composite_score"] = p["_score"]
        return [p for p in top_candidates if p["_score"] >= min_score]
