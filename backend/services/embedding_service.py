import json
import logging
from typing import Any, Dict, List
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        logger.info("Initializing EmbeddingService with sentence-transformers 'all-MiniLM-L6-v2'")
        self._embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    def get_embedding_function(self):
        return self._embed_fn

    def generate(self, text: str) -> List[float]:
        return self._embed_fn([text])[0]

    def generate_batch(self, texts: List[str]) -> List[List[float]]:
        return self._embed_fn(texts)

    def build_embedding_text(self, product: Dict[str, Any]) -> str:
        """
        Formulates the text representation to generate embeddings.
        Includes Name, Brand, Category, Description, and Specifications.
        """
        parts = [
            f"Product Name: {product.get('name') or ''}",
            f"Brand: {product.get('brand') or ''}",
            f"Category: {product.get('category') or ''}",
            f"Description: {product.get('description') or ''}",
            f"Specifications: {json.dumps(product.get('specifications') or {}, ensure_ascii=False)}"
        ]
        return "\n".join(parts)
