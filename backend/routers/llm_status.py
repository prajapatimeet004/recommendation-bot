from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from backend.services.llm_gateway import gateway

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/llm-status")
def llm_status() -> Dict[str, Any]:
    return gateway.get_status()
