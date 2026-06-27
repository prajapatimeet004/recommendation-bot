import logging
from typing import List, Dict, Any, Optional

from backend.services.vector_service import VectorService

logger = logging.getLogger(__name__)


class ProductRepository:
    def __init__(self, vector_service: VectorService) -> None:
        self.vector_service = vector_service

    async def save_products(self, products: List[Dict[str, Any]], keywords: Optional[List[str]] = None) -> None:
        """Persist a list of products individually into ChromaDB collections based on their categories."""
        if not products:
            return
        await self.vector_service.store_products(products, keywords)

    async def get_products_by_category(self, category: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Query products matching a search string in a specific category collection."""
        return await self.vector_service.search_collection(category, query, n=limit)

    async def get_products_across_categories(self, categories: List[str], query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Query and merge matching products across multiple collections."""
        return await self.vector_service.search_all_collections(categories, query, n=limit)
