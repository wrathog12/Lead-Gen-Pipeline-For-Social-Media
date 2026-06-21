SYSTEM CONTEXT & ARCHITECTURE ARTIFACT

Project: ICICI Bank Autonomous Social Media Commenting Agent (PoC)
Developer: Abhishek Choudhary
Role: AI Intern, ICICI Bank (ICICI Prudential AMC & Retail Banking)
Last Updated: June 2026

1. Project Overview

The objective is to build an autonomous, multi-platform AI agent capable of finding, validating, and replying to user queries across social media platforms with highly relevant ICICI Bank schemes (Mutual Funds, Loans, Credit Cards, Deposits).

To prevent brand risk and "spammy" behavior, the system relies on a strict Hub-and-Spoke architecture, a 2-Tier Intent Filtering Pipeline, and a Hybrid Search RAG (Retrieval-Augmented Generation) engine.

2. Core Architecture (Hub-and-Spoke)

The system is decoupled to ensure rate limits on one platform do not block processing on another.

Ingestion Spokes (Readers): Independent workers polling specific platforms (Reddit, Quora, YouTube, X). They fetch raw data, normalize it into a standard JSON schema, and push it to the Central Hub.

Central Hub (The Brain): An asynchronous FastAPI backend that processes the queue. It handles Deduplication, Tier-1 Filtering, Tier-2 Validation, Scheme Retrieval, and Response Generation.

Execution Spokes (Writers): Independent workers that take the generated responses and publish them back to the respective platforms via API or headless browser automation.

3. Processing Pipeline (Central Hub)

Step 3.1: Deduplication Layer

Mechanism: Hybrid system utilizing the unique post_id or URL + an in-memory cache (Redis/Dict) with a 72-hour TTL (Time-To-Live).

Purpose: Ensures the agent never evaluates or comments on the same post twice.

Step 3.2: Tier-1 Filter (The Net)

Mechanism: High-speed Regex and Keyword matching (BM25 baseline).

Purpose: Drops ~80% of noise with zero compute cost. If a post contains no financial triggers (e.g., "loan", "invest", "tax", "ICICI"), it is discarded immediately.

Step 3.3: Tier-2 Filter (LLM Intent Validation)

Mechanism: Lightweight LLM (e.g., Gemini 2.5 Flash).

Purpose: Semantic intent scoring (0-100). The LLM checks if the user is actually asking for advice.

Score > 85: User is asking for help -> Pass to Generation.

Score < 85: User is complaining, sharing news, or making a joke -> Drop post to protect brand reputation.

Step 3.4: RAG / Scheme Routing (Hybrid Search)

Dataset: 60 structured ICICI products (AMC, Loans, Cards).

Mechanism: 1.  Dense Search: FAISS vector index retrieves top semantic matches based on LLM embeddings.
2.  Sparse Search: BM25 matches exact keywords.
3.  Reranking: A Cross-Encoder reranker takes the Top-5 candidates and scores them against the user's specific query to find the absolute best match.

Step 3.5: Generation Agent

Mechanism: LLM dynamically generates a concise, helpful, and platform-appropriate 2-3 sentence comment weaving the user's query with the retrieved ICICI scheme's vector_description.

4. Platform Specific Strategies

Reddit: Ingestion via .json backdoor (no API keys needed for reading). Execution in a private test sandbox (r/ICICIPoC_Test) via OAuth2 API to bypass Karma/Age restrictions.

Quora: Ingestion & Execution via Headless Browser Automation (Selenium/Playwright) and BeautifulSoup, as Quora has no public API.

YouTube: Full support via YouTube Data API v3.

X (Twitter): API v2 Stream (Free tier constrained to 1,500 posts/month).

5. Data Schemas

Standardized Ingestion Post Schema

{
  "platform": "reddit",
  "post_id": "t3_15abcde",
  "author": "user123",
  "subreddit": "IndiaInvestments",
  "url": "[https://reddit.com/](https://reddit.com/)...",
  "timestamp": "2026-06-21T10:00:00",
  "text": "Full title and body of the post."
}


ICICI Scheme Database Schema

{
  "scheme_id": "ICICI_PRU_BLUECHIP",
  "scheme_name": "ICICI Prudential Bluechip Fund",
  "metadata": {
    "category": "Mutual Fund",
    "risk_level": "Very High"
  },
  "bm25_keywords": ["bluechip", "large cap", "equity"],
  "vector_description": "An open-ended equity scheme predominantly investing in large-cap stocks..."
}


6. Project Directory Structure

icici-social-agent/
│
├── data/
│   ├── raw/                        # Temporarily stored JSON scrapes
│   ├── database/                   # The 60-item icici_schemes_dataset.json
│   └── vector_store/               # FAISS index files (generated locally)
│
├── src/
│   ├── ingestion_spokes/
│   │   ├── reddit_ingester.py      # Uses JSON backdoor
│   │   ├── quora_ingester.py       # Selenium/Playwright scraper
│   │   ├── youtube_ingester.py     # API worker
│   │   └── x_ingester.py           # API worker
│   │
│   ├── central_hub/
│   │   ├── deduplicator.py         # TTL Cache logic
│   │   ├── tier1_filter.py         # Regex/Keyword engine
│   │   ├── tier2_validator.py      # LLM Intent scoring module
│   │   └── generator.py            # LLM Comment generation module
│   │
│   ├── rag_engine/
│   │   ├── embedder.py             # Converts descriptions to vectors
│   │   └── hybrid_search.py        # Combines FAISS + BM25 + Cross-Encoder
│   │
│   └── execution_spokes/
│       ├── reddit_poster.py        # OAuth2 API poster
│       └── quora_poster.py         # Selenium web driver
│
├── api_server.py                   # FastAPI backend orchestrating the queue
├── requirements.txt
└── README.md
