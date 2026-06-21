# 🚀 Lead-Gen Pipeline for Social Media

An autonomous social media listening and response pipeline that finds relevant user queries across platforms, validates intent through a 2-tier filter, generates contextual responses using RAG, and queues everything for **human review** before posting.

> **PoC Note**: Company name is censored (BCI) throughout for development safety.

## Architecture

```
Ingestion Spokes → Central Hub (Filter + RAG) → Review Queue → Human Approval → Throttled Execution
```

### Key Components

| Component | Purpose |
|---|---|
| **Ingestion Spokes** | Platform-specific readers (Reddit, YouTube, X, Quora) |
| **Pipeline** | Deduplication → Tier-1 Keyword Filter → Tier-2 LLM Intent Validation |
| **RAG Engine** | FAISS (dense) + BM25 (sparse) + Cross-Encoder reranking |
| **Generator** | LLM-powered grounded response generation |
| **Dashboard** | Admin UI for review queue, metrics, and audit log |
| **Execution** | Throttled poster respecting per-platform rate limits |

### Supported Platforms

| Platform | Read | Write | Method |
|---|---|---|---|
| Reddit | ✅ Auto | ✅ Human-triggered | JSON endpoint / OAuth2 API |
| YouTube | ✅ Auto | ✅ Human-triggered | Data API v3 |
| X (Twitter) | ✅ Auto | ✅ Human-triggered | API v2 |
| Quora | ✅ Auto | 📋 Manual copy-paste | Playwright scraper |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/wrathog12/Lead-Gen-Pipeline-For-Social-Media.git
cd Lead-Gen-Pipeline-For-Social-Media

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
copy .env.example .env
# Edit .env with your API keys

# 5. Run
uvicorn api.server:app --reload
```

## Project Structure

```
├── data/              # Schemes dataset, raw scrapes, FAISS index
├── src/
│   ├── ingestion/     # Platform readers
│   ├── pipeline/      # Filter + generation pipeline
│   ├── rag/           # Hybrid search engine
│   ├── execution/     # Throttled platform posters
│   └── utils/         # Config, schemas, logging
├── dashboard/         # Admin UI (templates + static)
├── api/               # FastAPI backend + routes
└── tests/             # Test suite
```

## License

Internal PoC — Not for public distribution.
