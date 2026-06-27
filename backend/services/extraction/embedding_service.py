import re
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self, core_embedding_service: Optional[Any] = None):
        self.core_embedding_service = core_embedding_service

    def build_embedding_text(self, p: Dict[str, Any]) -> str:
        name = p.get("name") or ""
        brand = p.get("brand") or ""
        category = p.get("category") or ""
        
        # Clean description to ensure NO prices, image URLs, or product URLs are embedded
        desc = p.get("description") or ""
        # 1. Remove markdown images
        desc = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', desc)
        # 2. Remove markdown links, keeping only anchor text
        desc = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', desc)
        # 3. Remove raw URLs
        desc = re.sub(r'https?://\S+', '', desc)
        # 4. Remove price references (e.g. ₹124,999, Rs. 15000, MRP 20000)
        desc = re.sub(r'(?:₹|Rs\.?|MRP)\s*\d+(?:,\d+)*(?:\.\d+)?', '', desc, flags=re.IGNORECASE)
        desc = re.sub(r'\bMRP\b', '', desc, flags=re.IGNORECASE)
        # 5. Normalize spaces
        desc = re.sub(r'\s+', ' ', desc).strip()

        specs = json.dumps(p.get("specifications") or {}, ensure_ascii=False)
        
        parts = [
            f"Product Name: {name}",
            f"Brand: {brand}",
            f"Category: {category}",
            f"Description: {desc}",
            f"Specifications: {specs}"
        ]
        return "\n".join(parts)

    async def generate_embedding(self, p: Dict[str, Any]) -> List[float]:
        text = self.build_embedding_text(p)
        if self.core_embedding_service:
            import asyncio
            return await asyncio.to_thread(self.core_embedding_service.generate, text)
        
        return [0.0] * 384
