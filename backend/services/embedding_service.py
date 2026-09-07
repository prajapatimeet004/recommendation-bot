import json
import logging
from typing import Any, Dict, List
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

logger = logging.getLogger(__name__)


from backend.settings import settings


class EmbeddingService:
    _embed_fn = None

    def _ensure_loaded(self) -> None:
        if self._embed_fn is None:
            logger.info("Lazy-loading EmbeddingService with sentence-transformers '%s'", settings.EMBEDDING_MODEL_NAME)
            self.__class__._embed_fn = SentenceTransformerEmbeddingFunction(
                model_name=settings.EMBEDDING_MODEL_NAME,
                local_files_only=settings.EMBEDDING_LOCAL_FILES_ONLY,
            )

    def get_embedding_function(self):
        self._ensure_loaded()
        return self._embed_fn

    def generate(self, text: str) -> List[float]:
        self._ensure_loaded()
        return self._embed_fn([text])[0]

    def generate_batch(self, texts: List[str]) -> List[List[float]]:
        self._ensure_loaded()
        return self._embed_fn(texts)

    def build_embedding_text(self, product: Dict[str, Any]) -> str:
        """
        Formulates the text representation to generate embeddings.
        Includes Name, Brand, Category, Description, and Specifications.
        """
        specs = product.get("specifications") or product.get("specs") or {}
        specs_list = []
        if isinstance(specs, dict):
            for k, v in specs.items():
                if v and str(v).strip():
                    key_clean = k.replace("_", " ").title()
                    specs_list.append(f"{key_clean} is {v}")
        specs_str = ", ".join(specs_list) if specs_list else ""

        parts = [
            f"Product Name: {product.get('name') or ''}",
            f"Brand: {product.get('brand') or ''}",
            f"Category: {product.get('category') or ''}",
            f"Description: {product.get('description') or ''}",
        ]
        if specs_str:
            parts.append(f"Specifications: {specs_str}")

        return "\n".join(parts)

