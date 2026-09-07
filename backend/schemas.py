from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

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


_ALLOWED_ROLES = {"user", "assistant", "system"}


class SearchContext(BaseModel):
    keywords_used: str = ""
    semantic_description: str = ""
    inferred_context: str = ""
    target_sites: List[str] = []
    data_source: str = "live"
    query_hash: str = ""


class Message(BaseModel):
    role: str
    content: str = Field(..., min_length=0, max_length=10000)
    timestamp: str
    products: Optional[List[Any]] = None
    comparison: Optional[Dict[str, Any]] = None
    response_type: Optional[str] = Field(default=None, alias="responseType")
    search_context: Optional[Any] = Field(default=None, alias="searchContext")
    bundle: Optional[Dict[str, Any]] = None

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v.lower() not in _ALLOWED_ROLES:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {_ALLOWED_ROLES}")
        return v.lower()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    history: List[Message] = []
    activeChatId: str = Field(default="default", min_length=1, max_length=64)

    @field_validator("activeChatId")
    @classmethod
    def _validate_session_id(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("activeChatId must contain only letters, digits, hyphens, and underscores")
        return v


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
