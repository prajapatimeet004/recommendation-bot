# AI Shopping Assistant

A conversational AI shopping assistant with multi-chat sessions and context-aware LLM recommendations.

---

## Prerequisites

- Python 3.10+
- Node.js 18+

---

## Setup & Run

### 1. Backend

```powershell
# From project root
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# Configure API keys
copy backend\.env.example backend\.env
# Edit backend\.env and add your keys:
#   OPENROUTER_API_KEY  (https://openrouter.ai/keys)
#   TAVILY_API_KEY      (https://app.tavily.com)
#   APIFY_API_TOKEN     (https://console.apify.com)

# Start backend
uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 3. Open

- **Frontend**: http://localhost:5173
- **Backend**: http://localhost:8000
- **Health**: http://localhost:8000/health

---

## Quick Start Commands

| Try this | What happens |
|----------|-------------|
| *"Best laptop under ₹80,000"* | Budget-aware product search |
| *"I need clothes for Navratri"* | Seasonal fashion recommendations |
| *"Show me Samsung tablets"* | Brand search |
| *"Accessories for that"* | Follow-up (uses chat context) |
| *"Compare iPhone and Samsung"* | Side-by-side comparison |
| *"Show more"* | Paginate results |

---

## Environment Variables

| Variable | Required | Get it at |
|----------|----------|-----------|
| `OPENROUTER_API_KEY` | Yes | https://openrouter.ai/keys |
| `TAVILY_API_KEY` | Yes | https://app.tavily.com |
| `APIFY_API_TOKEN` | Yes | https://console.apify.com |
| `GEMINI_API_KEY` | No | Fallback LLM |
| `GROQ_API_KEY` | No | Fallback LLM |
