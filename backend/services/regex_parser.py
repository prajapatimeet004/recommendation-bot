from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.models.product import ExtractedProduct

logger = logging.getLogger(__name__)

_PRICE_PATTERN = re.compile(r'(?:Rs\.?\s*|₹|INR\s*|MRP\s*[:]*\s*),?(\d[\d,]*)(?:\.\d{2})?', re.IGNORECASE)
_RATING_PATTERN = re.compile(r'([\d.]+)\s*(?:out\s*of\s*5|star|★|rating)', re.IGNORECASE)
_STRIP_CURRENCY = re.compile(r'[^\d.]')
_BRAND_PATTERN = re.compile(
    r'\b(Apple|Samsung|Xiaomi|Redmi|Realme|OnePlus|Oppo|Vivo|Nothing|Motorola|'
    r'Nokia|Poco|Infinix|Tecno|ASUS|Lenovo|HP|Dell|Acer|MSI|Sony|LG|Panasonic|'
    r'Google|Pixel|Boat|JBL|Bose|Sennheiser|Skullcandy|Jabra|Noise|Mivi|'
    r'Nike|Adidas|Puma|Reebok|Skechers|New\s*Balance|Under\s*Armour|Decathlon|'
    r'Wildcraft|Zara|H&M|Uniqlo|Levi\'?s|Wrangler|Tommy|Hilfiger|'
    r'Lakmé|Maybelline|L\'?Oréal|Loreal|MAC|Nykaa|Dot\s*&\s*Key|Minimalist|'
    r'Mamaearth|Mcaffeine|Plum|Biotique|Himalaya|Cetaphil|Neutrogena|'
    r'Sugar|Swissbeauty|Wow\s*Skin)\b',
    re.IGNORECASE,
)
_DISCOUNT_PATTERN = re.compile(r'(\d+)\s*%\s*OFF', re.IGNORECASE)

_SPEC_KEYS = [
    "ram", "storage", "display", "processor", "camera", "battery",
    "color", "size", "weight", "material", "connectivity",
    "warranty", "model", "screen", "resolution", "os",
]

_IMAGE_URL_PATTERN = re.compile(
    r'https?://[^\s"\'<>]+\.(?:jpe?g|png|gif|webp)(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE,
)

_AMAZON_NAV_BLOCKLIST = {
    "warranty", "authorized", "brand authorized", "return", "refund",
    "delivery", "fashion", "computers", "kitchen", "mobiles & accessories",
    "laptops & accessories", "tv & home entertainment", "computer peripherals",
    "smart technology", "replacement reason", "replacement period",
    "replacement policy", "cancellation policy", "refund policy",
    "warranty policy", "defective item", "physical damage",
    "wrong and missing item", "customer service", "gift cards",
    "amazon pay", "your account", "your orders", "sell on amazon",
    "best sellers", "new releases", "today's deals", "gift ideas",
    "electronics", "home & kitchen", "toys & games",
    "beauty & personal care", "sports, fitness & outdoors", "baby",
    "hello, sign in", "account & lists", "returns & orders",
    "delivering to", "update location", "need help", "help me decide",
    "buying guide", "sort by", "pay on delivery", "eligible for pay on delivery",
    "include out of stock", "skip to main", "previous", "next",
    "you are seeing this ad", "sponsored", "free delivery", "flat inr",
    "only few left", "coming soon", "bank offer", "amazon prime",
    "register for free", "see more", "see less", "filter", "clear filter",
    "customer review", "international brand", "item condition", "availability",
    "eligible", "free shipping", "display", "resolution",
    "subscribe & save", "audible", "music", "movies", "books",
    "m.r.p", "mrp", "list price", "price", "you save", "inclusive of all taxes",
    "custom products", "main content",
    "get it by", "only", "left in stock", "in stock",
    "skip to", "keyboard shortcuts", "image unavailable", "amazon fashion",
    "page", "you are viewing", "related to this item", "special offers",
    "product description", "product details", "technical details",
    "additional information", "customer reviews", "top reviews",
    "review this product", "tell the community", "amazon brand",
    "about this item", "bestsellers", "phones & wearables",
    "computers & tablets", "please note", "orders which exceed",
    "quantity limit", "auto-canceled", "make money with us",
    "amazon business", "discover more", "blog", "read more",
    "best quality", "regular fit", "slim fit", "breathable",
    "product information", "manufacturer details", "item weight",
    "item dimensions", "country of origin", "generic name",
    "net quantity", "included components", "seller",
    "customer questions", "answers", "search this page",
    "have a question", "find answers", "report incorrect",
    "›", "»",
}

_LIST_URL_PATTERN = re.compile(
    r'(/s\?k=|/s\?rh=|/b\?|/best-|/search\?|/s\?ref=|/q/|/clp/|/unboxed/|\?s=bazaar)',
    re.IGNORECASE,
)


def _clean_price(text: str) -> Optional[float]:
    match = _PRICE_PATTERN.search(text)
    if match:
        cleaned = re.sub(r'[^\d.]', '', match.group(1))
        try:
            val = float(cleaned)
            if 10 <= val <= 5_000_000:
                return val
        except ValueError:
            pass
    return None


def _extract_rating(text: str) -> Optional[float]:
    match = _RATING_PATTERN.search(text)
    if match:
        try:
            val = float(match.group(1))
            return min(val, 5.0) if val <= 5.0 else None
        except ValueError:
            pass
    return None


def _extract_brand(text: str, name: str = "") -> Optional[str]:
    for source in (text, name):
        match = _BRAND_PATTERN.search(source)
        if match:
            return match.group(1).strip()
    return None


def _extract_specs(text: str) -> Dict[str, str]:
    specs: Dict[str, str] = {}
    for key in _SPEC_KEYS:
        pat = re.compile(
            rf'(?:{re.escape(key)}|{key.capitalize()})\s*[:•\-\s]*\s*([^,\n]{{1,60}}?)(?=[,;\n]|\d+\s*(?:GB|TB|MP|Hz|inch|cm)|\s*(?:GB|TB|MP|Hz|inch|cm)\b)',
            re.IGNORECASE,
        )
        for match in pat.finditer(text):
            val = match.group(1).strip()
            if val and len(val) < 60 and not re.match(r'^[\d\W]+$', val):
                specs[key] = val
                break
    storage_match = re.search(r'(\d+\s*(?:GB|TB))\s*(?:Storage|ROM|Internal)', text, re.IGNORECASE)
    if storage_match and "storage" not in specs:
        specs["storage"] = storage_match.group(1)
    ram_match = re.search(r'(\d+\s*GB)\s*(?:RAM|Memory)', text, re.IGNORECASE)
    if ram_match and "ram" not in specs:
        specs["ram"] = ram_match.group(1)
    return specs


def _extract_image(text: str) -> Optional[str]:
    urls = _IMAGE_URL_PATTERN.findall(text)
    skip_keywords = ["sprite", "nav-", "fls-", "pixel", "1x1", "transparent", "blank", "logo", "icon", "spacer"]
    for url in urls:
        low = url.lower()
        if any(s in low for s in skip_keywords):
            continue
        if "images/" in low or "/i/" in low or "/img/" in low:
            return url
    return urls[0] if urls else None


def _is_amazon_nav_text(line: str) -> bool:
    low = line.lower().strip("* ").strip()
    if not low:
        return True
    if low.startswith("##") or low.startswith("!["):
        return True
    if "](/gp/cart/" in low or "](/cart/" in low:
        return True
    if any(blocked in low for blocked in _AMAZON_NAV_BLOCKLIST):
        return True
    if low.startswith("*") or low.startswith("|"):
        return True
    if len(low.split()) <= 2 and len(low) < 30:
        cleaned = low.strip("* ").strip()
        if cleaned in ("new", "used", "refurbished", "all", "premium", "value",
                       "standard", "express", "pickup", "delivery", "free",
                       "included", "available", "stock", "sale", "offer",
                       "deals", "coupons", "offers", "rewards", "prime",
                       "exclusive", "membership", "subscribe", "sign up", "save",
                       "sell", "best", "fresh", "women", "men", "kids", "buy again",
                       "top", "more", "home", "shop", "brands", "brand",
                       "category", "categories", "customer", "service"):
            return True
    return False


_BAD_NAME_PATTERNS = {
    "about this item", "bestsellers", "the best quality", "please note",
    "quantity limit", "auto-canceled", "orders which exceed", "skip to",
    "keyboard shortcuts", "image unavailable", "make money with us",
    "product description", "product details", "technical details",
    "additional information", "customer reviews", "top reviews",
    "review this product", "tell the community", "product information",
    "manufacturer details", "search this page", "have a question",
    "find answers", "report incorrect", "only few left", "coming soon",
    "bank offer", "free delivery", "free shipping", "you save",
    "inclusive of all taxes", "see more", "see less",
    "phones & wearables", "computers & tablets", "customer service",
    "sell on amazon", "register for free", "amazonbasics",
    "brand size", "size chart", "size guide", "delivery option",
    "bank offers", "exchange offer", "no cost emi",
    "specifications", "highlights", "ratings & reviews",
    "customer image", "customer video", "video review",
    "product image", "image caption", "customer photo",
    "stay cool", "positive ratings from", "share:",
    "read more", "learn more", "shop now", "buy now",
    "item details", "shipping information", "payment options",
    "secure transaction", "have a question", "find answers",
    "customer questions", "answers", "page 1 of", "page 2 of",
    "sort by", "filter by", "sort by popularity",
}


def _is_valid_product_name(name: str) -> bool:
    if not name or len(name) < 10:
        return False
    low = name.lower()
    if low.startswith(("it's", "this ", "i ", "my ", "we ", "you ", "the ", "a ", "very ", "would ", "great ")):
        return False
    special_ratio = sum(1 for c in name if not c.isalnum() and not c.isspace()) / max(len(name), 1)
    if special_ratio > 0.3:
        return False
    has_brand = _BRAND_PATTERN.search(name)
    has_spec = bool(re.search(r'\b(\d+\s*(GB|TB|MP|Hz|inch|cm|mm|Watt)|[A-Z][a-z]+[\s-]*\d+)', name))
    has_model = bool(re.search(r'([A-Z][a-z]+[\s-]*){2,}\d', name))
    if not (has_brand or has_spec or has_model):
        return False
    return True


def _clean_product_name(name: str) -> str:
    if not name:
        return ""
    cleaned = name.strip("* #-\t").strip()
    if not cleaned:
        return ""
    if cleaned.lower().startswith("buy ") and len(cleaned) > 10:
        cleaned = cleaned[4:]
    for suffix in [" at amazon.in", " at flipkart.com", " at myntra.com", " at croma.com"]:
        idx = cleaned.lower().find(suffix)
        if idx > 0:
            cleaned = cleaned[:idx]
    if "##" in cleaned:
        parts = [p.strip() for p in cleaned.split("##") if p.strip()]
        cleaned = parts[0] if parts else cleaned
    img_match = re.match(r'!\[.*?\]\(.*?\)\s*(.*)', cleaned, re.DOTALL)
    if img_match:
        cleaned = img_match.group(1).strip()
    low = cleaned.lower().strip()
    if low in _BAD_NAME_PATTERNS or low.startswith(tuple(_BAD_NAME_PATTERNS)):
        return ""
    if any(k in low for k in _BAD_NAME_PATTERNS if len(k) > 8):
        return ""
    if len(cleaned) < 5:
        return ""
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned.startswith("*") or cleaned.startswith("-") or cleaned.startswith("#") or cleaned.startswith("|"):
        return ""
    # Reject names that are clearly descriptions (end mid-sentence, start with verb)
    if len(cleaned) > 80 and any(k in cleaned.lower() for k in [" under pressure", " ensures ", " maintains ", " provides "]):
        return ""
    if not _is_valid_product_name(cleaned):
        return ""
    return cleaned[:150]


def _parse_amazon(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    if _LIST_URL_PATTERN.search(url):
        logger.debug("Skipping Amazon list/search page: %s", url)
        return None

    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    name = ""
    price = None
    mrp = None
    rating = None
    brand = None
    specs: Dict[str, str] = {}
    image = None

    for line in lines:
        low = line.lower()
        if "price" in low and ("product page" in low or ":" in low):
            prices = _PRICE_PATTERN.findall(line)
            if prices:
                raw = re.sub(r'[^\d.]', '', prices[0])
                try:
                    price = float(raw) if raw else None
                except ValueError:
                    pass
                if len(prices) > 1:
                    raw2 = re.sub(r'[^\d.]', '', prices[1])
                    try:
                        mrp = float(raw2) if raw2 else None
                    except ValueError:
                        pass

    # Primary strategy: look for a product title line with known brand or specs
    if not name:
        for line in lines:
            low = line.lower()
            if _is_amazon_nav_text(line):
                continue
            if len(line) < 10 or len(line) > 300:
                continue
            has_brand = _BRAND_PATTERN.search(line)
            has_spec = bool(re.search(r'\b(\d+\s*(GB|TB|MP|Hz|inch|cm|mm)|[A-Z0-9]{4,})\b', line, re.IGNORECASE))
            if has_brand or has_spec:
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    # Secondary strategy: find first non-boilerplate line that looks like a title
    if not name:
        for line in lines:
            if _is_amazon_nav_text(line):
                continue
            if len(line) > 20 and len(line) < 200:
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    # Fallback: anything > 20 chars with extended exclusion list
    if not name:
        fallback_exclude = {"bought", "rating", "review", "m.r.p", "price", "warranty",
                            "authorized", "brand authorized", "return", "refund",
                            "delivery", "fashion", "computers", "kitchen",
                            "customer service", "amazon pay", "your order",
                            "sell on amazon", "best seller", "new release",
                            "today's deal", "gift idea", "electronics",
                            "home & kitchen", "toys & games", "beauty",
                            "sports", "fitness", "outdoors", "baby",
                            "subscribe", "save", "audible", "music",
                            "movies", "books", "free delivery",
                            "only few left", "coming soon", "bank offer",
                            "amazon prime", "sponsored", "advertisement",
                            "image unavailable", "skip to", "cart", "best quality"}
        for line in lines:
            low = line.lower()
            if len(line) > 20 and not any(k in low for k in fallback_exclude):
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    # Fallback: use Tavily title
    if not name and fallback_title:
        candidate = _clean_product_name(fallback_title)
        if candidate:
            name = candidate

    if name:
        name = _clean_product_name(name)

    rating = _extract_rating(content)
    if not price:
        for line in lines:
            p = _clean_price(line)
            if p and p >= 100:
                price = p
                break
    # Fallback price from title or snippet
    if not price:
        for src in (fallback_title, fallback_snippet):
            if src:
                p = _clean_price(src)
                if p and p >= 100:
                    price = p
                    break
    if name:
        name = _clean_product_name(name)
    brand = _extract_brand(content, name)
    image = _extract_image(content)
    specs = _extract_specs(content)

    if not name:
        return None

    discount = None
    if price and mrp and mrp > price:
        discount = round((mrp - price) / mrp * 100, 1)
    elif "\u20b9" in content:
        dm = _DISCOUNT_PATTERN.search(content)
        if dm:
            discount = float(dm.group(1))

    return ExtractedProduct(
        name=name,
        brand=brand,
        price=price,
        mrp=mrp,
        discount=discount,
        image_url=image,
        product_url=url,
        rating=rating,
        specifications=specs,
        description=name,
        category=None,
        tags=[brand.lower()] if brand else [],
        source="amazon.in",
    )


def _parse_flipkart(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    name = ""
    price = None
    mrp = None
    rating = None
    brand = None
    specs: Dict[str, str] = {}
    image = None

    for i, line in enumerate(lines):
        low = line.lower()
        if "₹" in line or "rs" in low:
            p = _clean_price(line)
            if p:
                if not price:
                    price = p
                elif p > (price or 0) * 1.05 and not mrp:
                    mrp = p
        if not name and len(line) > 25 and not any(k in low for k in ["rating", "review", "seller", "delivery", "price"]):
            name = re.sub(r'\s+', ' ', line).strip()[:200]
        if "rating" in low or "★" in line or "star" in low:
            r = _extract_rating(line)
            if r:
                rating = r

    if not name:
        for line in lines:
            if len(line) > 20 and not any(k in line.lower() for k in ["price", "delivery", "seller", "rating", "₹", "rs"]):
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    if not name and fallback_title:
        candidate = _clean_product_name(fallback_title)
        if candidate:
            name = candidate

    if not price:
        for src in (fallback_title, fallback_snippet):
            if src:
                p = _clean_price(src)
                if p and p >= 100:
                    price = p
                    break

    if name:
        name = _clean_product_name(name)
    brand = _extract_brand(content, name)
    image = _extract_image(content)
    specs = _extract_specs(content)

    if not name:
        return None

    discount = None
    if price and mrp and mrp > price:
        discount = round((mrp - price) / mrp * 100, 1)
    elif "\u20b9" in content:
        dm = _DISCOUNT_PATTERN.search(content)
        if dm:
            discount = float(dm.group(1))

    return ExtractedProduct(
        name=name,
        brand=brand,
        price=price,
        mrp=mrp,
        discount=discount,
        image_url=image,
        product_url=url,
        rating=rating,
        specifications=specs,
        description=name,
        category=None,
        tags=[brand.lower()] if brand else [],
        source="flipkart.com",
    )


def _parse_myntra(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    name = ""
    price = None
    mrp = None
    rating = None
    brand = None
    specs: Dict[str, str] = {}
    image = None

    for line in lines:
        low = line.lower()
        if "₹" in line or "rs" in low:
            p = _clean_price(line)
            if p:
                if not price:
                    price = p
                elif p > (price or 0) * 1.05 and not mrp:
                    mrp = p
        if not name and len(line) > 15 and not any(k in low for k in ["rating", "size", "delivery", "price"]):
            name = re.sub(r'\s+', ' ', line).strip()[:200]
        if "rating" in low or "★" in line:
            r = _extract_rating(line)
            if r:
                rating = r

    if not name:
        for line in lines:
            if len(line) > 15 and not any(k in line.lower() for k in ["price", "₹", "size", "delivery"]):
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    if not name and fallback_title:
        candidate = _clean_product_name(fallback_title)
        if candidate:
            name = candidate

    if not price:
        for src in (fallback_title, fallback_snippet):
            if src:
                p = _clean_price(src)
                if p and p >= 100:
                    price = p
                    break

    if name:
        name = _clean_product_name(name)
    brand = _extract_brand(content, name)
    image = _extract_image(content)
    specs = _extract_specs(content)

    if not name:
        return None

    discount = None
    if price and mrp and mrp > price:
        discount = round((mrp - price) / mrp * 100, 1)
    else:
        dm = _DISCOUNT_PATTERN.search(content)
        if dm:
            discount = float(dm.group(1))

    return ExtractedProduct(
        name=name,
        brand=brand,
        price=price,
        mrp=mrp,
        discount=discount,
        image_url=image,
        product_url=url,
        rating=rating,
        specifications=specs,
        description=name,
        category="fashion",
        tags=[brand.lower()] if brand else [],
        source="myntra.com",
    )


def _parse_nykaa(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    return _parse_generic(content, url, "nykaa.com", fallback_title, fallback_snippet)


def _parse_croma(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    return _parse_generic(content, url, "croma.com", fallback_title, fallback_snippet)


def _parse_ajio(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    return _parse_generic(content, url, "ajio.com", fallback_title, fallback_snippet)


def _parse_generic(content: str, url: str, source: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    name = ""
    price = None
    mrp = None
    rating = None
    brand = None
    specs: Dict[str, str] = {}
    image = None

    for line in lines:
        low = line.lower()
        if "₹" in line or "rs" in low:
            p = _clean_price(line)
            if p:
                if not price:
                    price = p
                elif p > (price or 0) * 1.05 and not mrp:
                    mrp = p
        if not name and len(line) > 15 and not any(k in low for k in ["rating", "price", "delivery"]):
            name = re.sub(r'\s+', ' ', line).strip()[:200]
        if "rating" in low or "★" in line:
            r = _extract_rating(line)
            if r:
                rating = r

    if not name:
        for line in lines:
            if len(line) > 15 and not any(k in line.lower() for k in ["price", "₹", "delivery"]):
                name = re.sub(r'\s+', ' ', line).strip()[:200]
                break

    if not name and fallback_title:
        candidate = _clean_product_name(fallback_title)
        if candidate:
            name = candidate

    if not price:
        for src in (fallback_title, fallback_snippet):
            if src:
                p = _clean_price(src)
                if p and p >= 100:
                    price = p
                    break

    if name:
        name = _clean_product_name(name)
    brand = _extract_brand(content, name)
    image = _extract_image(content)
    specs = _extract_specs(content)

    if not name:
        return None

    discount = None
    if price and mrp and mrp > price:
        discount = round((mrp - price) / mrp * 100, 1)

    return ExtractedProduct(
        name=name,
        brand=brand,
        price=price,
        mrp=mrp,
        discount=discount,
        image_url=image,
        product_url=url,
        rating=rating,
        specifications=specs,
        description=name,
        category=None,
        tags=[brand.lower()] if brand else [],
        source=source,
    )


_SOURCE_PARSERS = {
    "amazon.in": _parse_amazon,
    "flipkart.com": _parse_flipkart,
    "myntra.com": _parse_myntra,
    "nykaa.com": _parse_nykaa,
    "croma.com": _parse_croma,
    "ajio.com": _parse_ajio,
}


def parse_product(content: str, url: str, fallback_title: str = "", fallback_snippet: str = "") -> Optional[ExtractedProduct]:
    if not url:
        return None
    source = _resolve_source(url)
    named_parser = _SOURCE_PARSERS.get(source)
    try:
        if named_parser:
            return named_parser(content, url, fallback_title, fallback_snippet)
        return _parse_generic(content, url, source, fallback_title, fallback_snippet)
    except Exception as exc:
        logger.warning("Regex parser failed for %s (%s): %s", url, source, exc)
        return None


def parse_products(tavily_results: list) -> list[ExtractedProduct]:
    seen_urls: set = set()
    products: list[ExtractedProduct] = []

    for result in tavily_results:
        raw_content = getattr(result, "raw_content", None) or ""
        snippet = getattr(result, "content", None) or ""
        title = getattr(result, "title", "") or ""
        content = (title + "\n" + raw_content) if raw_content else (snippet if snippet else title)
        url = getattr(result, "url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        if _LIST_URL_PATTERN.search(url):
            logger.debug("Skipping list/search page: %s", url)
            continue

        product = parse_product(content, url, title, snippet)
        if product:
            products.append(product)

    return products


def _resolve_source(url: str) -> str:
    url_lower = url.lower()
    for domain in _SOURCE_PARSERS:
        if domain in url_lower:
            return domain
    match = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url_lower)
    return match.group(1) if match else url_lower
