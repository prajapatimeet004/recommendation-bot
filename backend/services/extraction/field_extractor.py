import re
from urllib.parse import urlparse
from typing import Dict, Any, List

class FieldExtractor:
    COMMON_BRANDS = [
        "samsung", "apple", "xiaomi", "redmi", "oneplus", "oppo", "vivo", "realme", "nothing",
        "motorola", "poco", "hmd", "lenovo", "asus", "dell", "hp", "acer", "sony", "nike", "adidas",
        "puma", "reebok", "bata", "woodland", "casio", "titan", "fossil", "fastrack", "boat"
    ]

    @classmethod
    async def extract_fields(cls, block: str, url: str) -> Dict[str, Any]:
        parsed_url = urlparse(url)
        source = parsed_url.netloc.replace("www.", "") or "local"

        # 1. Product URL
        product_url = url
        link_matches = re.findall(r'\[(?:Buy now|View|Product|\w+[^\]]*)\]\(([^\)]+)\)', block)
        if not link_matches:
            link_matches = re.findall(r'\[[^\]]*\]\(([^\)]+)\)', block)
        
        if link_matches:
            match_url = link_matches[0].strip()
            if match_url.startswith("/"):
                product_url = f"https://{source}{match_url}"
            elif match_url.startswith("http"):
                product_url = match_url

        # 2. Image URL
        image_url = ""
        img_matches = re.findall(r'!\[[^\]]*\]\(([^\)]+)\)', block)
        if not img_matches:
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', block)
        if img_matches:
            image_url = img_matches[0]

        # 3. Product Name
        name = ""
        header_match = re.search(r'###\s+\[([^\]]+)\]|###\s+([^\n]+)|##\s+([^\n]+)', block)
        if header_match:
            name = (header_match.group(1) or header_match.group(2) or header_match.group(3)).strip()
        else:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if lines:
                name = lines[0]
        name = re.sub(r'[\*\[\]#]', '', name).strip()

        # 4. Brand
        brand = "Generic"
        for b in cls.COMMON_BRANDS:
            if re.search(rf'\b{b}\b', name, re.IGNORECASE) or re.search(rf'\b{b}\b', block, re.IGNORECASE):
                brand = b.capitalize()
                break

        # 5. Prices
        price = None
        mrp = None
        discount = None

        mrp_match = re.search(r'M\.?R\.?P\.?\s*[:\-₹]?\s*(?:Rs\.?|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)', block, re.IGNORECASE)
        if mrp_match:
            mrp = cls._parse_price(mrp_match.group(1))

        price_matches = re.findall(r'(?:₹|Rs\.?)\s*(\d+(?:,\d+)*(?:\.\d+)?)', block)
        if price_matches:
            parsed_prices = [cls._parse_price(p) for p in price_matches]
            if mrp:
                lower_prices = [p for p in parsed_prices if p < mrp]
                price = lower_prices[0] if lower_prices else parsed_prices[0]
            else:
                price = parsed_prices[0]

        discount_match = re.search(r'(\d+)\s*%\s*off', block, re.IGNORECASE)
        if discount_match:
            discount = float(discount_match.group(1))

        # 6. Ratings & Reviews
        rating = None
        review_count = 0

        rating_match = re.search(r'(\d+\.?\d*)\s*(?:out of 5 stars|★|star)', block, re.IGNORECASE)
        if rating_match:
            rating = float(rating_match.group(1))

        review_match = re.search(r'(\d+(?:,\d+)*)\s*Rating[s]?|(\d+(?:,\d+)*)\s*Review[s]?', block, re.IGNORECASE)
        if review_match:
            val = review_match.group(1) or review_match.group(2)
            review_count = int(val.replace(",", ""))

        # 7. Specifications
        specifications = {}
        ram_match = re.search(r'(\d+\s*GB\s*RAM)', block, re.IGNORECASE)
        if ram_match:
            specifications["ram"] = ram_match.group(1).strip()
        storage_match = re.search(r'(\d+\s*GB\s*(?:ROM|Storage))', block, re.IGNORECASE)
        if storage_match:
            specifications["storage"] = storage_match.group(1).strip()
        cpu_match = re.search(r'\b(Snapdragon\s*\d+|Dimensity\s*\d+|Helio\s*\w+)\b', block, re.IGNORECASE)
        if cpu_match:
            specifications["processor"] = cpu_match.group(1).strip()
        screen_match = re.search(r'(\d+\.?\d*)\s*(?:inch|")\s*(?:Display|Screen)?', block, re.IGNORECASE)
        if screen_match:
            specifications["display_size"] = f"{screen_match.group(1)} inch"

        # 8. Availability
        availability = "In Stock"
        if re.search(r'out of stock|currently unavailable|sold out', block, re.IGNORECASE):
            availability = "Out of Stock"

        # 9. Seller
        seller_match = re.search(r'sold\s*by\s*([^\n,|]+)', block, re.IGNORECASE)
        seller = seller_match.group(1).strip() if seller_match else brand

        # 10. Category & Subcategory
        category = "general"
        subcategory = "general"
        if re.search(r'phone|mobile|smartphone|galaxy|iphone|redmi|realme|oppo|vivo', name, re.IGNORECASE):
            category = "smartphones"
            subcategory = "mobile_phones"
        elif re.search(r'laptop|notebook|macbook|chromebook', name, re.IGNORECASE):
            category = "laptops"
            subcategory = "portable_computers"
        elif re.search(r'dress|t-shirt|shirt|kurta|clothing|jeans|pants|wear', name, re.IGNORECASE):
            category = "clothing"
            subcategory = "apparel"
        elif re.search(r'shoe|sneaker|boot|sandal|footwear', name, re.IGNORECASE):
            category = "shoes"
            subcategory = "footwear"
        elif re.search(r'watch|smartwatch|chronograph', name, re.IGNORECASE):
            category = "watches"
            subcategory = "timepieces"

        # 11. Description
        desc_lines = block.split("\n")[1:]
        description = "\n".join([l.strip() for l in desc_lines if l.strip()])

        return {
            "name": name,
            "brand": brand,
            "category": category,
            "subcategory": subcategory,
            "price": price,
            "mrp": mrp,
            "discount": discount,
            "rating": rating,
            "review_count": review_count,
            "image_url": image_url,
            "product_url": product_url,
            "availability": availability,
            "description": description,
            "specifications": specifications,
            "variants": [],
            "colors": [],
            "sizes": [],
            "seller": seller,
            "source": source
        }

    @staticmethod
    def _parse_price(text: str) -> float:
        clean = text.replace(",", "").strip()
        try:
            return float(clean)
        except ValueError:
            return 0.0
