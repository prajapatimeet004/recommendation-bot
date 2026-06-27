import re
import json
import logging
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from backend.services.llm_gateway import LLMGateway
from backend.services.extract_service import ExtractService
from backend.models.product import ProductSchema

logger = logging.getLogger(__name__)

# List page indicators in URLs
_LIST_URL_PATTERN = re.compile(
    r'(/s\?k=|/s\?rh=|/b\?|/best-|/search\?|/s\?ref=|/q/|/clp/|/unboxed/|\?s=bazaar|/l/|/category/|/list/|/listing/)',
    re.IGNORECASE,
)

_SINGLE_PRODUCT_EXTRACT_PROMPT = """\
You are an expert e-commerce data extraction engine.
Analyze the provided web page content and extract the product details as a JSON object.

Do NOT hallucinate or make up any values. Only extract what is explicitly mentioned in the content. If a field is not found, return null.

Required JSON format:
{
  "name": "Product Name (string or null)",
  "brand": "Brand Name (string or null)",
  "category": "Product Category (string or null)",
  "price": 12345.0,  // Numeric price or null
  "mrp": 15000.0,    // Numeric original price (MRP) or null
  "discount": 17.7,  // Numeric percentage discount or null
  "rating": 4.2,     // Numeric average rating out of 5 or null
  "specifications": { ... }, // Dictionary of product specifications or empty dict {}
  "description": "Product description (string or null)",
  "image": "Product image URL (string or null)",
  "url": "Product URL (string or null)",
  "source": "Source website domain, e.g. amazon.in, flipkart.com, myntra.com, nykaa.com, croma.com (string or null)",
  "availability": "Availability status, e.g. In Stock, Out of Stock, or null (string or null)"
}
"""

_CATEGORY_PRODUCTS_EXTRACT_PROMPT = """\
You are an expert e-commerce data extraction engine.
Analyze the provided product listing or search results page content and extract ALL visible products as a JSON list.

Do NOT hallucinate or make up any values. Only extract what is explicitly mentioned. If a field is not found, return null.

Return a JSON object with two fields:
1. "products" - a list of product objects, where each object matches this schema:
   {
     "name": "Product Name (string or null)",
     "brand": "Brand Name (string or null)",
     "category": "Product Category (string or null)",
     "price": 12345.0,  // Numeric price or null
     "mrp": 15000.0,    // Numeric original price (MRP) or null
     "discount": 17.7,  // Numeric percentage discount or null
     "rating": 4.2,     // Numeric average rating out of 5 or null
     "specifications": { ... }, // Dictionary of key specifications (e.g. RAM, storage, display) or empty dict {}
     "description": "Short description (string or null)",
     "image": "Product image URL (string or null)",
     "url": "Product URL (string or null)",
     "source": "Source website domain, e.g. amazon.in, flipkart.com, myntra.com, nykaa.com, croma.com (string or null)",
     "availability": "Availability status, e.g. In Stock, Out of Stock, or null (string or null)"
   }
2. "next_page_url" - The absolute or relative URL of the next page in pagination if it exists on the page, or null.

Format the output strictly as a JSON object.
"""


class ProductParser:
    def __init__(self, gateway: Optional[LLMGateway] = None, extract_service: Optional[ExtractService] = None, vector_service: Optional[Any] = None):
        self.gateway = gateway or LLMGateway()
        self.extract_service = extract_service or ExtractService()
        
        # Initialize modular pipeline parser
        from backend.services.embedding_service import EmbeddingService
        from backend.services.extraction.parser import PipelineParser
        core_embed = EmbeddingService()
        self.pipeline_parser = PipelineParser(core_embedding_service=core_embed, vector_service=vector_service)

    def determine_page_type(self, url: str, content: str = "") -> str:
        """Determines if the URL is a single product page or category/listing page."""
        url_lower = url.lower()

        # Amazon India
        if "amazon.in" in url_lower:
            if "/dp/" in url_lower or "/gp/product/" in url_lower:
                return "product"
            return "category"

        # Flipkart
        if "flipkart.com" in url_lower:
            if "/p/" in url_lower:
                return "product"
            return "category"

        # Myntra
        if "myntra.com" in url_lower:
            # Myntra product URLs end with a pattern like /12345/buy
            if "/buy" in url_lower or re.search(r'/\d+$', url_lower.rstrip('/')):
                return "product"
            return "category"

        # Nykaa
        if "nykaa.com" in url_lower:
            if "/p/" in url_lower or "/product" in url_lower:
                return "product"
            return "category"

        # Croma
        if "croma.com" in url_lower:
            if "/p/" in url_lower:
                return "product"
            return "category"

        if _LIST_URL_PATTERN.search(url_lower):
            return "category"

        # Fallback check on content
        if content:
            # High count of ₹ symbol usually means a listing page
            rupee_count = content.count("₹") + content.count("Rs")
            if rupee_count > 6:
                return "category"

        return "product"

    async def parse_single_product(
        self,
        url: str,
        content: str,
        default_category: Optional[str] = None,
        query: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Parses a single product page using the deterministic regex pipeline."""
        try:
            prods = await self.pipeline_parser.parse_and_store_webpage(content, url)
            if prods:
                p = prods[0]
                # Provide backward-compatibility keys for existing code
                p["image"] = p.get("image_url")
                p["url"] = p.get("product_url")
                return p
            return None
        except Exception as e:
            logger.error("Failed parsing single product with modular pipeline: %s", e)
            return None

    async def parse_category_page(
        self,
        url: str,
        content: str,
        default_category: Optional[str] = None,
        page_limit: int = 3,
        current_page: int = 1,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Parses category page using the deterministic regex pipeline."""
        try:
            prods = await self.pipeline_parser.parse_and_store_webpage(content, url)
            for p in prods:
                p["image"] = p.get("image_url")
                p["url"] = p.get("product_url")
            return prods
        except Exception as e:
            logger.error("Failed parsing category page with modular pipeline: %s", e)
            return []



    def normalize_product(self, raw: Dict[str, Any], default_category: Optional[str] = None, query: Optional[str] = None) -> Dict[str, Any]:
        """Performs robust data sanitization and field normalizations to match the schema."""
        url = raw.get("url", "").strip()
        if not url:
            raise ValueError("Product URL is required for normalization.")

        # ID: Deterministic MD5 hash of product URL to prevent duplicate scraping and insertion
        pid = hashlib.md5(url.encode()).hexdigest()

        name = self.normalize_whitespace(raw.get("name") or "")
        brand = self.normalize_brand(raw.get("brand"))
        
        # Category normalizations
        category = self.normalize_category(raw.get("category") or default_category)
        
        price = self.normalize_price(raw.get("price"))
        mrp = self.normalize_price(raw.get("mrp"))
        rating = self.normalize_rating(raw.get("rating"))

        # Fix 3: Garbage/Quality Check Validation
        if not name or len(name) < 3:
            raise ValueError("Product name is too short or missing.")
        if query:
            q_clean = query.strip().lower()
            n_clean = name.strip().lower()
            if n_clean == q_clean and price is None and rating is None:
                raise ValueError("Product name matches query exactly and lacks price/rating (likely garbage content).")
        
        # Calculate discount if price/mrp exists, otherwise use raw discount
        discount = self.normalize_discount(raw.get("discount"), price, mrp)
        
        specifications = self.normalize_specs(raw.get("specifications") or {})
        
        description = self.normalize_whitespace(raw.get("description") or name)

        image = raw.get("image") or raw.get("image_url") or None
        
        if image:
            image = image.strip()

        source = raw.get("source") or self._resolve_domain(url)
        availability = raw.get("availability")
        if availability:
            availability = availability.strip()
        else:
            availability = "In Stock" if price else "Out of Stock"

        scraped_at = raw.get("scraped_at") or datetime.now(timezone.utc).isoformat()

        return {
            "id": pid,
            "name": name,
            "brand": brand or "Generic",
            "category": category,
            "price": price,
            "mrp": mrp,
            "discount": discount,
            "rating": rating,
            "specifications": specifications,
            "description": description,
            "image": image,
            "url": url,
            "source": source,
            "availability": availability,
            "scraped_at": scraped_at
        }

    # Normalization Helpers
    def normalize_price(self, val: Any) -> Optional[float]:
        if val is None or val == "":
            return None
        if isinstance(val, (int, float)):
            return float(val)
        
        # Remove currency prefix/abbreviations (including any dots like Rs. or INR.) first
        s_val = str(val).strip()
        s_val = re.sub(r'^(?:Rs\.?|INR\.?|MRP\.?|Price\.?|₹)\s*', '', s_val, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"[^\d.]", "", s_val)
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None


    def normalize_rating(self, val: Any) -> Optional[float]:
        if val is None or val == "":
            return None
        if isinstance(val, (int, float)):
            return min(float(val), 5.0)
        match = re.search(r"[\d.]+", str(val))
        if match:
            try:
                return min(float(match.group()), 5.0)
            except ValueError:
                pass
        return None

    def normalize_discount(self, discount: Any, price: Optional[float], mrp: Optional[float]) -> Optional[float]:
        if price and mrp and mrp > price:
            return round(((mrp - price) / mrp) * 100, 1)
        if discount is not None:
            return self.normalize_price(discount)
        return None

    def normalize_brand(self, brand: Optional[str]) -> Optional[str]:
        if not brand:
            return None
        brand = brand.strip()
        b_lower = brand.lower()
        mapping = {
            "apple": "Apple", "samsung": "Samsung", "oneplus": "OnePlus",
            "xiaomi": "Xiaomi", "redmi": "Redmi", "realme": "Realme",
            "oppo": "Oppo", "vivo": "Vivo", "motorola": "Motorola",
            "nokia": "Nokia", "poco": "Poco", "sony": "Sony", "lg": "LG",
            "hp": "HP", "dell": "Dell", "lenovo": "Lenovo", "asus": "Asus",
            "acer": "Acer", "boat": "boAt", "jbl": "JBL", "bose": "Bose"
        }
        return mapping.get(b_lower, brand)

    def normalize_category(self, category: Optional[str]) -> str:
        if not category:
            return "other"
        cat_lower = category.lower().strip()
        valid_cats = ["smartphones", "laptops", "fashion", "beauty", "footwear", "home_appliances", "electronics"]
        for vc in valid_cats:
            if vc in cat_lower or cat_lower in vc:
                return vc
        return "other"

    def normalize_specs(self, specs: Any) -> Dict[str, Any]:
        if not isinstance(specs, dict):
            return {}
        normalized = {}
        for k, v in specs.items():
            k_clean = re.sub(r'\s+', ' ', k.strip().lower())
            v_str = re.sub(r'\s+', ' ', str(v).strip())
            
            # Normalize units for RAM/Storage/Memory
            if any(term in k_clean for term in ["ram", "storage", "rom", "memory"]):
                # E.g. "8 gb", "8gb", "8  GB" -> "8GB"
                v_str = re.sub(r'(\d+)\s*(gb|tb|mb)', lambda m: m.group(1) + m.group(2).upper(), v_str, flags=re.IGNORECASE)
                
            normalized[k_clean] = v_str
        return normalized

    def normalize_text(self, text: Optional[str]) -> str:
        """Removes HTML, multiple whitespaces, ads and noise from content."""
        if not text:
            return ""
        # Remove HTML
        text = re.sub(r"<[^>]*>", "", text)
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            l_strip = line.strip()
            if not l_strip:
                continue
            # Remove ad indicators
            if any(noise in l_strip.lower() for noise in ["sponsored", "ads by google", "advertisement", "subscribe to"]):
                continue
            cleaned_lines.append(re.sub(r"\s+", " ", l_strip))
        return "\n".join(cleaned_lines)

    def normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip()

    def _resolve_domain(self, url: str) -> str:
        url_lower = url.lower()
        for domain in ["flipkart.com", "amazon.in", "myntra.com", "nykaa.com", "croma.com"]:
            if domain in url_lower:
                return domain
        match = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url_lower)
        return match.group(1) if match else url_lower

    def _strip_fences(self, text: str) -> str:
        text = text.strip()
        start = text.find("{")
        if start == -1:
            start = text.find("[")
        if start == -1:
            return text
        end = text.rfind("}")
        if end == -1:
            end = text.rfind("]")
        if end == -1 or end < start:
            return text
        return text[start:end + 1].strip()
