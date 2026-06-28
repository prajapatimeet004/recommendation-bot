import logging
import os
from typing import Any, Dict, List, Optional

from backend.pipeline.shopping_pipeline import run_pipeline
from backend.services.product_service import enrich_product
from backend.schemas import ChatResponse, Message

logger = logging.getLogger(__name__)


async def process_query(
    user_message: str,
    tavily_api_key: str = "",
    history: Optional[List[Message]] = None,
    session_id: str = "default",
) -> Dict[str, Any]:
    """
    Thin compatibility wrapper around the shopping pipeline.
    """
    if not tavily_api_key:
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "")

    # Combine history context + follow-up answer (Bug 3)
    original_query = user_message
    is_follow_up = False
    if history and len(history) > 0:
        # Find the last user message from history (original query)
        for msg in reversed(history):
            role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
            if role == "user":
                val = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
                if val:
                    original_query = val
                    is_follow_up = True
                    break
        user_message = f"{original_query} {user_message}"

    result = await run_pipeline(
        user_message=user_message,
        session_id=session_id or "default",
        tavily_api_key=tavily_api_key,
        history=history,
    )

    products = result.get("products", [])
    intent = result.get("intent", "RECOMMEND")
    data_source = result.get("data_source", "live")
    keywords = result.get("keywords", [])

    enriched = [enrich_product(p) for p in products]
    keyword_str = ", ".join(keywords[:5]) if keywords else user_message

    follow_ups = _generate_follow_ups(intent, enriched)

    return {
        "message": _generate_message(intent, enriched, user_message, is_follow_up=is_follow_up),
        "reply": _generate_message(intent, enriched, user_message, is_follow_up=is_follow_up),
        "response_type": intent,
        "search_context": {
            "keywords_used": keyword_str,
            "data_source": data_source,
        },
        "products": [p.model_dump() for p in enriched] if enriched else None,
        "comparison": None,
        "comparison_table": None,
        "bundle": None,
        "follow_up_questions": follow_ups,
        "followUps": follow_ups,
        "data_freshness": data_source,
    }


def _generate_message(intent: str, products: list, query: str, is_follow_up: bool = False) -> str:
    # Bypass hardcoded greeting response if it is a follow-up answer (Bug 4)
    if intent in ("GREETING", "GENERAL") and not is_follow_up:
        return "Hello! I'm your AI Shopping Assistant. Tell me what you're looking for — clothes, electronics, fitness gear, or anything else — and I'll find the best products for you!"
    if not products:
        return f"I couldn't find specific products for '{query}'. Try different keywords or be more specific about your needs."
    return f"Here are the top matching products for '{query}'. I've ranked them by relevance, price fit, rating, and completeness."


def _generate_follow_ups(intent: str, products: list) -> List[str]:
    follow_ups = []
    if intent in ("GREETING", "GENERAL"):
        return ["Best laptop under ₹80,000", "Gym shoes and clothes", "Smartphones under ₹40,000"]
    if products:
        if len(products) >= 2:
            follow_ups.append(f"Compare {products[0].name} and {products[1].name}")
        follow_ups.append("Show more")
        follow_ups.append("What are the cheaper options?")
    follow_ups.extend(["Search again", "Find accessories"])
    return follow_ups
