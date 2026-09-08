from __future__ import annotations

import os
from pathlib import Path


class Settings:
    _instance: Settings | None = None

    def __new__(cls) -> Settings:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # LLM Gateway
    LLM_CACHE_TTL_SECONDS: int = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "3600"))
    LLM_CACHE_MAX_ENTRIES: int = int(os.environ.get("LLM_CACHE_MAX_ENTRIES", "1000"))
    LLM_REQUEST_TIMEOUT: int = int(os.environ.get("LLM_REQUEST_TIMEOUT", "30"))
    LLM_COOLDOWN_BASE_SECONDS: int = int(os.environ.get("LLM_COOLDOWN_BASE_SECONDS", "10"))
    LLM_COOLDOWN_MAX_SECONDS: int = int(os.environ.get("LLM_COOLDOWN_MAX_SECONDS", "120"))
    LLM_MAX_INPUT_CHARS: int = int(os.environ.get("LLM_MAX_INPUT_CHARS", "6000"))
    LLM_MAX_CHUNK_CHARS: int = int(os.environ.get("LLM_MAX_CHUNK_CHARS", "3000"))
    OPENROUTER_FREE_REQ_PER_MIN: int = int(os.environ.get("OPENROUTER_FREE_REQ_PER_MIN", "20"))
    OPENROUTER_FREE_REQ_PER_DAY: int = int(os.environ.get("OPENROUTER_FREE_REQ_PER_DAY", "200"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

    # Pagination
    PAGINATION_TTL_SECONDS: int = int(os.environ.get("PAGINATION_TTL_SECONDS", "1800"))
    PAGINATION_MAX_ENTRIES: int = int(os.environ.get("PAGINATION_MAX_ENTRIES", "5000"))

    # Paths
    CHROMA_DB_PATH: str = os.environ.get("CHROMA_DB_PATH", str(Path(__file__).resolve().parent / "chroma_db"))
    LOG_DIR_PATH: str = os.environ.get("LOG_DIR_PATH", str(Path(__file__).resolve().parent / "logs"))

    # Apify
    APIFY_ACTOR_ID: str = os.environ.get("APIFY_ACTOR_ID", "apify~e-commerce-scraping-tool")
    APIFY_TIMEOUT_SECONDS: int = int(os.environ.get("APIFY_TIMEOUT_SECONDS", "45"))

    # Tavily
    TAVILY_MAX_SEARCH_RESULTS: int = int(os.environ.get("TAVILY_MAX_SEARCH_RESULTS", "10"))
    TAVILY_REQUEST_TIMEOUT: int = int(os.environ.get("TAVILY_REQUEST_TIMEOUT", "20"))

    # CORS
    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "*")

    # Auth
    API_AUTH_TOKEN: str = os.environ.get("API_AUTH_TOKEN", "")

    # Logging
    LOG_MAX_BYTES: int = int(os.environ.get("LOG_MAX_BYTES", str(100 * 1024 * 1024)))
    LOG_BACKUP_COUNT: int = int(os.environ.get("LOG_BACKUP_COUNT", "5"))

    # Rate limits
    SSE_MAX_QUEUE_SIZE: int = int(os.environ.get("SSE_MAX_QUEUE_SIZE", "128"))
    PENDING_TASK_TTL: int = int(os.environ.get("PENDING_TASK_TTL", "300"))

    # ChromaDB
    CHROMA_RETRIES: int = int(os.environ.get("CHROMA_RETRIES", "3"))
    CHROMA_BACKOFF_SECONDS: float = float(os.environ.get("CHROMA_BACKOFF_SECONDS", "1.0"))

    # Embedding
    EMBEDDING_MODEL_NAME: str = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    EMBEDDING_LOCAL_FILES_ONLY: bool = os.environ.get("EMBEDDING_LOCAL_FILES_ONLY", "true").lower() == "true"

    # Jina Reranker
    JINA_RERANK_ENABLED: bool = os.environ.get("JINA_RERANK_ENABLED", "false").lower() == "true"
    JINA_API_KEY: str = os.environ.get("JINA_API_KEY", "")
    JINA_RERANK_MODEL: str = os.environ.get("JINA_RERANK_MODEL", "jina-reranker-v3")
    JINA_RERANK_TOP_N: int = int(os.environ.get("JINA_RERANK_TOP_N", "20"))
    JINA_RERANK_ALPHA: float = float(os.environ.get("JINA_RERANK_ALPHA", "0.6"))


settings = Settings()
