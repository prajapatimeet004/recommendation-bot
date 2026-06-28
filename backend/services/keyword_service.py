from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional


from backend.services.llm_gateway import LLMGateway
from backend.services.pipeline_logger import get_pipeline_logger

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

_INTENT_KEYWORD_PROMPT = """\
You are a shopping intent classifier, keyword generation engine, and category classifier for an Indian e-commerce assistant.

## Task
Analyze the user's message and return a JSON object with exactly three fields:
1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `keywords` — approximately 10 intelligent shopping search keywords
3. `category` — the most appropriate canonical product category, one of: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, other

## Intent Definitions
- RECOMMEND: user wants product suggestions (keywords: suggest, recommend, best, find, buy, need, looking for, help me choose)
- COMPARE: user wants to compare products (keywords: compare, versus, vs, difference between)
- FOLLOW_UP: user is asking follow-up on previously shown products (keywords: show more, more options, tell me about, what about, how about)
- BUNDLE: user wants a lifestyle bundle or kit (keywords: kit, bundle, setup, combo, everything for, full gear)
- GENERAL: off-topic or non-shopping message
- EXPLAIN: user wants explanation of product features, specs, or technology
- GREETING: greeting, thank you, hello, hi, bye

## Category Definitions
- smartphones: mobile phones, cellphones, iPhones, androids, accessories like phone cases
- laptops: notebooks, MacBooks, gaming laptops
- fashion: clothing, shirts, t-shirts, jeans, dresses, sarees, jackets, hoodies
- beauty: cosmetics, skincare, lipstick, foundation, sunscreen, shampoo, moisturizer
- footwear: shoes, sneakers, sandals, boots, heels
- home_appliances: refrigerators, washing machines, air conditioners, TVs, microwave ovens, kitchen appliances
- electronics: headphones, smartwatches, cameras, tablets, speaker systems, general tech accessories
- other: anything else that does not fit the above categories

## Keyword Generation Rules
- Generate approximately 10 diverse, specific shopping keywords
- Do NOT simply repeat the user's words — infer context
- Account for Indian market, seasons, occasions, and lifestyle
- Keywords should maximize product discovery across Flipkart, Amazon.in, Myntra, Nykaa, Croma, Ajio

## Examples

User: "I need clothes for Navratri"
Response: {"intent": "RECOMMEND", "keywords": ["Navratri Kurta", "Traditional Kurta", "Ethnic Wear", "Festival Wear", "Kurta Pajama", "Mirror Work Kurta", "Navratri Collection", "Men Ethnic Wear", "Women's Ethnic Wear", "Garba Outfit"], "category": "fashion"}

User: "Phone for photography"
Response: {"intent": "RECOMMEND", "keywords": ["Camera Phone", "50MP Camera", "OIS Smartphone", "Flagship Camera", "Night Photography Phone", "Photography Smartphone", "AMOLED Phone", "4K Video Recording Phone", "Optical Zoom Phone", "Portrait Camera Phone"], "category": "smartphones"}

User: "Compare iPhone and Samsung"
Response: {"intent": "COMPARE", "keywords": ["iPhone 16 Pro", "Samsung Galaxy S25 Ultra", "iPhone vs Samsung comparison", "Flagship smartphone", "Premium phone"], "category": "smartphones"}

User: "I'm joining a gym"
Response: {"intent": "BUNDLE", "keywords": ["Gym shoes men", "Workout clothes", "Gym bag", "Gym equipment", "Activewear", "Gym kit", "Fitness accessories", "Protein supplements", "Dumbbell set", "Yoga mat"], "category": "other"}

Return ONLY valid JSON. No markdown, no explanation."""


_DETAILED_INTENT_PROMPT_WITH_CONTEXT = """\
You are an advanced shopping intent parser for an e-commerce assistant.

## Conversation History
Below is the recent conversation history. Use it to understand references like "that product", "accessories for it", "show me more like this", etc.
{conversation_context}

## Current Message
{user_message}

## Task
Analyze the user's CURRENT MESSAGE in the context of the conversation history above.
Return a valid JSON object with the following fields:
1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `category` — canonical category: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, or other
3. `subcategory` — specific product subcategory (e.g. mobile_phones, casual_tshirts, running_shoes, face_cream, etc.)
4. `budget` — maximum price limit if specified (integer in INR, or null if not specified)
5. `occasion` — usage occasion (e.g., Goa trip, gym, wedding, office, daily, or null)
6. `style` — style profile (e.g. oversized, casual, formal, traditional, sporty, or null)
7. `brand_preference` — list of preferred brands mentioned (e.g., ["Apple", "Samsung"] or empty list [])
8. `keywords` — list of approximately 10 optimized search keywords (INCLUDE context from history — e.g. if user previously searched for "Samsung tablet" and now asks for "accessories", keywords should include "Samsung tablet accessories", "Samsung Tab case", etc.)
9. `search_queries` — list of 5 to 10 optimized shopping search query phrases

Return ONLY a valid JSON object. Do not include markdown formatting or extra text.

Example with context:
Conversation History:
User: I need a good Samsung tablet for drawing
Assistant: Here are some great Samsung tablets...

Current Message: Show me accessories for that

Expected Response:
{{
  "intent": "FOLLOW_UP",
  "category": "electronics",
  "subcategory": "tablet_accessories",
  "budget": null,
  "occasion": null,
  "style": null,
  "brand_preference": ["Samsung"],
  "keywords": ["Samsung tablet accessories", "Samsung Tab S9 case", "Galaxy Tab pen", "Samsung tablet cover", "Samsung Tab screen protector", "Samsung tablet keyboard case", "Samsung Tab S9 FE accessories", "Samsung Tab drawing accessories", "Samsung tablet stand", "Samsung tablet charger"],
  "search_queries": ["Samsung tablet accessories", "Samsung Tab S9 case cover", "Galaxy Tab S9 FE accessories", "Samsung tablet pen stylus", "Samsung tablet keyboard case"]
}}
"""

_DETAILED_INTENT_PROMPT = """\
You are an advanced shopping intent parser for an e-commerce assistant.
Analyze the user's shopping query and return a valid JSON object with the following fields:
1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `category` — canonical category: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, or other
3. `subcategory` — specific product subcategory (e.g. mobile_phones, casual_tshirts, running_shoes, face_cream, etc.)
4. `budget` — maximum price limit if specified (integer in INR, or null if not specified)
5. `occasion` — usage occasion (e.g., Goa trip, gym, wedding, office, daily, or null)
6. `style` — style profile (e.g. oversized, casual, formal, traditional, sporty, or null)
7. `brand_preference` — list of preferred brands mentioned (e.g., ["Apple", "Samsung"] or empty list [])
8. `keywords` — list of approximately 10 optimized search keywords
9. `search_queries` — list of 5 to 10 optimized shopping search query phrases (e.g., "Best smartphone under ₹30000", "Camera phone under ₹30000", etc.)

Return ONLY a valid JSON object. Do not include markdown formatting or extra text.

Example query: "I want a phone under ₹30,000"
Example response:
{
  "category": "smartphones",
  "subcategory": "mobile_phones",
  "budget": 30000,
  "occasion": null,
  "style": null,
  "brand_preference": [],
  "keywords": ["smartphones under 30000", "best budget phone", "30k smartphone", "5G phone under 30k", "gaming phone under 30k", "camera phone under 30k"],
  "search_queries": [
    "Best smartphone under ₹30000",
    "Camera phone under ₹30000",
    "Gaming phone under ₹30000",
    "5G phone under ₹30000",
    "Smartphone under ₹30000 Amazon",
    "Smartphone under ₹30000 Flipkart",
    "Smartphone under ₹30000 Croma"
  ]
}
"""


class KeywordService:
    def __init__(self, gateway: Optional[LLMGateway] = None) -> None:
        self._gateway = gateway or LLMGateway()

    def analyze(self, user_message: str, conversation_context: str = "") -> Dict[str, Any]:
        plog.info("LLM INTENT + KEYWORDS -- query='%s'", user_message)

        if conversation_context:
            content = f"## Conversation History\n{conversation_context}\n\n## Current Message\n{user_message}"
            messages = [
                {"role": "system", "content": _INTENT_KEYWORD_PROMPT},
                {"role": "user", "content": content},
            ]
        else:
            messages = [
                {"role": "system", "content": _INTENT_KEYWORD_PROMPT},
                {"role": "user", "content": user_message},
            ]

        raw = self._gateway.call("intent_classification", messages)
        if raw:
            try:
                cleaned = self._strip_fences(raw)
                parsed = json.loads(cleaned)
                intent = parsed.get("intent", "RECOMMEND")
                keywords = parsed.get("keywords", [])
                category = parsed.get("category")
                if not category:
                    category = self._fallback_category(user_message)
                if not isinstance(keywords, list):
                    keywords = [str(keywords)]
                plog.info("  -> intent=%s | category=%s | keywords=%d", intent, category, len(keywords))
                for k in keywords[:10]:
                    plog.info("  -> keyword: %s", k)
                return {"intent": intent, "keywords": keywords[:12], "category": category}
            except (json.JSONDecodeError, KeyError) as exc:
                plog.warning("  -> LLM JSON parse failed: %s -- raw=%s", exc, raw[:200])

        fallback_intent = self._fallback_intent(user_message)
        fallback_keywords = self._fallback_keywords(user_message)
        fallback_cat = self._fallback_category(user_message)
        plog.info("  -> fallback: intent=%s | category=%s | keywords=%s", fallback_intent, fallback_cat, fallback_keywords[:3])
        return {"intent": fallback_intent, "keywords": fallback_keywords, "category": fallback_cat}

    def _fallback_intent(self, text: str) -> str:
        low = text.lower()
        if re.search(r'\b(compare|versus|vs|difference)\b', low):
            return "COMPARE"
        if any(k in low for k in [
            "show more", "more options", "more product", "tell me more", "any other",
            "accessor", "for this", "for that", "for it", "for them",
            "cheaper", "alternative", "another", "different", "more like",
            "any more", "other option", "similar",
        ]):
            return "FOLLOW_UP"
        if re.search(r'\b(kit|bundle|combo|set|gear|everything|full)\b', low):
            return "BUNDLE"
        if re.search(r'\b(hello|hi|hey|thanks|thank|bye|good)\b', low):
            return "GREETING"
        if any(k in low for k in ["explain", "what is", "how does", "difference", "meaning", "tell me about"]):
            return "EXPLAIN"
        
        # If fallback category is a known product class, treat as RECOMMEND
        if self._fallback_category(text) != "other":
            return "RECOMMEND"

        if re.search(r'\b(suggest|recommend|need|buy|want|looking|under|price)\b', low):
            return "RECOMMEND"
        return "GENERAL"



    def _fallback_category(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ["phone", "mobile", "smartphone", "iphone", "galaxy", "oneplus"]):
            return "smartphones"
        if any(k in low for k in ["laptop", "notebook", "macbook", "pc", "computer"]):
            return "laptops"
        if any(k in low for k in ["shirt", "tshirt", "t-shirt", "jeans", "pant", "trouser", "dress", "saree", "kurta", "jacket", "hoodie", "clothes", "clothing"]):
            return "fashion"
        if any(k in low for k in ["sunscreen", "moisturizer", "lipstick", "lip", "makeup", "foundation", "shampoo", "cream", "beauty", "perfume", "serum", "skin", "skincare", "skin care", "lotion", "soap"]):
            return "beauty"
        if any(k in low for k in ["shoes", "shooes", "shos", "sheos", "sneaker", "sneakers", "snakers", "footwear", "slipper", "sandal", "heel"]):
            return "footwear"
        if any(k in low for k in ["refrigerator", "fridge", "washing machine", "ac", "air conditioner", "tv", "television", "appliance", "appliances"]):
            return "home_appliances"
        if any(k in low for k in ["watch", "smartwatch", "headphone", "earphone", "earbuds", "camera", "tablet", "ipad", "gadget"]):
            return "electronics"
        return "other"

    def _fallback_keywords(self, text: str) -> List[str]:
        low = text.lower()
        # Remove punctuation except hyphens
        low = re.sub(r'[^\w\s-]', '', low)
        words = low.split()
        stop_words = {
            "i", "want", "need", "buy", "suggest", "recommend", "show", "me", "the", "a", "an",
            "under", "below", "above", "over", "budget", "price", "within", "around", "for", "with",
            "in", "of", "and", "or", "to", "from", "on", "at", "by", "only", "please"
        }
        keywords = []
        for w in words:
            if w not in stop_words and not w.isdigit():
                keywords.append(w)
        
        if keywords:
            unified = " ".join(keywords)
            res = [unified]
            for kw in keywords:
                if kw not in res and len(kw) > 1:
                    res.append(kw)
            return res
        return [text.strip()]

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

    def _escape_format(self, s: str) -> str:
        return s.replace("{", "{{").replace("}", "}}")

    def extract_detailed_intent(self, user_message: str, conversation_context: str = "") -> Dict[str, Any]:
        """Extract a structured representation of the user's shopping intent."""
        plog.info("LLM DETAILED INTENT EXTRACTION -- query='%s'", user_message)

        if conversation_context:
            prompt = _DETAILED_INTENT_PROMPT_WITH_CONTEXT.format(
                conversation_context=self._escape_format(conversation_context),
                user_message=self._escape_format(user_message),
            )
            messages = [
                {"role": "system", "content": "You are an advanced shopping intent parser for an e-commerce assistant."},
                {"role": "user", "content": prompt},
            ]
            plog.info("  -> using context-aware prompt with %d chars of conversation history", len(conversation_context))
        else:
            messages = [
                {"role": "system", "content": _DETAILED_INTENT_PROMPT},
                {"role": "user", "content": user_message},
            ]

        raw = self._gateway.call("intent_classification", messages)
        if raw:
            try:
                cleaned = self._strip_fences(raw)
                parsed = json.loads(cleaned)
                
                # Validation and formatting
                intent_val = parsed.get("intent")
                if not intent_val or intent_val not in ["RECOMMEND", "COMPARE", "FOLLOW_UP", "BUNDLE", "GENERAL", "EXPLAIN", "GREETING"]:
                    parsed["intent"] = self._fallback_intent(user_message)

                category = parsed.get("category")
                if not category or category not in ["smartphones", "laptops", "fashion", "beauty", "footwear", "home_appliances", "electronics", "other"]:
                    parsed["category"] = self._fallback_category(user_message)
                
                if "keywords" not in parsed or not isinstance(parsed["keywords"], list):
                    parsed["keywords"] = self._fallback_keywords(user_message)

                if "search_queries" not in parsed or not isinstance(parsed["search_queries"], list):
                    parsed["search_queries"] = [user_message]
                
                if "brand_preference" not in parsed or not isinstance(parsed["brand_preference"], list):
                    parsed["brand_preference"] = []

                # Ensure budget is integer or float
                budget = parsed.get("budget")
                if budget is not None:
                    try:
                        parsed["budget"] = float(budget)
                    except (ValueError, TypeError):
                        parsed["budget"] = None
                else:
                    parsed["budget"] = parse_budget(user_message)

                plog.info("  -> detailed intent category=%s | budget=%s | keywords=%d | queries=%d", 
                          parsed.get("category"), parsed.get("budget"), len(parsed.get("keywords", [])), len(parsed.get("search_queries", [])))
                return parsed
            except Exception as exc:
                plog.warning("  -> LLM detailed intent parse failed: %s -- raw=%s", exc, raw[:200])

        return self._fallback_detailed_intent(user_message)

    def _fallback_detailed_intent(self, user_message: str) -> Dict[str, Any]:
        category = self._fallback_category(user_message)
        budget = parse_budget(user_message)
        
        low = user_message.lower()
        occasion = None
        for occ in ["goa", "trip", "wedding", "office", "gym", "school", "sports", "travel", "summer"]:
            if occ in low:
                occasion = occ.capitalize()
                break
                
        style = None
        for st in ["oversized", "casual", "formal", "traditional", "sporty", "printed", "graphic"]:
            if st in low:
                style = st.capitalize()
                break

        brands = []
        # Check standard brands
        common_brands = [
            "samsung", "apple", "xiaomi", "redmi", "oneplus", "oppo", "vivo", "realme", "nothing",
            "motorola", "poco", "lenovo", "asus", "dell", "hp", "acer", "sony", "nike", "adidas",
            "puma", "reebok"
        ]
        for brand in common_brands:
            if re.search(rf"\b{brand}\b", low):
                brands.append(brand.capitalize())
        
        keywords = [user_message]
        words = user_message.split()
        if len(words) > 2:
            keywords.extend(words)
            
        search_queries = [
            f"Best {category} {user_message}",
            f"{user_message} online",
            f"{user_message} amazon",
            f"{user_message} flipkart",
        ]

        return {
            "intent": self._fallback_intent(user_message),
            "category": category,
            "subcategory": f"{category}_general",
            "budget": budget,
            "occasion": occasion,
            "style": style,
            "brand_preference": brands,
            "keywords": keywords[:10],
            "search_queries": search_queries[:6]
        }


def detect_gender(text: str) -> Optional[str]:
    low = text.lower()
    men_words = ["men", "men's", "mens", "male", "boy", "boys", "gents", "gentlemen", "his", "him", "man", "guy", "guys"]
    women_words = ["women", "women's", "womens", "female", "girl", "girls", "ladies", "lady", "her", "she", "woman", "gal"]

    men_score = sum(1 for w in men_words if re.search(rf'\b{w}\b', low))
    women_score = sum(1 for w in women_words if re.search(rf'\b{w}\b', low))

    if men_score > 0 and women_score == 0:
        return "men"
    if women_score > 0 and men_score == 0:
        return "women"
    if men_score > 0 and women_score > 0:
        return "unisex"
    return None


def parse_budget(query: str) -> Optional[float]:
    if not query:
        return None
    # Normalize commas, currency symbols, and spaces
    q_norm = query.lower().replace(",", "").replace("rs.", "").replace("rs", "").replace("inr", "").replace("₹", "").replace("$", "")

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
        return val
    return None


