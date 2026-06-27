"""
tavily_service.py
-----------------
Production-grade Tavily Product Retrieval Service.

Pipeline:
  User Query → Intent Extraction → Tavily Search → Raw Results

Supported sources:
  - Flipkart        (flipkart.com)
  - Amazon India    (amazon.in)
  - Myntra          (myntra.com)
  - Nykaa           (nykaa.com)
  - Croma           (croma.com)
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from backend.services.pipeline_logger import get_pipeline_logger

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_DOMAINS: List[str] = [
    "flipkart.com",
    "amazon.in",
    "myntra.com",
    "nykaa.com",
    "croma.com",
]

TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# Maximum number of Tavily results to request per search
MAX_SEARCH_RESULTS = 10

# Maximum number of URLs to deep-extract per query (rate-limit safe)
MAX_EXTRACT_URLS = 5

# Seconds before a Tavily HTTP call is considered timed-out
REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Intent model
# ---------------------------------------------------------------------------

@dataclass
class SearchIntent:
    """Structured intent parsed from the user's natural-language query."""

    raw_query: str
    product_type: str        # e.g. "smartphone", "laptop", "sunscreen"
    brand_hints: List[str]   # e.g. ["Samsung", "Apple"]
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    preferred_sources: List[str] = field(default_factory=list)
    search_query: str = ""   # Optimised query string for Tavily


# ---------------------------------------------------------------------------
# Intent Extraction
# ---------------------------------------------------------------------------

# Maps keyword -> canonical product type
_PRODUCT_TYPE_MAP: Dict[str, str] = {
    # Electronics
    "phone": "smartphone", "mobile": "smartphone", "smartphone": "smartphone",
    "iphone": "smartphone", "galaxy": "smartphone", "oneplus": "smartphone",
    "laptop": "laptop", "notebook": "laptop", "macbook": "laptop",
    "headphone": "headphones", "earphone": "headphones", "earbuds": "headphones",
    "tws": "headphones", "airpods": "headphones",
    "tablet": "tablet", "ipad": "tablet",
    "tv": "television", "television": "television",
    "camera": "camera", "dslr": "camera", "mirrorless": "camera",
    "smartwatch": "smartwatch", "watch": "smartwatch",
    "refrigerator": "refrigerator", "fridge": "refrigerator",
    "washing machine": "washing machine",
    "ac": "air conditioner", "air conditioner": "air conditioner",
    # Fashion
    "shirt": "shirt", "tshirt": "t-shirt", "t-shirt": "t-shirt",
    "jeans": "jeans", "pant": "trousers", "trouser": "trousers",
    "shoes": "shoes", "sneakers": "shoes", "footwear": "shoes",
    "dress": "dress", "saree": "saree", "kurta": "kurta",
    "bag": "bag", "handbag": "bag", "backpack": "bag",
    "jacket": "jacket", "hoodie": "hoodie",
    # Personal care / beauty
    "sunscreen": "sunscreen", "spf": "sunscreen",
    "moisturizer": "moisturizer", "lotion": "moisturizer",
    "serum": "face serum", "vitamin c": "face serum",
    "cleanser": "face wash", "face wash": "face wash",
    "lipstick": "lipstick", "lip": "lipstick",
    "foundation": "foundation", "concealer": "concealer",
    "shampoo": "shampoo", "conditioner": "hair conditioner",
    "perfume": "perfume", "deodorant": "deodorant",
    # Fitness
    "gym": "gym equipment", "dumbbell": "dumbbell", "protein": "protein supplement",
    "yoga": "yoga mat", "mat": "yoga mat",
}

# Maps keyword -> source domain
_SOURCE_HINT_MAP: Dict[str, str] = {
    "flipkart": "flipkart.com",
    "amazon": "amazon.in",
    "myntra": "myntra.com",
    "nykaa": "nykaa.com",
    "croma": "croma.com",
}

# Popular brand names (lower-cased) to detect brand hints
_KNOWN_BRANDS = {
    "samsung", "apple", "oneplus", "xiaomi", "redmi", "oppo", "vivo", "realme",
    "nokia", "motorola", "iqoo", "poco", "sony", "lg", "panasonic",
    "dell", "hp", "lenovo", "asus", "acer", "msi", "razer", "microsoft",
    "boat", "jbl", "bose", "sennheiser", "skullcandy", "jabra",
    "nike", "adidas", "puma", "reebok", "skechers", "new balance",
    "lakme", "maybelline", "loreal", "mac", "nykaa", "dot & key",
    "minimalist", "mamaearth", "mcaffeine", "plum", "the derma co",
    "forest essentials", "biotique", "himalaya", "cetaphil", "neutrogena",
    "wildcraft", "decathlon", "under armour", "zara", "h&m", "uniqlo",
}


def extract_intent(query: str) -> SearchIntent:
    """
    Parse the user's query to extract structured intent.

    This function is pure Python (no external API calls) so it is fast,
    deterministic, and free from hallucination risk.

    Args:
        query: Raw user-supplied query string.

    Returns:
        A populated SearchIntent dataclass.
    """
    q_lower = query.lower()

    # 1. Product type
    product_type = "product"
    for keyword, ptype in _PRODUCT_TYPE_MAP.items():
        if keyword in q_lower:
            product_type = ptype
            break

    # 2. Brand hints
    brand_hints: List[str] = []
    for brand in _KNOWN_BRANDS:
        if brand in q_lower:
            brand_hints.append(brand.title())

    # 3. Budget / price constraints
    price_min: Optional[float] = None
    price_max: Optional[float] = None

    # Normalise commas and currency symbols
    q_norm = q_lower.replace(",", "").replace("rs.", "").replace("rs", "").replace("inr", "")

    # "above / over / starting from / minimum <amount>" -> price_min
    min_match = re.search(
        r"(?:above|over|starting from|minimum|min|at least|more than)\s*(\d+)\s*(k|lakh|lakhs)?",
        q_norm,
    )
    if min_match:
        val = float(min_match.group(1))
        unit = (min_match.group(2) or "").lower()
        if unit == "k":
            val *= 1_000
        elif unit in ("lakh", "lakhs"):
            val *= 100_000
        price_min = val

    # "under / below / less than / within / budget of / max <amount>" -> price_max
    max_match = re.search(
        r"(?:under|below|less than|within|budget of|budget|max|maximum|upto|up to|not more than)\s*(\d+)\s*(k|lakh|lakhs)?",
        q_norm,
    )
    if max_match:
        val = float(max_match.group(1))
        unit = (max_match.group(2) or "").lower()
        if unit == "k":
            val *= 1_000
        elif unit in ("lakh", "lakhs"):
            val *= 100_000
        price_max = val

    # 4. Preferred sources
    preferred_sources: List[str] = []
    for hint, domain in _SOURCE_HINT_MAP.items():
        if hint in q_lower:
            preferred_sources.append(domain)

    # 5. Build optimised Tavily search query
    parts: List[str] = []
    if brand_hints:
        parts.extend(brand_hints)
    parts.append(product_type)
    parts.append("buy online India")
    if price_max:
        parts.append(f"under Rs {int(price_max):,}")
    elif price_min:
        parts.append(f"above Rs {int(price_min):,}")
    search_query = " ".join(parts)

    intent = SearchIntent(
        raw_query=query,
        product_type=product_type,
        brand_hints=brand_hints,
        price_min=price_min,
        price_max=price_max,
        preferred_sources=preferred_sources,
        search_query=search_query,
    )

    logger.debug(
        "Extracted intent | product_type=%s | brands=%s | price_max=%s | search_query=%s",
        product_type,
        brand_hints,
        price_max,
        search_query,
    )
    return intent


# ---------------------------------------------------------------------------
# Tavily Search Result model
# ---------------------------------------------------------------------------

@dataclass
class TavilyResult:
    """A single search result returned by Tavily."""

    title: str
    url: str
    content: str            # Snippet / page summary from Tavily
    raw_content: str        # Full page text (populated after extraction)
    score: float            # Relevance score from Tavily (0-1)
    source: str             # Resolved domain (e.g. "amazon.in")
    published_date: str = ""
    _images: List[str] = field(default_factory=list)  # extracted product image URLs
    _product_urls: List[str] = field(default_factory=list)  # product page URLs found in content


# ---------------------------------------------------------------------------
# Tavily Service
# ---------------------------------------------------------------------------

class TavilyService:
    """
    Wraps the Tavily Search and Extract APIs with:

    * Intent-aware query construction
    * Source filtering to the 5 supported e-commerce domains
    * Deduplication by URL
    * Optional full-page content extraction for richer product data
    * Structured error handling and graceful degradation
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = MAX_SEARCH_RESULTS,
        max_extract_urls: int = MAX_EXTRACT_URLS,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Tavily API key is required. Set the TAVILY_API_KEY environment "
                "variable or pass api_key= to TavilyService()."
            )
        self.max_results = max_results
        self.max_extract_urls = max_extract_urls
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        extract_content: bool = True,
        crawl_products: bool = True,
        raw_query: Optional[str] = None,
    ) -> Tuple[SearchIntent, List[TavilyResult]]:
        """
        End-to-end retrieval pipeline with product page crawling.

        Args:
            query:            Raw user query (used for intent extraction).
            extract_content:  If True, performs a second Tavily Extract call
                              to retrieve full page text for the top results.
            crawl_products:   If True, scans extracted category page content
                              for individual product page URLs and extracts them.
            raw_query:        If provided, used as the actual Tavily search query
                              instead of the intent-derived query. Useful when
                              the pipeline already has specific keywords.

        Returns:
            (intent, results) - the parsed intent and a deduplicated,
            domain-filtered list of TavilyResult objects (primarily
            individual product pages when crawl_products=True).
        """
        intent = extract_intent(query)

        search_query = raw_query if raw_query else intent.search_query

        logger.info("Starting Tavily search | query=%r | search_query=%r", query, search_query)

        # Determine which domains to search
        domains = intent.preferred_sources if intent.preferred_sources else SUPPORTED_DOMAINS

        raw_results = self._search_tavily(
            query=search_query,
            include_domains=domains,
        )

        if not raw_results:
            logger.warning("Tavily returned 0 results for query=%r", intent.search_query)
            return intent, []

        # Deduplicate by URL
        results = _deduplicate(raw_results)

        # Log individual search results
        for r in results:
            plog.info("  -> TAVILY RESULT: [%.2f] %s | %s", r.score, r.title[:80], r.url[:120])
        plog.info("  -> Tavily returned %d deduplicated result(s)", len(results))

        # Step 1: Extract full page content for top category/listing pages
        if extract_content and results:
            urls = [r.url for r in results[: self.max_extract_urls]]
            extracted = self._extract_tavily(urls)
            _merge_extracted_content(results, extracted)
            for url in urls:
                if url in extracted:
                    plog.info("  -> EXTRACTED: %s (%d chars)", url[:100], len(extracted.get(url, "")))

        # Step 2: Crawl individual product page URLs from category page content
        if crawl_products and extract_content and results:
            product_pages = self._crawl_product_pages(results)
            if product_pages:
                logger.info(
                    "Product page crawling found %d individual product page(s) — appending to results",
                    len(product_pages),
                )
                plog.info("  -> Crawled %d product page(s)", len(product_pages))
                for pp in product_pages:
                    plog.info("    -> CRAWLED: %s | %s", pp.title[:80], pp.url[:120])
                results = _deduplicate(results + product_pages)

        logger.info("Tavily pipeline complete | %d results returned", len(results))
        return intent, results

    def search_by_intent(
        self,
        intent: SearchIntent,
        *,
        extract_content: bool = True,
    ) -> List[TavilyResult]:
        """
        Accepts a pre-built SearchIntent (e.g. from an upstream
        Gemini intent-extraction step) and runs the Tavily search directly.

        Args:
            intent:          Pre-built search intent.
            extract_content: If True, performs Tavily Extract on top results.

        Returns:
            Deduplicated list of TavilyResult objects.
        """
        domains = intent.preferred_sources if intent.preferred_sources else SUPPORTED_DOMAINS

        raw_results = self._search_tavily(
            query=intent.search_query or intent.raw_query,
            include_domains=domains,
        )

        results = _deduplicate(raw_results)

        if extract_content and results:
            urls = [r.url for r in results[: self.max_extract_urls]]
            extracted = self._extract_tavily(urls)
            _merge_extracted_content(results, extracted)

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _search_tavily(
        self,
        query: str,
        include_domains: List[str],
    ) -> List[TavilyResult]:
        """Call Tavily /search and return parsed results."""
        payload: Dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_domains": include_domains,
            "max_results": self.max_results,
            "include_raw_content": False,   # fetched separately via /extract
            "include_answer": False,
        }

        try:
            t0 = time.monotonic()
            resp = self._client.post(TAVILY_API_URL, json=payload)
            elapsed = time.monotonic() - t0
            logger.debug("Tavily /search responded in %.2fs | status=%d", elapsed, resp.status_code)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.error("Tavily /search timed out after %ds for query=%r", self.timeout, query)
            return []
        except httpx.HTTPStatusError as exc:
            logger.error("Tavily /search HTTP error %d: %s", exc.response.status_code, exc.response.text)
            return []
        except httpx.RequestError as exc:
            logger.error("Tavily /search network error: %s", exc)
            return []

        data = resp.json()
        raw_items: List[Dict[str, Any]] = data.get("results", [])

        results: List[TavilyResult] = []
        for item in raw_items:
            url = item.get("url", "")
            source = _resolve_source(url)
            if source not in SUPPORTED_DOMAINS:
                # Extra guard - Tavily may occasionally bleed outside include_domains
                logger.debug("Skipping result outside supported domains: %s", url)
                continue

            results.append(
                TavilyResult(
                    title=item.get("title", "").strip(),
                    url=url,
                    content=item.get("content", "").strip(),
                    raw_content="",     # populated later if extract_content=True
                    score=float(item.get("score", 0.0)),
                    source=source,
                    published_date=item.get("published_date", ""),
                    _images=[],
                )
            )

        logger.debug("Tavily /search returned %d valid results", len(results))
        return results

    def _extract_tavily(self, urls: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Call Tavily /extract to retrieve full page text and title for a list of URLs.

        Returns:
            Mapping of url -> {"text": raw_content, "title": title}.
        """
        if not urls:
            return {}

        payload = {
            "api_key": self.api_key,
            "urls": urls,
        }

        try:
            t0 = time.monotonic()
            resp = self._client.post(TAVILY_EXTRACT_URL, json=payload)
            elapsed = time.monotonic() - t0
            logger.debug("Tavily /extract responded in %.2fs | status=%d", elapsed, resp.status_code)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Tavily /extract timed out - proceeding with snippet-only content")
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning("Tavily /extract HTTP %d - proceeding with snippet-only content", exc.response.status_code)
            return {}
        except httpx.RequestError as exc:
            logger.warning("Tavily /extract network error: %s - proceeding with snippet-only content", exc)
            return {}

        data = resp.json()
        result_map: Dict[str, Dict[str, str]] = {}

        for item in data.get("results", []):
            url = item.get("url", "")
            text = item.get("raw_content", "") or item.get("content", "")
            title = item.get("title", "") or ""
            if url and text:
                result_map[url] = {
                    "text": text.strip(),
                    "title": title.strip()
                }

        logger.debug("Tavily /extract retrieved content for %d/%d URLs", len(result_map), len(urls))
        return result_map

    def _crawl_product_pages(
        self,
        category_results: List[TavilyResult],
    ) -> List[TavilyResult]:
        """
        Scan extracted category/listing page content for individual product
        page URLs, then extract their full content via Tavily /extract.

        The product URLs are found in the raw (uncleaned) content by
        clean_page_content() which extracts them from markdown-style links
        [text](url) before stripping the link syntax. These are stored in
        each result's _product_urls attribute.

        Args:
            category_results: List of TavilyResult from the initial search
                              (category/listing pages with extracted content).

        Returns:
            New list of TavilyResult objects for individual product pages,
            or empty list if no product URLs were found.
        """
        # Collect product URLs already extracted by clean_page_content
        all_product_urls: List[str] = []
        for r in category_results:
            for u in getattr(r, "_product_urls", []):
                if u not in all_product_urls:
                    all_product_urls.append(u)

        if not all_product_urls:
            logger.debug("No product page URLs found in category page content")
            return []

        logger.info(
            "Found %d product page URL(s) in category content — extracting...",
            len(all_product_urls),
        )

        # Limit to max_extract_urls to avoid excessive API usage
        target_urls = all_product_urls[: self.max_extract_urls]

        # Extract content from product pages
        extracted = self._extract_tavily(target_urls)
        if not extracted:
            logger.warning("Tavily /extract returned no content for product pages")
            return []

        # Build TavilyResult objects for each product page
        product_results: List[TavilyResult] = []
        for url in target_urls:
            entry = extracted.get(url, {})
            raw_content = entry.get("text", "")
            title = entry.get("title", "")
            if not raw_content:
                continue

            source = _resolve_source(url)
            if source not in SUPPORTED_DOMAINS:
                continue
            cleaned, images, _ = clean_page_content(raw_content, source)

            product_results.append(
                TavilyResult(
                    title=title,
                    url=url,
                    content=title,
                    raw_content=cleaned,
                    score=1.0,
                    source=source,
                    published_date="",
                    _images=images,
                    _product_urls=[],
                )
            )

        logger.info(
            "Crawled %d product pages | amazon=%d flipkart=%d other=%d",
            len(product_results),
            sum(1 for r in product_results if r.source == "amazon.in"),
            sum(1 for r in product_results if r.source == "flipkart.com"),
            sum(1 for r in product_results if r.source not in ("amazon.in", "flipkart.com")),
        )

        return product_results

    def __enter__(self) -> "TavilyService":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release the underlying HTTP client."""
        self._client.close()


# ---------------------------------------------------------------------------
# Content cleaning — strip nav/HTML garbage, keep product text + images
# ---------------------------------------------------------------------------

_NAV_NOISE = {
    "become a seller", "hello, sign in", "account & lists", "returns & orders",
    "delivering to", "update location", "need help?", "help me decide",
    "buying guide", "sort by", "price -- low to high", "price -- high to low",
    "newest first", "customer reviews", "4 stars & up & up", "deals & discounts",
    "today's deals", "new arrivals", "last 30 days", "last 90 days",
    "pay on delivery", "eligible for pay on delivery", "include out of stock",
    "customer service", "gift cards", "video games", "amazon pay",
    "mx player", "explore plus", "60 more", "50 more", "show more",
    "skip to main", "previous", "next", "page", "you are seeing this ad",
    "sponsored", "sponsored)", "free delivery", "flat inr", "m.r.p",
    "list:", "only few left", "coming soon", "bank offer",
    "amazon prime", "sell on amazon", "best sellers", "today's deals",
    "new releases", "gift ideas", "electronics", "home & kitchen",
    "toys & games", "car & motorbike", "beauty & personal care",
    "home improvement", "grocery & gourmet foods", "health, household",
    "pet supplies", "sports, fitness & outdoors", "baby",
    "audible", "music", "movies", "books", "subscribe & save",
    "register for free", "see more", "see less", "filter", "clear filter",
    "customer review", "international brand", "new", "used",
    "discount", "off", "brands", "item condition", "availability",
    "eligible", "free shipping", "display", "resolution",
    # Amazon-specific navigation
    "custom products", "main content", "mobiles & accessories",
    "laptops & accessories", "tv & home entertainment",
    "computer peripherals", "smart technology",
    "replacement reason", "replacement period", "replacement policy",
    "cancellation policy", "refund policy", "warranty policy",
    "defective item", "physical damage", "wrong and missing item",
}


def _is_nav_line(line: str) -> bool:
    """Check if a line is navigation/sidebar noise (bullet items, single words)."""
    low = line.lower().strip("* ").strip()
    if not low:
        return True
    # Single short words that are typical nav
    if len(low.split()) <= 2 and len(low) < 30:
        if low in ("new", "used", "refurbished", "all", "premium", "value",
                    "standard", "express", "pickup", "delivery", "free",
                    "included", "available", "stock", "sale", "offer",
                    "deals", "coupons", "offers", "rewards", "prime",
                    "exclusive", "membership", "subscribe", "sign up"):
            return True
    return False


def _clean_image_url(url: str) -> str:
    """Clean an image URL: strip trailing garbage, normalize protocol."""
    url = url.strip().strip("\"'")
    # Skip data URIs (inline base64 images / tracking pixels)
    if url.startswith("data:"):
        return ""
    # Remove trailing query params for cleaner URL
    url = re.sub(r"\?.*$", "", url)
    # Fix protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url
    return url


# Product page URL patterns per domain
_PRODUCT_URL_PATTERNS: Dict[str, re.Pattern] = {
    "flipkart.com": re.compile(r'https?://(?:www\.)?flipkart\.com/[\w-]+/p/[\w-]+'),
    "amazon.in": re.compile(r'https?://(?:www\.)?amazon\.in/(?:[^/\s]+/)?dp/[\w]{10}(?:\s|/|$|\)|\?|&)'),
    "myntra.com": re.compile(r'https?://(?:www\.)?myntra\.com/[\w-]+(?:/[\w-]+)*/\d+'),
    "nykaa.com": re.compile(r'https?://(?:www\.)?nykaa\.com/[\w-]+/p/\d+'),
    "croma.com": re.compile(r'https?://(?:www\.)?croma\.com/[\w-]+/p/\d+'),
}

# General fallback pattern (less specific)
_GENERIC_PRODUCT_URL = re.compile(
    r'https?://(?:www\.)?(?:flipkart|amazon|myntra|nykaa|croma)\.com/'
    r'(?:[\w%-]+/)?(?:dp/[\w]{10}|p/[\w-]+|buy/\d+)',
    re.IGNORECASE,
)

# Relative (path-only) product URL patterns — Tavily's raw content often
# contains relative URLs like /dp/B0XXXXXX without the full domain.
_RELATIVE_PRODUCT_URLS = re.compile(
    r'/(?:dp/[\w]{10,}|p/[\w-]{8,}|buy/\d+)',
    re.IGNORECASE,
)

# Domain-specific mapping for relative URL reconstruction.
# /dp/ pattern is Amazon; /p/ pattern is Flipkart/Myntra/Nykaa/Croma.
_RELATIVE_PATTERN_DOMAINS: Dict[str, List[str]] = {
    "/dp/": ["amazon.in"],
    "/p/": ["flipkart.com", "myntra.com", "nykaa.com", "croma.com"],
    "/buy/": ["flipkart.com"],
}

_RELATIVE_URL_PREFIXES: Dict[str, str] = {
    "amazon.in": "https://www.amazon.in",
    "flipkart.com": "https://www.flipkart.com",
    "myntra.com": "https://www.myntra.com",
    "nykaa.com": "https://www.nykaa.com",
    "croma.com": "https://www.croma.com",
}


def _reconstruct_relative_url(path: str, source_domain: str = "") -> List[str]:
    """
    Reconstruct full product URLs from a relative path.

    Uses path patterns (/dp/, /p/, /buy/) to determine likely domains,
    and optionally restricts to source_domain when known.
    """
    results: List[str] = []

    # Determine candidate domains based on path pattern
    candidates: List[str] = []
    for pattern, domains in _RELATIVE_PATTERN_DOMAINS.items():
        if pattern in path.lower():
            candidates.extend(domains)

    # If no pattern matched, try all domains
    if not candidates:
        candidates = list(_RELATIVE_URL_PREFIXES.keys())

    # If source_domain is known and is a valid candidate, use only that
    if source_domain and source_domain in candidates:
        prefix = _RELATIVE_URL_PREFIXES.get(source_domain)
        if prefix:
            return [prefix + path]

    # Otherwise use deduplicated candidates
    seen: set = set()
    for d in candidates:
        if d not in seen:
            seen.add(d)
            prefix = _RELATIVE_URL_PREFIXES.get(d)
            if prefix:
                results.append(prefix + path)

    return results


def extract_product_urls(text: str, source_domain: str = "") -> List[str]:
    """
    Scan raw text for individual product page URLs.

    Handles both absolute URLs (https://...) and relative paths (/dp/..., /p/...)
    that are common in Tavily's extracted content.

    Args:
        text: Raw text to scan.
        source_domain: If provided, prefer patterns for this domain.

    Returns:
        Unique product page URLs (max 10).
    """
    found: List[str] = []
    domain_patterns = _PRODUCT_URL_PATTERNS

    # 1. Match absolute URLs (full domain + path)
    if source_domain and source_domain in domain_patterns:
        absolute_patterns = [domain_patterns[source_domain]]
    else:
        absolute_patterns = list(domain_patterns.values()) + [_GENERIC_PRODUCT_URL]

    for pat in absolute_patterns:
        for m in pat.finditer(text):
            url = m.group(0).rstrip("/").rstrip(")").rstrip("?").rstrip("&")
            if url and url not in found:
                found.append(url)

    # 2. Match relative paths (/dp/..., /p/...) and reconstruct full URLs
    for m in _RELATIVE_PRODUCT_URLS.finditer(text):
        path = m.group(0)
        # Skip if this relative path was already matched as part of an absolute URL
        skip = False
        for abs_url in found:
            if path in abs_url:
                skip = True
                break
        if skip:
            continue
        for full_url in _reconstruct_relative_url(path, source_domain):
            if full_url not in found:
                found.append(full_url)

    # Deduplicate (strip query params for dedup, but keep original otherwise)
    seen: set = set()
    unique: List[str] = []
    for u in found:
        norm = u.split("?")[0].rstrip("/").lower()
        if norm not in seen:
            seen.add(norm)
            unique.append(u)

    return unique[:10]  # max 10 product pages


def clean_page_content(raw: str, source_domain: str = "") -> Tuple[str, List[str], List[str]]:
    """
    Strip navigation/HTML garbage from Tavily raw_content.
    Returns (cleaned_text, image_urls_found, product_urls_found).

    Product URLs are extracted from the RAW (uncleaned) text using both
    absolute (https://www.amazon.in/dp/...) and relative (/dp/B0XXX) patterns.
    """
    # Extract product URLs from raw text BEFORE cleaning strips links
    product_urls = extract_product_urls(raw, source_domain)

    image_urls: List[str] = []
    lines = raw.split("\n")
    cleaned: List[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        low = line.lower()

        # Capture product image URLs from markdown images (even inside markdown links)
        for img_m in re.finditer(r"!\[.*?\]\(([^)]+)\)", line):
            url = _clean_image_url(img_m.group(1))
            if not url:
                continue
            # Skip tracking pixels, nav sprites, logos, icons
            low_url = url.lower()
            if any(s in low_url for s in ("fls-", "sprite", "1x1", "pixel",
                                           "tracking", "nav-", "spacer",
                                           "transparent", "blank", "loading",
                                           "logo", "icon", "gno/")):
                continue
            # Only keep /images/I/ for Amazon (actual product images, not nav/assets)
            if "amazon" in low_url and "/images/I/" not in low_url:
                continue
            # Skip common non-product image CDN patterns
            if "assets." in low_url and "myntra" not in low_url:
                continue
            if url not in image_urls:
                image_urls.append(url)

        # Skip lines that are ONLY markdown images (possibly nested in links)
        img_only = re.sub(r"\[!\[.*?\]\([^)]*\)\]\([^)]*\)", "", line).strip()
        img_only = re.sub(r"!\[.*?\]\([^)]*\)", "", img_only).strip()
        if not img_only:
            continue

        # Skip lines that are just numbers, punctuation, or whitespace
        # BUT keep lines containing ₹ followed by digits (prices)
        if "₹" in line and re.search(r"₹\s*\d", line):
            pass  # keep price lines
        elif re.fullmatch(r"[\d.,%\-+\s\^\[\]()#/\\:;\"'!?@&*_=|<>~`$₹]+", line):
            continue

        # Skip known navigation noise
        if any(noise in low for noise in _NAV_NOISE):
            continue

        # Skip sidebar/nav filter lines
        if _is_nav_line(line):
            continue

        # Strip markdown link syntax: [text](url) -> text
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)

        # Remove base64 data URIs
        if "data:image" in low or "base64" in low:
            continue

        # Remove tracking pixel references
        if "fls-" in low and ("amazon" in low or "flipkart" in low):
            continue
        if "sprites" in low or "1x1" in low:
            continue

        # Remove CSS/HTML class references (lines starting with . or #)
        if line.startswith(".") or line.startswith("#"):
            continue

        cleaned.append(line)

    text = "\n".join(cleaned)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), image_urls, product_urls


def extract_images_from_content(content: str) -> List[str]:
    """Extract product image URLs from raw content."""
    urls: List[str] = []
    skip_patterns = ["icon", "logo", "sprite", "fls-", "1x1", "pixel", "tracking",
                     "nav-", "spacer", "transparent", "blank", "loading"]
    for m in re.finditer(r"https?://[^\s]+\.(?:jpe?g|png|gif|webp)(?:\?[^\s]*)?", content, re.IGNORECASE):
        url = m.group()
        low_url = url.lower()
        if any(s in low_url for s in skip_patterns):
            continue
        if url not in urls:
            urls.append(url)
    return urls[:5]  # max 5 images


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _resolve_source(url: str) -> str:
    """
    Extract the bare domain from a URL and normalise it to one of the
    known source domains (e.g. 'www.flipkart.com' -> 'flipkart.com').
    """
    url_lower = url.lower()
    for domain in SUPPORTED_DOMAINS:
        if domain in url_lower:
            return domain
    # Fallback: strip scheme + www
    match = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url_lower)
    return match.group(1) if match else url_lower


def _deduplicate(results: List[TavilyResult]) -> List[TavilyResult]:
    """Remove duplicate results by URL while preserving insertion order."""
    seen: set = set()
    unique: List[TavilyResult] = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            unique.append(r)
    return unique


def _merge_extracted_content(
    results: List[TavilyResult],
    extracted: Dict[str, Dict[str, str]],
) -> None:
    """
    In-place merge: attach cleaned extracted text and title to matching results.
    Falls back to the shorter snippet if extraction did not succeed.
    """
    for r in results:
        if r.url in extracted:
            entry = extracted[r.url]
            raw = entry["text"]
            title = entry["title"]
            cleaned, images, product_urls = clean_page_content(raw, r.source)
            r.raw_content = cleaned
            if title and not r.title:
                r.title = title
            r._images = images  # type: ignore[attr-defined]
            r._product_urls = product_urls  # type: ignore[attr-defined]
        else:
            r.raw_content = r.content  # graceful fallback
            r._images = []  # type: ignore[attr-defined]
            r._product_urls = []  # type: ignore[attr-defined]
