from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ExtractedProduct(BaseModel):
    name: str = Field(..., min_length=1)
    brand: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    currency: str = "INR"
    image_url: Optional[str] = None
    product_url: str = Field(..., min_length=1)
    rating: Optional[float] = None
    specifications: Dict[str, str] = Field(default_factory=dict)
    description: str = ""
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: str = ""
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("price", "mrp", mode="before")
    @classmethod
    def coerce_number(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            import re
            cleaned = re.sub(r"[^\d.]", "", v)
            return float(cleaned) if cleaned else None
        return None

    @field_validator("discount", mode="before")
    @classmethod
    def coerce_discount(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            import re
            cleaned = re.sub(r"[^\d.]", "", v)
            return float(cleaned) if cleaned else None
        return None

    @field_validator("rating", mode="before")
    @classmethod
    def coerce_rating(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return min(float(v), 5.0)
        if isinstance(v, str):
            import re
            match = re.search(r"[\d.]+", v)
            return min(float(match.group()), 5.0) if match else None
        return None


class ProductSchema(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    rating: Optional[float] = None
    specifications: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    image: Optional[str] = None
    url: str
    source: Optional[str] = None
    availability: Optional[str] = None
    scraped_at: Optional[str] = None


class ProductInput(BaseModel):
    name: str
    brand: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    currency: str = "INR"
    image_url: Optional[str] = None
    product_url: str
    rating: Optional[float] = None
    specifications: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: str = ""
    similarity_score: Optional[float] = None


class ProductOutput(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    currency: str = "INR"
    image_url: Optional[str] = None
    product_url: str
    rating: Optional[float] = None
    specifications: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: str = ""
    similarity_score: Optional[float] = None
    score_label: Optional[str] = None
    # redone fields
    image: Optional[str] = None
    url: Optional[str] = None
    availability: Optional[str] = None
    scraped_at: Optional[str] = None

    class Config:
        from_attributes = True

    def compute_label(self) -> str | None:
        if self.similarity_score is None:
            return None
        if self.similarity_score >= 90:
            return "Excellent Match"
        if self.similarity_score >= 80:
            return "Great Match"
        return "Good Match"

