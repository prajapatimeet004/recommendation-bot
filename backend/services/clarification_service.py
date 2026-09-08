from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.services.keyword_service import detect_gender, parse_budget

logger = logging.getLogger(__name__)

# Product keywords that strongly imply a gender
_IMPLICIT_GENDER_MAP: Dict[str, Optional[str]] = {
    "saree": "women", "saris": "women", "salwar": "women", "lehenga": "women",
    "choli": "women", "bra": "women", "bikini": "women", "nightie": "women",
    "kurti": "women", "dupatta": "women", "hijab": "women", "burqa": "women",
    "niqab": "women", "maxi": "women", "skirt": "women", "camisole": "women",
    "crop top": "women", "leggings": "women", "palazzo": "women",
    "boxers": "men", "briefs": "men", "trunks": "men", "necktie": "men",
    "bow tie": "men", "cufflinks": "men", "tie": "men",
}

_BROAD_PRODUCT_TYPES: Dict[str, str] = {
    "shoes": "What type of shoes? (e.g., running, casual, formal, sports)",
    "sneakers": "What type of sneakers? (e.g., casual, sports, running)",
    "bag": "What will you use the bag for? (e.g., school, travel, gym, everyday)",
    "dress": "What type of dress? (e.g., casual, party, formal, traditional)",
    "shirt": "What type of shirt? (e.g., casual, formal, party wear)",
    "t-shirt": "What style of t-shirt? (e.g., plain, printed, polo)",
    "tshirt": "What style of t-shirt? (e.g., plain, printed, polo)",
    "jeans": "What type of jeans? (e.g., skinny, straight, bootcut, ripped)",
    "pants": "What type of pants? (e.g., formal, casual, chinos)",
    "trousers": "What type of trousers? (e.g., formal, casual)",
    "shorts": "What type of shorts? (e.g., sports, casual, denim)",
    "jacket": "What type of jacket? (e.g., casual, formal, sports, winter)",
    "hoodie": "What style of hoodie? (e.g., plain, printed, zip-up)",
    "sweater": "What type of sweater? (e.g., casual, winter wear)",
    "watch": "What type of watch? (e.g., casual, sports, smartwatch, formal)",
    "headphones": "What type of headphones? (e.g., wireless, wired, noise-cancelling)",
    "earphones": "What type of earphones? (e.g., wireless, wired, in-ear)",
    "earbuds": "What type of earbuds? (e.g., wireless, noise-cancelling, sports)",
    "perfume": "What type of fragrance? (e.g., men's, women's, deodorant, body spray)",
    "sunscreen": "What SPF level? (e.g., SPF 30, SPF 50, for face, for body)",
    "moisturizer": "What type? (e.g., for face, for body, with SPF)",
    "lipstick": "What finish? (e.g., matte, gloss, liquid, cream)",
    "foundation": "What coverage? (e.g., light, medium, full, compact)",
}

_EXPENSIVE_CATEGORIES = {"smartphones", "laptops", "electronics", "home_appliances"}

_GENDERED_CATEGORIES = {"fashion", "footwear", "beauty"}

# Generic stop-words that don't count as specific modifiers
_GENERIC_MODIFIERS = {
    "a", "an", "the", "some", "any", "for", "i", "my", "your", "his", "her",
    "want", "need", "buy", "get", "have", "looking", "find", "show", "me",
    "this", "that", "these", "those", "nice", "good", "great", "best", "new",
    "cheap", "expensive", "colorful", "please", "just", "like", "would",
    "could", "can", "recommend", "suggest", "tell", "give", "need",
}


@dataclass
class ClarificationNeed:
    question: str
    options: Optional[List[str]] = None


def determine_clarification(
    detailed_intent: Dict[str, Any],
    user_message: str,
    is_llm_fallback: bool = False,
) -> Optional[ClarificationNeed]:
    intent = detailed_intent.get("intent", "RECOMMEND")
    if intent != "RECOMMEND":
        return None

    category = detailed_intent.get("category", "other")

    # In LLM fallback mode, only check things detectable via regex
    if is_llm_fallback:
        return _fallback_clarification(detailed_intent, user_message, category)

    # 2. Gender-needed categories (fashion, beauty)
    if category in ("fashion", "beauty"):
        return _check_gender(detailed_intent, user_message)

    # 3. Footwear → purpose first
    if category == "footwear":
        return _check_footwear_purpose(detailed_intent, user_message)

    # 4. Expensive categories → budget
    if category in _EXPENSIVE_CATEGORIES:
        return _check_budget(detailed_intent, user_message, category)

    # 5. Other category or "other" — check for broad product type
    return _check_broad_product_type(detailed_intent, user_message)


def _fallback_clarification(
    detailed_intent: Dict[str, Any],
    user_message: str,
    category: str,
) -> Optional[ClarificationNeed]:
    if category in _GENDERED_CATEGORIES:
        gender = detect_gender(user_message)
        if gender is None:
            if _has_implicit_gender(user_message.lower()):
                return None
            return ClarificationNeed(
                "Are you looking for Men's or Women's products?",
                ["Men", "Women", "Both"],
            )
    if category in _EXPENSIVE_CATEGORIES:
        budget = _extract_budget(detailed_intent, user_message)
        if budget is None:
            q, opts = _budget_question(category)
            return ClarificationNeed(q, opts)
    return None


def _check_gender(
    detailed_intent: Dict[str, Any],
    user_message: str,
) -> Optional[ClarificationNeed]:
    gender = detect_gender(user_message)
    if gender is not None:
        detailed_intent["gender"] = gender
        return None
    if _has_implicit_gender(user_message.lower()):
        return None
    return ClarificationNeed(
        "Are you looking for Men's or Women's products?",
        ["Men", "Women", "Both"],
    )


def _check_footwear_purpose(
    detailed_intent: Dict[str, Any],
    user_message: str,
) -> Optional[ClarificationNeed]:
    gender = detect_gender(user_message)
    if gender is not None:
        detailed_intent["gender"] = gender

    if _query_is_specific_enough(user_message, detailed_intent, "shoe"):
        return None

    return ClarificationNeed(
        "What type of shoes are you looking for? (e.g., running, casual, formal, sports)",
        ["Running", "Casual", "Formal", "Sports"],
    )


def _check_budget(
    detailed_intent: Dict[str, Any],
    user_message: str,
    category: str,
) -> Optional[ClarificationNeed]:
    budget = _extract_budget(detailed_intent, user_message)
    if budget is not None:
        return None
    question, options = _budget_question(category)
    return ClarificationNeed(question, options)


def _check_broad_product_type(
    detailed_intent: Dict[str, Any],
    user_message: str,
) -> Optional[ClarificationNeed]:
    product_type = _find_broad_product_type(user_message)
    if product_type and not _query_is_specific_enough(
        user_message, detailed_intent, product_type
    ):
        question = _BROAD_PRODUCT_TYPES.get(
            product_type,
            f"What type of {product_type} are you looking for?",
        )
        return ClarificationNeed(question)
    return None


def _has_implicit_gender(text: str) -> bool:
    for keyword, gender in _IMPLICIT_GENDER_MAP.items():
        if gender is not None and keyword in text:
            return True
    return False


def _extract_budget(
    detailed_intent: Dict[str, Any],
    user_message: str,
) -> Optional[float]:
    budget = detailed_intent.get("budget")
    if budget is not None:
        return budget
    return parse_budget(user_message)


def _budget_question(category: str):
    questions = {
        "smartphones": ("What's your budget for the smartphone?", ["Under ₹15k", "₹15k-₹30k", "₹30k-₹60k", "Above ₹60k"]),
        "laptops": ("What's your budget for the laptop?", ["Under ₹40k", "₹40k-₹70k", "₹70k-₹1L", "Above ₹1L"]),
        "electronics": ("What's your budget?", ["Under ₹5k", "₹5k-₹15k", "₹15k-₹30k", "Above ₹30k"]),
        "home_appliances": ("What's your budget?", ["Under ₹10k", "₹10k-₹30k", "₹30k-₹50k", "Above ₹50k"]),
    }
    return questions.get(category, ("What's your budget?", ["Under ₹10k", "₹10k-₹30k", "₹30k-₹50k", "Above ₹50k"]))


def _find_broad_product_type(user_message: str) -> Optional[str]:
    low = user_message.lower()
    for product_type in _BROAD_PRODUCT_TYPES:
        if product_type in low:
            return product_type
    return None


def _query_is_specific_enough(
    user_message: str,
    detailed_intent: Dict[str, Any],
    product_type: str,
) -> bool:
    if detailed_intent.get("brand_preference"):
        return True
    if detailed_intent.get("occasion") is not None:
        return True
    if detailed_intent.get("style") is not None:
        return True

    subcategory = detailed_intent.get("subcategory")
    if subcategory and not subcategory.endswith("_general"):
        return True

    size_present = bool(
        re.search(
            r'\b(size|uk|us|eu)\s*[:\s]*(\d+\.?\d*)',
            user_message,
            re.IGNORECASE,
        )
    )
    if size_present:
        return True

    low = user_message.lower()
    pattern = rf'(\w+)\s+{re.escape(product_type)}'
    match = re.search(pattern, low)
    if match:
        modifier = match.group(1).lower()
        if modifier not in _GENERIC_MODIFIERS:
            return True

    return False
