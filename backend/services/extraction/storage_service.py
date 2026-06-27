import os
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")

    async def store_supabase(self, p: Dict[str, Any]) -> bool:
        if not self.supabase_url or not self.supabase_key:
            logger.warning("Supabase URL or Key not configured. Skipping database insertion.")
            return False

        payload = {
            "id": p.get("id"),
            "name": p.get("name"),
            "brand": p.get("brand"),
            "category": p.get("category"),
            "subcategory": p.get("subcategory"),
            "price": p.get("price"),
            "mrp": p.get("mrp"),
            "discount": p.get("discount"),
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "description": p.get("description"),
            "specifications": p.get("specifications"),
            "image_url": p.get("image_url"),
            "product_url": p.get("product_url"),
            "seller": p.get("seller"),
            "availability": p.get("availability"),
            "source": p.get("source"),
            "last_scraped": p.get("scraped_at")
        }

        url = f"{self.supabase_url.rstrip('/')}/rest/v1/products"
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers=headers, timeout=10.0)
                if res.status_code in (200, 201):
                    logger.info("Successfully stored product in Supabase: %s", p.get("name"))
                    return True
                else:
                    logger.error("Failed to store in Supabase. Status: %d, Response: %s", res.status_code, res.text)
                    return False
        except Exception as e:
            logger.error("Supabase storage error: %s", e)
            return False
