# AI Shopping Assistant — Complete Project Overview

## Project Name
**SmartAssociate — AI-Powered Intelligent Product Recommendation Chatbot**

A conversational AI shopping assistant that acts as a virtual sales associate for e-commerce. Users can have natural language conversations to discover, compare, and evaluate products across multiple categories.

---

## Tech Stack

### Frontend
| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.2.7 | UI library |
| Vite | 8.1.0 | Build tool & dev server |
| Zustand | 5.0.14 | State management (with localStorage persistence) |
| Tailwind CSS | 3.4.19 | Utility-first CSS styling |
| Framer Motion | 12.42.0 | Animations & transitions |
| Lucide React | 1.21.0 | Icon library |
| Axios | 1.18.1 | HTTP client for API calls |
| PostCSS | 8.5.15 | CSS processing |
| Autoprefixer | 10.5.2 | CSS vendor prefixes |
| Oxlint | 1.69.0 | Linting |

### Backend
| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Runtime |
| FastAPI | 0.100+ | Web framework |
| Uvicorn | 0.22+ | ASGI server |
| Pydantic | 2.0+ | Data validation |
| LiteLLM | 1.40+ | Multi-provider LLM orchestration |
| ChromaDB | 0.5+ | Vector database (persistent) |
| sentence-transformers | 2.2+ | Embeddings (all-MiniLM-L6-v2) |
| Tavily Python | — | Web search & extract API |
| httpx | 0.27+ | Async HTTP client |
| Selenium | — | JS-rendered page scraping |
| WebDriver Manager | — | ChromeDriver management |
| numpy | — | Vector math for similarity |
| python-dotenv | 1.0+ | Environment variable management |

### External Services / APIs
| Service | Purpose |
|---------|---------|
| **OpenRouter** (free tier) | LLM inference via Gemini 2.0 Flash, Llama 3.3 70B, Qwen 2.5 Coder, Llama 3.1 8B, Llama 3.2 3B |
| **Apify** (e-commerce-scraping-tool) | Live e-commerce product scraping from Amazon.in, Flipkart, Croma |
| **Tavily** | Web search + URL content extraction from supported e-commerce domains |
| **Google Gemini API** | Fallback LLM provider |
| **Groq API** | Fallback LLM provider |

---

## Complete Project Structure

```
├── .gitignore
├── .venv/                          (Python virtual environment)
├── .vscode/settings.json
├── run.bat                          (Windows launcher batch script)
├── run.py                           (Python orchestration launcher — venv setup, deps install, parallel process mgmt)
├── README.md                        (Project README with setup & run instructions)
├── SYSTEM_WORKFLOW.md               (Detailed end-to-end workflow documentation)
├── system_workflow_diagram.png       (Architecture diagram)
├── AI_Shopping_Chatbot_Documentation.pdf
├── Problem Statement - Intelligent Product Recommendation Chatbot.pdf
│
├── backend/
│   ├── .env                          (API keys: OPENROUTER, TAVILY, APIFY, GEMINI, GROQ)
│   ├── .env.example                  (API keys template)
│   ├── __init__.py
│   ├── main.py                       (FastAPI app — CORS, routers, health endpoint, legacy chat)
│   ├── schemas.py                    (Pydantic models: ChatRequest, ChatResponse, Message, SearchContext, ResponseType)
│   ├── db.py                         (Minimal in-memory product list — legacy/unused)
│   ├── recommender.py                (Legacy compatibility wrapper around pipeline)
│   ├── requirements.txt              (Python dependencies)
│   ├── chroma_db/                    (Persistent ChromaDB vector database — auto-created)
│   ├── logs/                         (Log files: pipeline.log, apify.log, tavily_raw.jsonl, extracted_products.jsonl)
│   │
│   ├── models/
│   │   └── product.py                (Pydantic models: ProductInput, ProductOutput, ExtractedProduct, ProductSchema)
│   │
│   ├── pipeline/
│   │   └── shopping_pipeline.py      (Core orchestrator — 520 lines: intent, search, scoring, ranking, response gen)
│   │
│   ├── routers/
│   │   ├── chat.py                   (POST /chat, GET /chat/stream/{session_id} — SSE, pagination, ConnectionManager)
│   │   ├── search.py                 (POST /search endpoint)
│   │   └── llm_status.py             (GET /llm-status — model usage, rate limits, cooldowns)
│   │
│   ├── scripts/
│   │   └── load_data.py              (Script to load JSON data files into ChromaDB collections)
│   │
│   └── services/
│       ├── apify_service.py          (Apify e-commerce-scraping-tool integration + simulation fallback)
│       ├── cache_service.py          (Cache hit/miss logic with TTL & similarity threshold)
│       ├── discovery_task.py         (Background async discovery — scrape, score, store, broadcast via SSE)
│       ├── embedding_service.py      (sentence-transformers all-MiniLM-L6-v2 embedding generation)
│       ├── extract_service.py        (Tavily Extract API wrapper for URL content extraction)
│       ├── extraction_service.py     (Regex-based product extraction from Tavily results)
│       ├── keyword_service.py        (LLM-powered intent classification + keyword generation + budget parsing + gender detection)
│       ├── llm_gateway.py            (Multi-model LLM gateway — 5 OpenRouter free models, round-robin, rate limiting, chunking)
│       ├── local_database_service.py (Legacy local JSON file database loader)
│       ├── local_intent_classifier.py(Few-shot semantic intent classifier using embeddings — 181 examples)
│       ├── pipeline_logger.py        (Structured logging for pipeline)
│       ├── product_cache.py          (ChromaDB-based semantic product cache with TTL)
│       ├── product_parser.py         (LLM + regex product parsing from web content)
│       ├── product_repository.py     (Repository pattern for ChromaDB operations)
│       ├── product_service.py        (Pagination store, product enrichment, deduplication, image cleaning)
│       ├── recommendation_service.py (Composite scoring: semantic 0.4 + price 0.3 + rating 0.2 + completeness 0.1)
│       ├── regex_parser.py           (Domain-specific regex parsers for Amazon, Flipkart, Myntra, Nykaa, Croma)
│       ├── search_service.py         (Tavily search wrapper with multi-query parallel support)
│       ├── selenium_scraper.py       (Selenium-based JS-rendered page scraper)
│       ├── tavily_service.py         (Full Tavily search + extract + product URL crawling pipeline — 963 lines)
│       ├── vector_service.py         (ChromaDB vector store — CRUD on category collections, multi-collection search)
│       └── extraction/               (Modular extraction pipeline sub-package)
│           ├── cleaner.py            (Text cleaning — boilerplate removal, deduplication)
│           ├── product_block_detector.py (Splits content into product blocks by headers/indicators)
│           ├── field_extractor.py    (Regex field extraction: name, price, brand, specs, ratings)
│           ├── normalizer.py         (Data normalization, ID generation)
│           ├── validator.py          (Field validation, duplicate/ad detection)
│           ├── storage_service.py    (Supabase storage integration)
│           ├── parser.py             (PipelineParser orchestrator composing all extraction steps)
│           └── embedding_service.py  (Embedding text builder for extracted products)
│
├── data/                             (24 product catalog data files — JSON + CSV pairs)
│   ├── clothing_data.json/csv        (1,744 fashion products)
│   ├── womens_clothing_data.json/csv (Fashion)
│   ├── kids_clothing_data.json/csv   (Fashion)
│   ├── shoes_data.json/csv           (Footwear)
│   ├── watches_data.json/csv         (Electronics)
│   ├── phones_data.json/csv          (Smartphones)
│   ├── laptops_5pages.json/csv       (Laptops)
│   ├── laptops.json, shoes.json, watches.json, smartphones.json
│   ├── traditional_wear.json, formal_wear.json, casual_wear.json, sports_wear.json
│   ├── home_decor.json, kitchen.json, lighting_solutions.json, cleaning_supplies.json
│   ├── sports_and_outdoors.json, toys_and_games.json
│
└── frontend/
    ├── package.json, package-lock.json
    ├── vite.config.js, tailwind.config.js, postcss.config.js
    ├── public/ (favicon.svg, icons.svg)
    └── src/
        ├── main.jsx                  (React entry point)
        ├── index.css                 (Tailwind + glassmorphism global styles)
        ├── App.css                   (Legacy styles)
        ├── App.jsx                   (Main app component — 903 lines: sidebar, chat, cart, comparison)
        ├── assets/ (vite.svg, react.svg, hero.png)
        ├── store/
        │   └── chatStore.js          (Zustand store — conversations, cart, SSE, API calls, pagination, persist)
        └── components/
            └── ChatComponents.jsx    (534 lines: ProductCard, ComparisonView, BundleView, SuggestedPrompts, etc.)
```

---

## Features Implemented

### 1. Conversational Shopping Assistant
- Multi-turn conversations with context awareness
- Natural language understanding via LLM intent classification (7 intent types: RECOMMEND, COMPARE, FOLLOW_UP, BUNDLE, EXPLAIN, GENERAL, GREETING)
- Clarification handling (e.g., asking Men/Women for fashion queries)
- Follow-up question support ("Show more", "Compare these", "Accessories for that")
- Context-aware query reconstruction for clarification answers
- Conversation history tracked per session (last 5 turns used for context)

### 2. Intelligent Product Discovery Pipeline
The pipeline (`shopping_pipeline.py`) follows these steps:

1. **LLM Intent Detection & Keyword Generation** — Uses OpenRouter LLM to classify user intent and extract ~10 shopping keywords
2. **Category Classification** — Maps user query to one of 8 canonical categories (smartphones, laptops, fashion, beauty, footwear, home_appliances, electronics, other)
3. **Gender Detection** — For fashion/footwear/beauty categories, detects men/women/unisex preference
4. **ChromaDB Vector Search** — Semantic search across category collections with fallback chain
5. **Keyword Re-scoring** — 60% keyword match + 40% vector similarity
6. **Multi-Factor Ranking** — Composite score: semantic(0.4) + price(0.3) + rating(0.2) + completeness(0.1)
7. **Threshold Check (0.70)** — If local score >= 0.70, return instantly + background Apify discovery; else synchronous Apify scrape
8. **LLM Response Generation** — For product reference queries, generates natural language response
9. **Comparison Generation** — For COMPARE intent, generates LLM-powered side-by-side comparison
10. **Response Assembly** — Builds final response with products, follow-ups, pagination token

### 3. Hybrid Data Sources
- **Local Database**: 24 pre-loaded product catalog files (JSON + CSV) loaded into ChromaDB via `load_data.py`
- **Live Scraping (Apify)**: Real-time crawling of Amazon.in, Flipkart, Croma via Apify `e-commerce-scraping-tool` actor
- **Live Search (Tavily)**: Web search across 5 supported e-commerce domains (Flipkart, Amazon.in, Myntra, Nykaa, Croma) with content extraction
- **Selenium Scraper**: JavaScript-rendered page scraping as fallback for dynamic content
- **Simulation Fallback**: When API keys are unavailable, generates realistic mock products per category (smartphones, fashion with winter/ethnic/casual variants, beauty, general)

### 4. Product Recommendation Scoring
Composite score formula:
```
Composite Score = 0.30 Semantic Similarity + 0.15 Keyword Frequency
                + 0.25 Category Match + 0.20 Budget Penalty
                + 0.05 Brand Preference + 0.05 Occasion/Style Match
```
- Products scored and ranked; threshold 0.70 for "cache hit" vs "cache miss"
- Gender filtering applied post-ranking
- Budget-aware scoring with tiered price relevance (0.15 to 1.0 based on budget utilization)

### 5. Real-Time Streaming (SSE)
- GET `/chat/stream/{session_id}` — Server-Sent Events endpoint
- When local results are good (score >= 0.70), background task spawns Apify discovery
- New products broadcast to frontend via SSE (ConnectionManager with asyncio.Queue per session)
- Frontend dynamically appends new products to existing results without page reload

### 6. Product Comparison
- Side-by-side comparison matrix with specification rows (price, brand, rating, specs)
- LLM-generated AI overview summarizing differences (via OpenRouter)
- Local fallback heuristic comparison when LLM unavailable (compares price, brand, rating, up to 6 specs)
- Interactive compare checkbox on product cards
- Comparison drawer/panel in the UI

### 7. Shopping Cart
- Add/remove products with quantity management (+/- controls)
- Cart subtotal calculation with Indian number formatting (rupees)
- Simulated checkout flow with success animation
- Cart badge on sidebar icon

### 8. Multi-Chat Sessions
- Multiple concurrent conversations with sidebar
- Auto-creates fresh chat on app start
- Chat sidebar with collapse/expand (responsive: auto-collapses on mobile)
- Delete conversation with confirmation
- Zustand persist middleware saves conversations and cart to localStorage
- Chat titles auto-generated from first user message

### 9. LLM Gateway with Rate Limiting
- **5 OpenRouter free models**: Gemini 2.0 Flash, Llama 3.3 70B, Qwen 2.5 Coder 32B, Llama 3.1 8B, Llama 3.2 3B
- **6 task profiles**: intent_classification, context_keyword_generation, product_extraction, response_generation, comparison, summarization
- Round-robin task distribution across models (least-used first)
- Automatic cooldown on rate limits (30s per model on 429 errors)
- Chunked processing for large content (splits at page boundaries, merges JSON arrays)
- Token usage tracking per model
- Status endpoint (`/llm-status`) showing per-model stats, cooldowns, rate limit estimates
- Graceful degradation: falls back through model list, then to local regex/fallback

### 10. Domain-Specific Data Extraction
- Specialized regex parsers for Amazon.in, Flipkart, Myntra, Nykaa, Croma
- Content cleaning: removes navigation, ads, boilerplate
- Product URL crawling from category/listing pages
- Robust brand, price, rating, specification extraction
- Tavily Extract integration for deep URL content extraction

### 11. Multi-Layer Intent Classification
- **LLM-based**: Primary intent classification via OpenRouter with structured JSON output
- **Few-shot semantic**: Local `LocalIntentClassifier` using embedding similarity against 181 labeled examples
- **Regex fallback**: Keyword-based intent matching (compare → COMPARE, hello → GREETING, etc.)
- **Category fallback**: Keyword matching for 8 categories + related mappings

### 12. Pagination ("Show More")
- In-memory pagination store keyed by session + query hash
- Products retrieved in chunks of 3
- "Show More" button on frontend triggers pagination API call
- Background Apify discovery also triggered on pagination
- Fallback to ChromaDB direct query if pagination store empty

### 13. Error Handling & Graceful Degradation
- SSE error handling with console logging
- API error state with retry suggestions
- Server connection error messages with suggested fallback queries
- Pipeline exception handling at every stage
- All LLM calls wrapped in try/catch with fallbacks

### 14. UI/UX Features
- Glassmorphism design with gradient backgrounds
- Typing indicator (pulsing dots animation)
- Skeleton loader for product cards while loading
- Suggested prompt buttons (Navratri Outfits, Camera Phone, Coding Laptop, Gym Gear, Photography Phone)
- Markdown-style message formatting (bold, italic, headers, lists)
- Product cards with image, name, brand, price, MRP, discount, rating, specs
- Product card actions: Add to Cart, Compare checkbox, View on source website
- Cart drawer with item list, quantities, subtotal, checkout button
- Comparison drawer with spec matrix and AI overview
- Responsive design (mobile-friendly with collapsible sidebar)

### 15. Data Product Enrichment
- Product image URL cleaning (replaces Amazon CDN images with Unsplash placeholders to avoid broken images)
- Indian rupee formatting with lakh/crore notation
- Deduplication by product URL (both in API response and frontend)
- Rating display with star icons
- Brand extraction fallback from product name

### 16. Configuration & Deployment
- `run.py`: Auto-creates venv, installs deps, starts backend + frontend in parallel, handles Ctrl+C cleanup
- `run.bat`: Windows batch launcher for `run.py`
- Environment variables: OPENROUTER_API_KEY, TAVILY_API_KEY, APIFY_API_TOKEN, GEMINI_API_KEY, GROQ_API_KEY
- Single-command setup: `python run.py` or double-click `run.bat`

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Root info |
| `/health` | GET | Health check |
| `/chat` | POST | Main chat endpoint (supports `?page_token=` for pagination) |
| `/chat/stream/{session_id}` | GET | SSE stream for real-time product broadcasting |
| `/search` | POST | Direct product search |
| `/llm-status` | GET | LLM gateway status (model usage, rate limits, cooldowns) |
| `/chat-legacy` | POST | Legacy chat endpoint (compatibility wrapper) |

---

## Data Flow

```
User Query
    ↓
Intent Classification (LLM → Few-shot → Regex)
    ↓
Category Mapping + Gender Detection
    ↓
Budget Parsing
    ↓
ChromaDB Vector Search (with category fallback chain)
    ↓
Keyword Re-scoring & Multi-Factor Ranking
    ↓
Threshold Check (0.70)
    ├── Score ≥ 0.70 → Return instantly + Background Apify Discovery → SSE Broadcast
    └── Score < 0.70 → Synchronous Apify Scrape → Score & Rank → Store in ChromaDB → Return
    ↓
LLM Response Generation (for product references)
    ↓
Comparison Generation (for COMPARE intent)
    ↓
Response Assembly → JSON Response + SSE streaming
```

---

## Key Architectural Decisions

1. **No external database**: Everything is file-based (ChromaDB persists to disk; no PostgreSQL/MySQL)
2. **Free-tier LLMs**: Relies on OpenRouter's free models with automatic fallback chain; no paid API required
3. **Graceful degradation**: Every LLM call has 2-3 fallbacks (other models → local classifier → regex)
4. **Apify simulation fallback**: If Apify API key missing, generates realistic mock products based on intent (including seasonal/occasion-aware products)
5. **Image hotlink protection**: Amazon CDN images replaced with Unsplash placeholders to avoid broken images
6. **Production launcher**: Single `python run.py` command handles venv creation, dependency installation, and parallel process management with clean shutdown
7. **In-memory pagination**: Full result list stored in memory per session/query for efficient cursor-based pagination
8. **SSE for real-time updates**: Background discovery results pushed to frontend via Server-Sent Events without polling
