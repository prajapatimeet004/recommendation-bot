from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional


from backend.services.llm_gateway import LLMGateway
from backend.services.pipeline_logger import get_pipeline_logger
from backend.services.local_intent_classifier import LocalIntentClassifier

logger = logging.getLogger(__name__)
plog = get_pipeline_logger()

_INTENT_KEYWORD_PROMPT = """\
You are a shopping intent classifier, keyword generation engine, and category classifier for an Indian e-commerce assistant.

## Task
Analyze the user's message and return a valid JSON object with exactly three fields:
1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `keywords` — exactly 10 generic shopping search keywords derived ONLY from the user's message
3. `category` — one of: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, other

## CRITICAL RULES — YOU MUST FOLLOW THESE:
- NEVER invent specific products, model names, brand names, prices, or specifications.
- NEVER include a brand name unless the user explicitly mentions it in their message.
- NEVER include a price or budget figure unless the user explicitly states one.
- Keywords must be GENERIC category-level shopping terms (e.g., "running shoes" not "Nike Air Zoom Pegasus 40").
- Do NOT rewrite or rephrase proper nouns from the user query — use them verbatim.
- If the query spans multiple categories (e.g., "shoes and clothes"), pick the more specific one mentioned, or "other" if equally broad.
- Generate exactly 10 keywords. Do not generate fewer or more.

## Intent Definitions
- RECOMMEND: user wants product suggestions (keywords: suggest, recommend, best, find, buy, need, looking for, help me choose)
- COMPARE: user wants to compare products (keywords: compare, versus, vs, difference between)
- FOLLOW_UP: user is asking follow-up on previously shown products
- BUNDLE: user wants a lifestyle bundle or kit (keywords: kit, bundle, setup, combo, everything for, full gear)
- GENERAL: off-topic or non-shopping message
- EXPLAIN: user wants explanation of product features, specs, or technology
- GREETING: greeting, thank you, hello, hi, bye

## Category Definitions
- smartphones: mobile phones only. NOT phone cases, chargers, or accessories.
- laptops: notebooks, MacBooks, gaming laptops only.
- fashion: clothing, shirts, t-shirts, jeans, dresses, sarees, jackets, hoodies.
- beauty: cosmetics, skincare, lipstick, foundation, sunscreen, shampoo, moisturizer.
- footwear: shoes, sneakers, sandals, boots, heels.
- home_appliances: refrigerators, washing machines, air conditioners, TVs, microwave ovens only.
- electronics: headphones, smartwatches, cameras, tablets, speaker systems, general tech accessories.
- other: anything that does not fit the above categories, or spans multiple categories.

## Examples

User: "I need clothes for Navratri"
Response: {"intent": "RECOMMEND", "keywords": ["traditional kurta", "ethnic wear", "festival wear", "kurta pajama", "navratri outfit", "festive clothing", "ethnic men wear", "ethnic women wear", "garba attire", "traditional clothing"], "category": "fashion"}

User: "Phone for photography"
Response: {"intent": "RECOMMEND", "keywords": ["camera phone", "photography smartphone", "high megapixel phone", "portrait camera phone", "night photography phone", "optical zoom phone", "4k video phone", "smartphone camera", "best camera phone", "mobile photography"], "category": "smartphones"}

User: "Compare iPhone and Samsung"
Response: {"intent": "COMPARE", "keywords": ["iphone samsung comparison", "flagship smartphone", "premium phone", "ios android compare", "smartphone compare", "apple samsung", "high end phone", "smartphone features", "mobile phone comparison", "best smartphone"], "category": "smartphones"}

User: "I'm joining a gym"
Response: {"intent": "BUNDLE", "keywords": ["gym shoes", "workout clothes", "activewear", "gym bag", "fitness accessories", "gym equipment", "workout gear", "sportswear", "training shoes", "gym t-shirt"], "category": "other"}

Return ONLY valid JSON. No markdown, no explanation, no conversational text."""


_DETAILED_INTENT_PROMPT_WITH_CONTEXT = """\
You are a precise shopping intent parser for an e-commerce assistant.
You MUST return ONLY a valid JSON object. No conversational text, no explanations, no markdown fences.

## CRITICAL RULES — YOU MUST FOLLOW THESE:
- NEVER invent product names, model numbers, brand names, prices, or specifications.
- Include a brand in `brand_preference` ONLY if the user explicitly mentions it in the conversation.
- Include a `budget` value ONLY if the user explicitly states a price limit.
- Set `occasion` to null unless the user explicitly mentions an occasion.
- Set `style` to null unless the user explicitly mentions a style.
- Keywords and search_queries must be GENERIC (e.g., "tablet accessories" not "Samsung Tab S9 case cover").
- If the conversation history suggests the user is referring to a previously shown product, use FOLLOW_UP intent.
- If the user's current message is a standalone new request, use RECOMMEND intent.
- Do NOT carry over brand_preference, budget, occasion, or style from history unless the current message references them.

## Conversation History
Use this history ONLY to resolve pronouns and references (e.g., "that product", "accessories for it", "this brand").
<history>
{conversation_context}
</history>

## Current Message
<message>
{user_message}
</message>

## Task
Analyze the user's CURRENT MESSAGE in the context of the conversation history above.
Return a valid JSON object with ALL of the following fields:

1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `category` — one of: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, other
3. `subcategory` — generic subcategory (e.g., mobile_phones, casual_tshirts, running_shoes, face_cream, general). Set to "{{category}}_general" if unsure.
4. `budget` — integer in INR, or null. Set ONLY if user explicitly states a price.
5. `occasion` — string or null. Set ONLY if user explicitly mentions one (e.g., "gym", "wedding", "office", "goa trip").
6. `style` — string or null. Set ONLY if user explicitly mentions one (e.g., "casual", "formal", "sporty", "traditional").
7. `brand_preference` — list of strings, or empty list. Include ONLY brands the user explicitly named.
8. `keywords` — list of exactly 10 generic search keywords.
9. `search_queries` — list of exactly 5 generic search query phrases.

## Intent Selection Rules
- RECOMMEND: user asks for product suggestions. Default for shopping queries.
- COMPARE: user explicitly asks to compare two or more items.
- FOLLOW_UP: user refers to a previously shown product ("this", "that", "it", "show more", "accessories for it").
- BUNDLE: user asks for a kit, bundle, combo, or everything for an activity.
- GENERAL: non-shopping question.
- EXPLAIN: user asks for explanation of a feature or technology.
- GREETING: hello, hi, thanks, bye.

Example with context:
<history>
User: I need a good Samsung tablet for drawing
Assistant: Here are some great Samsung tablets...
</history>
<message>Show me accessories for that</message>

Expected Response:
{{
  "intent": "FOLLOW_UP",
  "category": "electronics",
  "subcategory": "tablet_accessories",
  "budget": null,
  "occasion": null,
  "style": null,
  "brand_preference": ["Samsung"],
  "keywords": ["tablet accessories", "tablet case", "tablet cover", "tablet stand", "tablet keyboard", "tablet screen protector", "stylus pen", "tablet bag", "tablet charger", "tablet dock"],
  "search_queries": ["tablet accessories online", "buy tablet accessories india", "tablet case and cover", "tablet keyboard and stylus", "tablet stand and mount"]
}}
"""

_DETAILED_INTENT_PROMPT = """\
You are a precise shopping intent parser for an e-commerce assistant.
You MUST return ONLY a valid JSON object. No conversational text, no explanations, no markdown fences.

## CRITICAL RULES — YOU MUST FOLLOW THESE:
- NEVER invent product names, model numbers, brand names, prices, or specifications.
- Include a brand in `brand_preference` ONLY if the user explicitly mentions it.
- Include a `budget` value ONLY if the user explicitly states a price limit. Otherwise null.
- Set `occasion` to null unless the user explicitly mentions an occasion.
- Set `style` to null unless the user explicitly mentions a style.
- Keywords and search_queries must be GENERIC (e.g., "budget smartphone" not "Xiaomi Redmi Note 13").
- Do NOT add model numbers or specific product identifiers to keywords.
- Generate exactly 10 keywords and exactly 5 search queries.

Analyze the user's shopping query and return a valid JSON object with ALL of the following fields:

1. `intent` — one of: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, GENERAL, EXPLAIN, GREETING
2. `category` — one of: smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, other
3. `subcategory` — generic subcategory (e.g., mobile_phones, casual_tshirts, running_shoes, face_cream, general). Set to "{{category}}_general" if unsure.
4. `budget` — integer in INR, or null. Set ONLY if user explicitly states a price.
5. `occasion` — string or null. Set ONLY if user explicitly mentions one.
6. `style` — string or null. Set ONLY if user explicitly mentions one.
7. `brand_preference` — list of strings, or empty list. Include ONLY brands the user explicitly named.
8. `keywords` — list of exactly 10 generic search keywords. Never include specific model names.
9. `search_queries` — list of exactly 5 generic search query phrases.

Example query: "I want a phone under ₹30,000"
Expected response:
{
  "intent": "RECOMMEND",
  "category": "smartphones",
  "subcategory": "mobile_phones",
  "budget": 30000,
  "occasion": null,
  "style": null,
  "brand_preference": [],
  "keywords": ["budget smartphone", "phone under 30000", "affordable 5g phone", "best value phone", "camera phone 30000", "battery phone 30000", "smartphone deals", "mid range phone", "android phone 30000", "display phone 30000"],
  "search_queries": ["best smartphone under 30000", "phone under 30000 india", "5g phone budget price", "camera phone under 30000", "buy smartphone online india"]
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

        # Local semantic intent classifier fallback
        try:
            pred = LocalIntentClassifier.instance().classify(user_message)
            if pred:
                fallback_intent = self._fallback_intent(user_message)
                if fallback_intent in ("COMPARE", "GREETING", "BUNDLE", "FOLLOW_UP"):
                    intent = fallback_intent
                else:
                    intent = pred.get("intent", "RECOMMEND")
                category = pred.get("category", "other")
                keywords = self._fallback_keywords(user_message)
                plog.info("  -> Local semantic intent classification fallback (analyze): intent=%s | category=%s", intent, category)
                return {"intent": intent, "keywords": keywords[:12], "category": category}
        except Exception as exc:
            plog.warning("  -> Local semantic fallback failed in analyze: %s", exc)

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
                {"role": "system", "content": "You are a precise shopping intent parser. You extract ONLY what the user explicitly states. NEVER invent brands, budgets, occasions, or styles. Set null for unspecified fields. Return valid JSON only."},
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
                parsed["llm_success"] = True
                return parsed
            except Exception as exc:
                plog.warning("  -> LLM detailed intent parse failed: %s -- raw=%s", exc, raw[:200])

        # Local semantic intent classifier fallback
        try:
            pred = LocalIntentClassifier.instance().classify(user_message)
            if pred:
                fallback_intent = self._fallback_intent(user_message)
                if fallback_intent in ("COMPARE", "GREETING", "BUNDLE", "FOLLOW_UP"):
                    intent = fallback_intent
                else:
                    intent = pred.get("intent", "RECOMMEND")
                category = pred.get("category", "other")
                
                budget = parse_budget(user_message)
                low = user_message.lower()
                occasion = None
                for occ in ["goa", "trip", "wedding", "office", "gym", "school", "sports", "travel", "summer", "navratri", "navaratri", "diwali", "festive", "ethnic", "party"]:
                    if occ in low:
                        occasion = occ.capitalize()
                        break
                        
                style = None
                for st in ["oversized", "casual", "formal", "traditional", "sporty", "printed", "graphic"]:
                    if st in low:
                        style = st.capitalize()
                        break

                brands = []
                common_brands = [
                    "samsung", "apple", "xiaomi", "redmi", "oneplus", "oppo", "vivo", "realme", "nothing",
                    "motorola", "poco", "lenovo", "asus", "dell", "hp", "acer", "sony", "nike", "adidas",
                    "puma", "reebok"
                ]
                for brand in common_brands:
                    if re.search(rf"\b{brand}\b", low):
                        brands.append(brand.capitalize())
                
                keywords = self._fallback_keywords(user_message)
                search_queries = [
                    f"Best {category} {user_message}",
                    f"{user_message} online",
                    f"{user_message} amazon",
                    f"{user_message} flipkart",
                ]
                
                plog.info("  -> Local semantic intent classification fallback (detailed): intent=%s | category=%s", intent, category)
                return {
                    "intent": intent,
                    "category": category,
                    "subcategory": f"{category}_general",
                    "budget": budget,
                    "occasion": occasion,
                    "style": style,
                    "brand_preference": brands,
                    "keywords": keywords[:10],
                    "search_queries": search_queries[:6],
                    "llm_success": False
                }
        except Exception as exc:
            plog.warning("  -> Local semantic fallback failed in detailed intent: %s", exc)

        res = self._fallback_detailed_intent(user_message)
        res["llm_success"] = False
        return res

    def _fallback_detailed_intent(self, user_message: str) -> Dict[str, Any]:
        category = self._fallback_category(user_message)
        budget = parse_budget(user_message)
        
        low = user_message.lower()
        occasion = None
        for occ in ["goa", "trip", "wedding", "office", "gym", "school", "sports", "travel", "summer", "navratri", "navaratri", "diwali", "festive", "ethnic", "party"]:
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


