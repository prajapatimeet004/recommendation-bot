import os
import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import quote

from backend.services.pipeline_logger import get_apify_logger

logger = get_apify_logger()

class ApifyService:
    def __init__(self):
        self.api_token = os.environ.get("APIFY_API_TOKEN", "").strip()

    async def discover_products(self, intent: Dict[str, Any]) -> List[Dict[str, Any]]:
        # 1. Check if token is available
        if not self.api_token:
            logger.info("APIFY_API_TOKEN not found in environment. Running simulation fallback.")
            return await self._simulate_discovery(intent)

        # 2. Generate search URLs based on search_queries
        queries = intent.get("search_queries", [])
        if not queries:
            queries = [intent.get("subcategory", "products")]

        urls = []
        for q in queries[:4]:  # Limit to top 4 queries to keep it fast
            encoded_q = quote(q)
            # Add Amazon
            urls.append(f"https://www.amazon.in/s?k={encoded_q}")
            # Add Flipkart
            urls.append(f"https://www.flipkart.com/search?q={encoded_q}")
            # Add Croma
            urls.append(f"https://www.croma.com/search/?text={encoded_q}")

        logger.info("Apify product discovery started with %d search URL(s)", len(urls))

        input_data = {
            "listingUrls": [{"url": url} for url in urls],
            "maxProductResults": 10,
            "scrapeMode": "AUTO"
        }

        # Call Apify actor synchronously (run act and get dataset items)
        # Using the actor 'apify/e-commerce-scraping-tool'
        actor_id = "apify~e-commerce-scraping-tool"
        run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={self.api_token}"

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(run_url, json=input_data)
                logger.info("Apify REST call completed. Status code: %d", resp.status_code)
                if resp.status_code in (200, 201):
                    items = resp.json()
                    if isinstance(items, list):
                        logger.info("Apify successfully crawled %d product(s)", len(items))
                        if items:
                            logger.info("Preview of first scraped product: %s", str(items[0])[:500])
                        return self._normalize_apify_items(items, intent.get("category", "other"))
                logger.warning("Apify actor run returned status %d. Falling back to simulation.", resp.status_code)
        except Exception as e:
            logger.exception("Apify actor execution failed: %s. Falling back to simulation.", e)

        return await self._simulate_discovery(intent)

    def _get_nested(self, item: Dict[str, Any], path: List[str]) -> Any:
        curr = item
        for key in path:
            if isinstance(curr, dict):
                curr = curr.get(key)
            else:
                return None
        return curr

    def _normalize_apify_items(self, items: List[Dict[str, Any]], default_cat: str) -> List[Dict[str, Any]]:
        normalized = []
        for item in items:
            name = item.get("name") or item.get("title") or ""
            if not name:
                continue

            price = self._get_nested(item, ["offers", "price"]) or item.get("price") or item.get("priceReal")
            if isinstance(price, str):
                price = self._clean_number(price)
            
            mrp = (self._get_nested(item, ["offers", "priceSpecification", "price"]) or 
                   self._get_nested(item, ["offers", "highPrice"]) or
                   item.get("mrp") or item.get("listPrice") or item.get("originalPrice"))
            if isinstance(mrp, str):
                mrp = self._clean_number(mrp)

            discount = item.get("discount") or item.get("discountPercentage")
            if isinstance(discount, str):
                discount = self._clean_number(discount)
            elif not discount and price and mrp and mrp > price:
                discount = round(((mrp - price) / mrp) * 100, 0)

            rating = self._get_nested(item, ["aggregateRating", "ratingValue"]) or item.get("rating") or item.get("stars")
            if isinstance(rating, str):
                rating = self._clean_number(rating)

            review_count = (self._get_nested(item, ["aggregateRating", "reviewCount"]) or
                            item.get("reviewsCount") or item.get("reviewCount") or item.get("reviews") or 0)
            if isinstance(review_count, str):
                review_count = int(self._clean_number(review_count))

            image_url = item.get("image") or item.get("imageUrl") or item.get("thumbnail") or ""
            if isinstance(image_url, list) and image_url:
                image_url = image_url[0]

            product_url = item.get("url") or item.get("productUrl") or item.get("sourceUrl") or ""
            
            source = item.get("source") or item.get("website") or ""
            if not source and product_url:
                from backend.services.tavily_service import _resolve_source
                source = _resolve_source(product_url)

            description = item.get("description") or item.get("aboutThisItem") or ""
            if isinstance(description, list):
                description = "\n".join(description)
            
            specs = item.get("specifications") or item.get("specs") or {}
            if not isinstance(specs, dict):
                specs = {"details": str(specs)}

            brand = self._get_nested(item, ["brand", "name"]) or item.get("brand") or "Generic"
            if isinstance(brand, dict):
                brand = brand.get("name") or "Generic"

            if brand == "Generic":
                from backend.services.regex_parser import _BRAND_PATTERN
                brand_match = _BRAND_PATTERN.search(name)
                if brand_match:
                    brand = brand_match.group(1).capitalize()

            normalized.append({
                "id": item.get("id") or product_url or f"apify-{abs(hash(name))}",
                "name": name,
                "brand": brand,
                "category": item.get("category") or default_cat,
                "subcategory": item.get("subcategory") or f"{default_cat}_general",
                "price": price,
                "mrp": mrp,
                "discount": discount,
                "rating": rating,
                "review_count": review_count,
                "image_url": image_url,
                "product_url": product_url,
                "description": description,
                "specifications": specs,
                "availability": item.get("availability") or "In Stock",
                "seller": item.get("seller") or brand,
                "source": source
            })
        import json
        logger.info("All scraped & normalized products (JSON format):\n%s", json.dumps(normalized, indent=2, default=str))
        return normalized

    def _clean_number(self, val_str: str) -> float:
        import re
        cleaned = re.sub(r"[^\d.]", "", val_str)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    async def _simulate_discovery(self, intent: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Simulate network crawl latency
        await asyncio.sleep(4.0)

        category = intent.get("category", "other")
        budget = intent.get("budget")
        style = intent.get("style")
        occasion = intent.get("occasion")
        brands = intent.get("brand_preference", [])

        preferred_brand = brands[0] if brands else "Brand"

        simulated = []

        if category == "smartphones":
            p1_price = budget * 0.85 if budget else 19999.0
            p2_price = budget * 0.72 if budget else 14999.0
            p3_price = budget * 0.94 if budget else 27999.0
            
            simulated.append({
                "name": f"{preferred_brand if preferred_brand != 'Brand' else 'OnePlus'} Nord CE4 Lite 5G (Super Silver, 8GB RAM, 128GB Storage)",
                "brand": preferred_brand if preferred_brand != "Brand" else "OnePlus",
                "price": p1_price,
                "mrp": p1_price * 1.15,
                "rating": 4.2,
                "review_count": 1824,
                "image_url": "https://m.media-amazon.com/images/I/61Io5-gQA+L._SL1500_.jpg",
                "product_url": "https://www.amazon.in/dp/B0D5Y7P7Z8",
                "description": "Powerful mid-range 5G smartphone with high refresh rate AMOLED display, Snapdragon processor, and superfast charging.",
                "specifications": {"ram": "8 GB", "storage": "128 GB", "battery": "5500 mAh", "processor": "Snapdragon 6 Gen 1"},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"{preferred_brand if preferred_brand != 'Brand' else 'Samsung'} Galaxy M35 5G (Daybreak Blue, 6GB RAM, 128GB Storage)",
                "brand": preferred_brand if preferred_brand != "Brand" else "Samsung",
                "price": p2_price,
                "mrp": p2_price * 1.25,
                "rating": 4.1,
                "review_count": 3490,
                "image_url": "https://m.media-amazon.com/images/I/81+GFFy8qFL._SL1500_.jpg",
                "product_url": "https://www.amazon.in/dp/B0DB1F5J94",
                "description": "Value flagship with massive battery, gorgeous sAMOLED display, and segment-leading security updates.",
                "specifications": {"ram": "6 GB", "storage": "128 GB", "battery": "6000 mAh", "display": "6.6 inch sAMOLED"},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"{preferred_brand if preferred_brand != 'Brand' else 'Realme'} Narzo 70 Pro 5G (Glass Green, 8GB RAM, 256GB Storage)",
                "brand": preferred_brand if preferred_brand != "Brand" else "Realme",
                "price": p3_price,
                "mrp": p3_price * 1.10,
                "rating": 4.3,
                "review_count": 892,
                "image_url": "https://m.media-amazon.com/images/I/71c6tWJ9ZlL._SL1500_.jpg",
                "product_url": "https://www.amazon.in/dp/B0CY5J8N9F",
                "description": "Sony IMX890 OIS camera smartphone with premium glass design and superfast charging support.",
                "specifications": {"ram": "8 GB", "storage": "256 GB", "camera": "50MP Sony IMX890", "battery": "5000 mAh"},
                "source": "amazon.in"
            })
        elif category in ("fashion", "clothing", "footwear"):
            p1_price = budget * 0.75 if budget else 799.0
            p2_price = budget * 0.90 if budget else 999.0
            p3_price = budget * 0.60 if budget else 599.0

            # Dynamic check for winter/ethnic query terms
            query_text = " ".join([str(kw) for kw in intent.get("keywords", [])] + [str(q) for q in intent.get("search_queries", [])]).lower()
            is_winter = any(w in query_text for w in ["winter", "cold", "jacket", "sweater", "hoodie", "cardigan", "coat", "woolen"])
            is_ethnic = any(w in query_text for w in ["navratri", "garba", "diwali", "festive", "ethnic", "kurta", "wedding", "marriage", "traditional", "saree", "chaniya", "choli", "koti", "sherwani"])

            if is_winter:
                simulated.append({
                    "name": f"Men's Classic Heavyweight Winter Fleece Jacket",
                    "brand": preferred_brand if preferred_brand != "Brand" else "Wildcraft",
                    "price": p1_price,
                    "mrp": p1_price * 1.5,
                    "rating": 4.3,
                    "review_count": 512,
                    "image_url": "https://images.unsplash.com/photo-1551028719-00167b16eac5?w=500",
                    "product_url": "https://www.amazon.in/dp/B0D5WINTER1",
                    "description": "Thick premium winter fleece jacket designed for insulation and outdoor cold protection. Features windproof zippers.",
                    "specifications": {"material": "Polyester Fleece", "pockets": "3 Zip Pockets", "closure": "Zipper"},
                    "source": "amazon.in"
                })
                simulated.append({
                    "name": f"Women's Cozy Knitted Winter Sweater Cardigan",
                    "brand": preferred_brand if preferred_brand != "Brand" else "H&M",
                    "price": p2_price,
                    "mrp": p2_price * 1.4,
                    "rating": 4.4,
                    "review_count": 891,
                    "image_url": "https://images.unsplash.com/photo-1620799140408-edc6dcb6d633?w=500",
                    "product_url": "https://www.myntra.com/sweaters/hm/women-knit-sweater/11468745/buy",
                    "description": "Loose fit knit sweater featuring soft rib-knit neck, drop shoulder long sleeves, and cozy warm feel.",
                    "specifications": {"material": "Acrylic-Wool Blend", "fit": "Regular Cozy Fit", "pattern": "Knit Cable"},
                    "source": "myntra.com"
                })
                simulated.append({
                    "name": f"Premium Unisex Woolen Winter Muffler & Beanie Combo Set",
                    "brand": "Generic",
                    "price": p3_price,
                    "mrp": p3_price * 1.8,
                    "rating": 4.2,
                    "review_count": 210,
                    "image_url": "https://images.unsplash.com/photo-1575413758035-3a37f23595ad?w=500",
                    "product_url": "https://www.amazon.in/dp/B0D5WINTER3",
                    "description": "Soft knitted warm winter cap and scarf matching combo. Excellent coverage against chilly winds.",
                    "specifications": {"material": "100% Soft Wool", "pieces": "Beanie + Muffler", "stretch": "One Size Fit"},
                    "source": "amazon.in"
                })
            elif is_ethnic:
                occ_val = occasion if occasion else "Festive"
                simulated.append({
                    "name": f"Men's Cotton Blend Traditional Straight Kurta Pajama Set for {occ_val}",
                    "brand": preferred_brand if preferred_brand != "Brand" else "Manyavar",
                    "price": p1_price,
                    "mrp": p1_price * 1.5,
                    "rating": 4.4,
                    "review_count": 920,
                    "image_url": "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=500",
                    "product_url": "https://www.myntra.com/kurta-sets/manyavar/men-traditional-kurta/24715999/buy",
                    "description": "Elegant traditional straight long kurta with white pajama set, perfect for festivals, weddings, and traditional events.",
                    "specifications": {"material": "Cotton Blend", "fit": "Regular Fit", "sleeve": "Full Sleeve", "occasion": f"{occ_val}"},
                    "source": "myntra.com"
                })
                simulated.append({
                    "name": f"Women's Designer Mirror Work Chaniya Choli Set for Navratri Garba",
                    "brand": preferred_brand if preferred_brand != "Brand" else "Biba",
                    "price": p2_price,
                    "mrp": p2_price * 1.6,
                    "rating": 4.5,
                    "review_count": 480,
                    "image_url": "https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=500",
                    "product_url": "https://www.myntra.com/chaniya-cholis/biba/women-navratri-set/11468750/buy",
                    "description": "Vibrant traditional Gujarati style chaniya choli with beautiful embroidery and real mirror work, perfect for Garba nights.",
                    "specifications": {"material": "Cotton-Rayon Blend", "fit": "Flared", "work": "Embroidery & Mirror Work", "occasion": "Garba / Navratri"},
                    "source": "myntra.com"
                })
                simulated.append({
                    "name": f"Women's Festive Wear Silk Blend Kurta Pant & Dupatta Set",
                    "brand": preferred_brand if preferred_brand != "Brand" else "W",
                    "price": p3_price,
                    "mrp": p3_price * 1.8,
                    "rating": 4.3,
                    "review_count": 673,
                    "image_url": "https://images.unsplash.com/photo-1617627143750-d86bc21e42bb?w=500",
                    "product_url": "https://www.myntra.com/kurta-sets/w/women-silk-blend-set/24715980/buy",
                    "description": "Premium look straight fit silk blend kurta with matching pants and floral printed dupatta set, perfect for festive wear.",
                    "specifications": {"material": "Silk Blend", "fit": "Straight Fit", "set_pieces": "Kurta, Pants, Dupatta", "occasion": f"{occ_val}"},
                    "source": "myntra.com"
                })
            else:
                style_label = style if style else "Beach"
                occ_label = occasion if occasion else "Goa Vacation"

                simulated.append({
                    "name": f"Men's Regular Fit Tropical {style_label} Print {occ_label} Shirt",
                    "brand": preferred_brand if preferred_brand != "Brand" else "Roadster",
                    "price": p1_price,
                    "mrp": p1_price * 1.8,
                    "rating": 4.1,
                    "review_count": 482,
                    "image_url": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=500",
                    "product_url": "https://www.myntra.com/shirts/roadster/men-tropical-print-shirt/2127876/buy",
                    "description": "Lightweight, breathable printed shirt perfect for summer vacations, beach wear, and casual outdoor styling.",
                    "specifications": {"material": "Viscose-Cotton Blend", "fit": "Regular Fit", "sleeve": "Half Sleeve", "pattern": "Tropical Print"},
                    "source": "myntra.com"
                })
                simulated.append({
                    "name": f"Unisex Oversized Cotton Graphic {style_label} T-Shirt for {occ_label}",
                    "brand": preferred_brand if preferred_brand != "Brand" else "H&M",
                    "price": p2_price,
                    "mrp": p2_price * 1.5,
                    "rating": 4.4,
                    "review_count": 1284,
                    "image_url": "https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=500",
                    "product_url": "https://www.myntra.com/tshirts/hm/oversized-printed-tshirt/11468732/buy",
                    "description": "Loose fit soft cotton tee with cool vacation/retro graphic prints. Ultra comfortable in warm weather.",
                    "specifications": {"material": "100% Pure Cotton", "fit": "Oversized Fit", "neck": "Round Neck"},
                    "source": "myntra.com"
                })
                simulated.append({
                    "name": f"Premium Linen Casual Solid Summer Shirt",
                    "brand": preferred_brand if preferred_brand != "Brand" else "Zara",
                    "price": p3_price,
                    "mrp": p3_price * 2.0,
                    "rating": 4.3,
                    "review_count": 673,
                    "image_url": "https://images.unsplash.com/photo-1598033129183-c4f50c736f10?w=500",
                    "product_url": "https://www.myntra.com/shirts/zara/men-linen-casual-shirt/24715956/buy",
                    "description": "Luxurious pure linen solid shirt featuring classic collar, button placket, and rolled-up sleeves detail.",
                    "specifications": {"material": "100% Pure Linen", "fit": "Slim Fit", "color": "Sand Beach White"},
                    "source": "myntra.com"
                })
        elif category == "beauty":
            p1_price = budget * 0.80 if budget else 799.0
            p2_price = budget * 0.90 if budget else 1299.0
            p3_price = budget * 0.55 if budget else 499.0

            simulated.append({
                "name": f"Hydrating Hyaluronic Acid Face Serum",
                "brand": preferred_brand if preferred_brand != "Brand" else "Neutrogena",
                "price": p1_price,
                "mrp": p1_price * 1.25,
                "rating": 4.5,
                "review_count": 1420,
                "image_url": "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=500",
                "product_url": "https://www.amazon.in/dp/B0D5BEAUTY1",
                "description": "Moisture-boosting facial serum formulated with concentrated hyaluronic acid. Restores hydration, plumps skin, and reduces fine lines.",
                "specifications": {"volume": "30 ml", "skin_type": "All skin types", "form": "Serum"},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"Ultra Sheer Dry-Touch Matte Sunscreen SPF 50+",
                "brand": preferred_brand if preferred_brand != "Brand" else "La Roche-Posay",
                "price": p2_price,
                "mrp": p2_price * 1.15,
                "rating": 4.6,
                "review_count": 892,
                "image_url": "https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?w=500",
                "product_url": "https://www.amazon.in/dp/B0D5BEAUTY2",
                "description": "Broad-spectrum daily matte sunscreen featuring clean, dry-touch finish. Prevents sun damage, dark spots, and redness.",
                "specifications": {"spf": "50+", "volume": "80 ml", "finish": "Matte Dry-Touch"},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"Gentle Foaming Daily Facial Cleanser",
                "brand": preferred_brand if preferred_brand != "Brand" else "Cetaphil",
                "price": p3_price,
                "mrp": p3_price * 1.20,
                "rating": 4.4,
                "review_count": 2180,
                "image_url": "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=500",
                "product_url": "https://www.amazon.in/dp/B0D5BEAUTY3",
                "description": "pH-balanced gentle foaming face wash that effectively deep-cleans pores without stripping natural hydration.",
                "specifications": {"volume": "125 ml", "skin_type": "Sensitive & Dry", "ph": "Balanced"},
                "source": "amazon.in"
            })
        else:
            p1_price = budget * 0.80 if budget else 4999.0
            p2_price = budget * 0.95 if budget else 8999.0
            p3_price = budget * 0.50 if budget else 2499.0

            simulated.append({
                "name": f"Premium {category.capitalize()} Gear {preferred_brand if preferred_brand != 'Brand' else ''}",
                "brand": preferred_brand if preferred_brand != "Brand" else "Generic",
                "price": p1_price,
                "mrp": p1_price * 1.3,
                "rating": 4.5,
                "review_count": 290,
                "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
                "product_url": "https://www.amazon.in/dp/B0DGENERIC1",
                "description": f"High performance {category} product suitable for {occasion if occasion else 'all daily needs'}.",
                "specifications": {"type": category, "brand": preferred_brand},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"Smart {category.capitalize()} Combo Pack for {style if style else 'Daily'} Use",
                "brand": preferred_brand if preferred_brand != "Brand" else "Generic",
                "price": p2_price,
                "mrp": p2_price * 1.4,
                "rating": 4.2,
                "review_count": 89,
                "image_url": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500",
                "product_url": "https://www.amazon.in/dp/B0DGENERIC2",
                "description": f"A comprehensive {category} kit designed for modern urban lifestyle.",
                "specifications": {"style": style, "occasion": occasion},
                "source": "amazon.in"
            })
            simulated.append({
                "name": f"Essential Budget {category.capitalize()} accessory",
                "brand": "Generic",
                "price": p3_price,
                "mrp": p3_price * 1.2,
                "rating": 4.0,
                "review_count": 510,
                "image_url": "https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=500",
                "product_url": "https://www.amazon.in/dp/B0DGENERIC3",
                "description": f"Affordable and high durability {category} accessory that provides extreme value for money.",
                "specifications": {"class": "budget"},
                "source": "amazon.in"
            })

        for p in simulated:
            p["category"] = category
            p["subcategory"] = f"{category}_general"
            p["id"] = p.get("id") or p["product_url"] or f"mock-{abs(hash(p['name']))}"
            p["discount"] = round(((p["mrp"] - p["price"]) / p["mrp"]) * 100, 0)
            p["availability"] = "In Stock"
            p["seller"] = p["brand"]

        import json
        logger.info("All simulated & normalized products (JSON format):\n%s", json.dumps(simulated, indent=2, default=str))
        return simulated
