from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.pipeline.shopping_pipeline import run_pipeline
from backend.services.product_service import enrich_product

logger = logging.getLogger(__name__)

router = APIRouter()


class SearchRequest(BaseModel):
    query: str


class SearchItem(BaseModel):
    name: str
    brand: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    currency: str = "INR"
    image_url: Optional[str] = None
    product_url: str
    rating: Optional[float] = None
    specifications: Dict[str, str] = {}
    description: str = ""
    category: Optional[str] = None
    tags: List[str] = []
    source: str = ""
    similarity_score: Optional[float] = None


class SearchResponse(BaseModel):
    query: str
    intent: str
    products: List[SearchItem]
    total_found: int
    data_source: str


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    try:
        result = await run_pipeline(
            user_message=request.query,
            session_id="search-direct",
        )


        products = result.get("products", [])
        enriched = [enrich_product(p) for p in products]

        return SearchResponse(
            query=request.query,
            intent=result.get("intent", "RECOMMEND"),
            products=[
                SearchItem(
                    name=p.name,
                    brand=p.brand,
                    price=p.price,
                    mrp=p.mrp,
                    discount=p.discount,
                    currency=p.currency,
                    image_url=p.image_url,
                    product_url=p.product_url,
                    rating=p.rating,
                    specifications=p.specifications,
                    description=p.description,
                    category=p.category,
                    tags=p.tags,
                    source=p.source,
                    similarity_score=p.similarity_score,
                )
                for p in enriched
            ],
            total_found=len(enriched),
            data_source=result.get("data_source", "live"),
        )

    except Exception as exc:
        logger.exception("Search endpoint error")
        raise HTTPException(status_code=500, detail=str(exc))
