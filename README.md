# AI Shopping Assistant - Intelligent Virtual Sales Associate

A full-stack modern web application featuring an intelligent conversational sales assistant designed to guide customers through e-commerce product discovery, comparisons, and budget-based selections.

---

## Tech Stack

- **Frontend**: React (Vite) + Tailwind CSS + Framer Motion + Zustand + Axios
- **Backend**: FastAPI + Python 3.11+ + Uvicorn + Pydantic
- **Vector Store**: ChromaDB (all-MiniLM-L6-v2 via ONNX)
- **LLM Gateway**: LiteLLM (OpenRouter, multiple free models)

---

## Project Structure

```
recommandtion chatbot/
├── backend/
│   ├── main.py                 # FastAPI App, CORS, Routes
│   ├── schemas.py              # Request/Response Pydantic models
│   ├── recommender.py          # Thin compatibility wrapper
│   ├── models/                 # Domain models (Product, etc.)
│   ├── services/               # Business logic layer
│   │   ├── llm_gateway.py      # Multi-model LLM router
│   │   ├── keyword_service.py  # LLM intent + keyword generation
│   │   ├── tavily_service.py   # Tavily search integration
│   │   ├── regex_parser.py     # Pure regex product extraction
│   │   ├── recommendation_service.py  # Composite scoring
│   │   ├── vector_service.py   # ChromaDB operations
│   │   └── ...
│   ├── routers/                # API route handlers
│   ├── pipeline/               # Orchestration pipeline
│   ├── requirements.txt
│   └── .env
├── frontend/
│   └── src/
│       ├── components/ChatComponents.jsx  # ProductCard, ComparisonView, etc.
│       ├── store/chatStore.js             # Zustand state + API calls
│       ├── App.jsx
│       └── main.jsx
├── run.py                      # Backend launcher (from project root)
├── .env
└── README.md
```

---

## Getting Started

### 1. Backend (FastAPI)

Ensure you have **Python 3.10+** installed.

Open a terminal at the **project root** (the folder containing `backend/`, `frontend/`, `run.py`).

Activate the virtual environment:
- **Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Windows (CMD)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```
- **macOS/Linux**:
  ```bash
  source .venv/bin/activate
  ```

Install dependencies:
```powershell
pip install -r backend/requirements.txt
```

Copy and configure environment variables:
```powershell
copy backend\.env .env
```

Launch the server (from project root):
```powershell
python run.py
```

The server starts at `http://127.0.0.1:8000` with hot-reloading. Verify at `http://127.0.0.1:8000/health`.

Alternative startup commands (also from project root):
```powershell
uvicorn backend.main:app --reload
```
or
```powershell
python -m backend.main
```

### 2. Frontend (Vite + React)

Open a **new terminal** at the project root:
```powershell
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`.

---

## Conversational Commands to Try

1. **Seasonal fashion**: *"I need clothes for Navratri"*
2. **Budget electronics**: *"Suggest a phone under 40000"*
3. **Lifestyle bundle**: *"I'm joining a gym"*
4. **Comparison**: *"Compare iPhone and Samsung phones"*
5. **Follow-up**: *"Show more"*

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Root info |
| GET | `/health` | Health check |
| POST | `/chat` | Conversational product search |
| POST | `/search` | Direct product lookup |
