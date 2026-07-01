import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.schemas import ChatRequest, ChatResponse, SearchContext
from backend.recommender import process_query
from backend.routers.chat import router as chat_router
from backend.routers.search import router as search_router
from backend.routers.llm_status import router as llm_status_router

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Shopping Assistant API",
    description="Backend API for the Intelligent Product Recommendation Chatbot",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(search_router)
app.include_router(llm_status_router)


@app.get("/")
def root():
    return {
        "message": "AI Shopping Assistant API is running!",
        "docs": "http://localhost:8000/docs",
        "health": "http://localhost:8000/health",
        "chat": "POST http://localhost:8000/chat",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Shopping Assistant API",
        "database_size": 0,
    }


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


