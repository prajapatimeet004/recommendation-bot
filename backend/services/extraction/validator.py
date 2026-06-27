import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class Validator:
    @staticmethod
    async def validate(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        valid_products = []
        seen_ids = set()

        for p in products:
            name = p.get("name")
            price = p.get("price")
            image_url = p.get("image_url")
            product_url = p.get("product_url")
            category = p.get("category")
            prod_id = p.get("id")

            # 1. Required fields validation
            if not name or price is None or not image_url or not product_url or not category:
                logger.warning("Product rejected by validation (missing critical field): Name=%s, Price=%s, Img=%s, URL=%s, Cat=%s", name, price, image_url, product_url, category)
                continue

            # 2. Duplicate detection
            if prod_id in seen_ids:
                logger.warning("Duplicate product rejected: %s", name)
                continue

            # 3. Ad / Banner detection
            ad_terms = ["sponsored", "advertisement", "subscribe now", "banner", "promotion", "special offer", "deal of the day"]
            if any(term in name.lower() for term in ad_terms):
                logger.warning("Advertisement/Banner rejected: %s", name)
                continue

            # 4. Recommendation widget text detection
            if len(name) > 150 or "customers who bought" in name.lower():
                logger.warning("Widget or invalid long text header rejected: %s", name)
                continue

            seen_ids.add(prod_id)
            valid_products.append(p)

        return valid_products
