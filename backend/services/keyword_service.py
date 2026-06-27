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


class KeywordService:
    def __init__(self, gateway: Optional[LLMGateway] = None) -> None:
        self._gateway = gateway or LLMGateway()

    def analyze(self, user_message: str) -> Dict[str, Any]:
        plog.info("LLM INTENT + KEYWORDS -- query='%s'", user_message)

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
        if any(k in low for k in ["show more", "more options", "more product", "tell me more", "any other"]):
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
        if any(k in low for k in ["sunscreen", "moisturizer", "lipstick", "lip", "makeup", "foundation", "shampoo", "cream", "beauty", "perfume", "serum"]):
            return "beauty"
        if any(k in low for k in ["shoes", "sneakers", "footwear", "slipper", "sandal", "heel"]):
            return "footwear"
        if any(k in low for k in ["refrigerator", "fridge", "washing machine", "ac", "air conditioner", "tv", "television", "appliance", "appliances"]):
            return "home_appliances"
        if any(k in low for k in ["watch", "smartwatch", "headphone", "earphone", "earbuds", "camera", "tablet", "ipad", "gadget"]):
            return "electronics"
        return "other"

    def _fallback_keywords(self, text: str) -> List[str]:
        words = text.strip().split()
        if len(words) <= 5:
            return [text.strip()]
        return [text.strip(), " ".join(words[:5]), " ".join(words[-3:])]

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


