import hashlib
from datetime import datetime, timezone
from typing import Dict, Any

class Normalizer:
    @staticmethod
    async def normalize(raw_product: Dict[str, Any]) -> Dict[str, Any]:
        name = (raw_product.get("name") or "").strip()
        product_url = (raw_product.get("product_url") or "").strip()
        
        # Unique ID using MD5 on name + url to prevent duplicates
        prod_id = hashlib.md5((name + product_url).encode("utf-8")).hexdigest() if name else ""

        return {
            "id": prod_id,
            "name": name or None,
            "brand": raw_product.get("brand") or "Generic",
            "category": raw_product.get("category") or "general",
            "subcategory": raw_product.get("subcategory") or "general",
            "price": raw_product.get("price") or None,
            "mrp": raw_product.get("mrp") or None,
            "discount": raw_product.get("discount") or None,
            "rating": raw_product.get("rating") or None,
            "review_count": raw_product.get("review_count") or 0,
            "description": raw_product.get("description") or None,
            "specifications": raw_product.get("specifications") or {},
            "image_url": raw_product.get("image_url") or None,
            "product_url": product_url or None,
            "availability": raw_product.get("availability") or "In Stock",
            "seller": raw_product.get("seller") or "Generic",
            "source": raw_product.get("source") or "local",
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }
