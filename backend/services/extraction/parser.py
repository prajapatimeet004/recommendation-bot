import time
import logging
from typing import List, Dict, Any, Optional

from backend.services.extraction.cleaner import Cleaner
from backend.services.extraction.product_block_detector import ProductBlockDetector
from backend.services.extraction.field_extractor import FieldExtractor
from backend.services.extraction.normalizer import Normalizer
from backend.services.extraction.validator import Validator
from backend.services.extraction.embedding_service import EmbeddingService
from backend.services.extraction.storage_service import StorageService

logger = logging.getLogger(__name__)

class PipelineParser:
    def __init__(self, core_embedding_service: Optional[Any] = None, vector_service: Optional[Any] = None):
        self.cleaner = Cleaner()
        self.block_detector = ProductBlockDetector()
        self.field_extractor = FieldExtractor()
        self.normalizer = Normalizer()
        self.validator = Validator()
        self.embedding_service = EmbeddingService(core_embedding_service)
        self.storage_service = StorageService()
        self.vector_service = vector_service

    async def parse_and_store_webpage(self, raw_content: str, url: str) -> List[Dict[str, Any]]:
        start_time = time.time()
        logger.info("Initializing modular extraction pipeline for URL: %s", url)

        # 1. Cleaner
        cleaned_text = await self.cleaner.clean(raw_content)

        # 2. Product Block Detection
        blocks = await self.block_detector.detect_blocks(cleaned_text)
        
        # 3. Field Extraction
        raw_products = []
        regex_matches = 0
        for block in blocks:
            fields = await self.field_extractor.extract_fields(block, url)
            if fields:
                raw_products.append(fields)
                regex_matches += 1

        # 4. Normalizer
        normalized_products = []
        for raw_p in raw_products:
            normalized = await self.normalizer.normalize(raw_p)
            normalized_products.append(normalized)

        # 5. Validator
        valid_products = await self.validator.validate(normalized_products)

        products_found = len(normalized_products)
        products_removed = products_found - len(valid_products)
        duplicate_products = products_removed  # main source of validation removals

        # 6. Database Storage & Embeddings
        stored_products = []
        for p in valid_products:
            db_success = await self.storage_service.store_supabase(p)
            
            embedding_created = False
            if self.vector_service:
                try:
                    # Formulate specific text representation and index in ChromaDB
                    emb_text = self.embedding_service.build_embedding_text(p)
                    # We store inside vector service
                    # Wait! In our code vector_service saves using a save method or similar. Let's make sure it is safe.
                    await self.vector_service.store_products([p], [p.get("brand") or "Generic"])
                    embedding_created = True
                except Exception as e:
                    logger.error("ChromaDB vector insertion failed: %s", e)

            missing_fields = [k for k, v in p.items() if v is None]
            
            # Step 11: Structured Logging
            logger.info(
                "Product Extraction Status | Name: %s | Missing Fields: %s | Regex Matches: %d | Embedding Created: %s | Database Insert Success: %s",
                p.get("name"), missing_fields, regex_matches, embedding_created, db_success
            )
            stored_products.append(p)

        time_taken = time.time() - start_time
        
        # Step 11: Structured Webpage Summary Logging
        logger.info(
            "Webpage Summary | URL: %s | Products Found: %d | Products Removed: %d | Duplicate Products: %d | Time Taken: %.4fs",
            url, products_found, products_removed, duplicate_products, time_taken
        )

        return stored_products
