from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from backend.models.product import ProductOutput, ExtractedProduct


class ResponseType(str, Enum):
    RECOMMEND = "RECOMMEND"
    COMPARE = "COMPARE"
    FOLLOW_UP = "FOLLOW_UP"
    BUNDLE = "BUNDLE"
    GENERAL = "GENERAL"
    EXPLAIN = "EXPLAIN"
    GREETING = "GREETING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class SearchContext(BaseModel):
    keywords_used: str = ""
    semantic_description: str = ""
    inferred_context: str = ""
    target_sites: List[str] = []
    data_source: str = "live"
    query_hash: str = ""


class Message(BaseModel):
    role: str
    content: str
    timestamp: str
    products: Optional[List[Any]] = None
    comparison: Optional[Dict[str, Any]] = None
    response_type: Optional[str] = None
    search_context: Optional[Any] = None
    bundle: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = []
    activeChatId: str = "default"


class ChatResponse(BaseModel):
    message: str
    response_type: ResponseType = ResponseType.RECOMMEND
    search_context: Optional[SearchContext] = None
    products: Optional[List[ProductOutput]] = None
    comparison: Optional[Dict[str, Any]] = None
    comparison_table: Optional[Dict[str, Any]] = None
    bundle: Optional[Dict[str, Any]] = None
    follow_up_questions: List[str] = []
    followUps: List[str] = []
    data_freshness: str = "live"
    pagination_token: Optional[str] = None
    total_products: int = 0

    class Config:
        use_enum_values = True
