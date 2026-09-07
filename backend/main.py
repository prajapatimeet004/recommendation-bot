import logging
import os
from pathlib import Path
import secrets
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

from backend.schemas import ChatRequest, ChatResponse, SearchContext
from backend.settings import settings
from backend.recommender import process_query
from backend.routers.chat import router as chat_router
from backend.routers.search import router as search_router
from backend.routers.llm_status import router as llm_status_router

# Load from backend/.env regardless of CWD
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)

# Request ID logging filter
class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", "-")
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(request_id)s] %(levelname)-8s %(name)s: %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIDFilter())

logger = logging.getLogger(__name__)

_API_AUTH_TOKEN = settings.API_AUTH_TOKEN
_security = HTTPBearer(auto_error=False)

async def verify_token(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security)):
    if request.url.path == "/health":
        return True
    if not _API_AUTH_TOKEN:
        return True
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not secrets.compare_digest(credentials.credentials, _API_AUTH_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid API token")
    return True

app = FastAPI(
    title="AI Shopping Assistant API",
    description="Backend API for the Intelligent Product Recommendation Chatbot",
    version="2.0.0",
    dependencies=[Depends(verify_token)],
)

_cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = req_id
    import logging
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.request_id = req_id
        return record
    logging.setLogRecordFactory(record_factory)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


app.include_router(chat_router)
app.include_router(search_router)
app.include_router(llm_status_router)


@app.get("/")
def root():
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    return {
        "message": "AI Shopping Assistant API is running!",
        "docs": f"http://localhost:{port}/docs",
        "health": f"http://localhost:{port}/health",
        "chat": f"POST http://localhost:{port}/chat",
    }


@app.get("/health")
async def health_check():
    from backend.pipeline.shopping_pipeline import _vector_service, _embedding_service
    from backend.services.llm_gateway import _MODELS_REGISTRY

    checks = {
        "api": True,
        "chromadb": False,
        "embedding_model": False,
        "llm_api_keys": False,
    }

    # Check ChromaDB
    try:
        col = _vector_service.get_collection("other")
        col.count()
        checks["chromadb"] = True
    except Exception as e:
        logger.warning("ChromaDB health check failed: %s", e)

    # Check embedding model
    try:
        result = _embedding_service.generate("health check query")
        checks["embedding_model"] = isinstance(result, list) and len(result) > 0
    except Exception as e:
        logger.warning("Embedding model health check failed: %s", e)

    # Check LLM API keys
    try:
        configured_keys = any(os.environ.get(cfg["env_key"]) for cfg in _MODELS_REGISTRY.values())
        checks["llm_api_keys"] = configured_keys
    except Exception as e:
        logger.warning("LLM API key check failed: %s", e)

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "service": "AI Shopping Assistant API",
            "checks": checks,
        }
    )


@app.post("/chat-legacy", response_model=ChatResponse)
async def chat_endpoint_legacy(request: ChatRequest):
    try:
        tavily_key = os.environ.get("TAVILY_API_KEY", "")
        result = await process_query(
            request.message,
            tavily_api_key=tavily_key,
            history=request.history,
            session_id=request.activeChatId or "default"
        )
        return ChatResponse(
            message=result.get("message", result.get("reply", "")),
            response_type=result.get("response_type", "RECOMMEND"),
            search_context=SearchContext(**result["search_context"]) if result.get("search_context") else None,
            products=result.get("products"),
            comparison=result.get("comparison"),
            comparison_table=result.get("comparison_table"),
            bundle=result.get("bundle"),
            follow_up_questions=result.get("follow_up_questions", []),
            followUps=result.get("followUps", []),
            data_freshness=result.get("data_freshness", "live"),
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")


