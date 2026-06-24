# Social Media Lead Generation Pipeline — Project Report

**Project**: Autonomous Social Media Commenting Agent (PoC)
**Developer**: Abhishek Choudhary
**Date**: June 2026

---

## 1. The Problem

Every day, thousands of people across Reddit, YouTube, X (Twitter), and Quora ask genuine financial questions — *"Which mutual fund should I start a SIP in?"*, *"Best credit card for travel in India?"*, *"How should I plan for retirement?"*. These are real humans, at the exact moment of purchase intent, asking for help in public.

Banks spend millions on digital advertising to reach these exact people. But by the time an ad appears in their feed, the moment has passed. The question was asked, answered by strangers, and the user moved on.

**What if the bank could be the one answering those questions?**

Not as a corporate account dropping brochure links — but as a genuinely helpful voice, recommending the right product at the right time, in the tone the platform expects. That's what this pipeline does.

---

## 2. Why This Is Hard

### 2.1 Social Media Is Hostile to Automation

Each platform has evolved sophisticated defences against automated engagement. Building a system that works across all four required navigating fundamentally different constraints:

| Platform | Access Method | Key Constraint |
|----------|--------------|----------------|
| **Reddit** | OAuth2 API (PRAW) | Strict rate limits (60 req/min). Subreddits have Karma and account-age requirements. Overly promotional comments get downvoted and flagged by community moderators. |
| **YouTube** | Data API v3 | Quota-based billing (10,000 units/day). A single video search costs 100 units. Comment replies are quota-cheap but heavily monitored for spam. |
| **X (Twitter)** | API v2 (Pay-per-use) | $0.005 per tweet read. Free tier capped at 1,500 posts/month. Tweet character limits (280 chars) compress all intent signals into very short text. |
| **Quora** | Headless Browser (Playwright) | **No public API at all.** Requires browser automation to even read questions. Login modals, CAPTCHAs, and anti-bot detection make any automation fragile. Posting cannot be automated — it must be done manually by a human. |

### 2.2 The Brand Risk Problem

An automated system that posts the wrong thing — on the wrong post — even once — creates a PR crisis. Imagine the bank's AI replying with a mutual fund recommendation under a post where someone is grieving a financial loss. Or replying to a sarcastic joke about bank fees with a genuine product pitch.

This is why **every design decision in this pipeline prioritises safety over reach**. We would rather miss 100 genuine leads than make 1 embarrassing public reply.

---

## 3. System Architecture

### 3.1 Hub-and-Spoke Design

The system follows a **hub-and-spoke architecture** where each platform is an independent "spoke" and a central FastAPI backend acts as the "hub" that orchestrates all processing.

```
┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│   Reddit     │  │   YouTube    │  │  X (Twitter) │  │    Quora     │
│  Ingester    │  │  Ingester    │  │  Ingester    │  │  Ingester    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │                  │
       └────────────┬────┴────────┬────────┘                  │
                    ▼             ▼                           ▼
              ┌──────────────────────────────────────────────────┐
              │                CENTRAL HUB                       │
              │                                                  │
              │   Dedup → Tier-1 → Tier-2 → RAG → Generator     │
              │                                                  │
              └──────────────────────┬───────────────────────────┘
                                     ▼
                          ┌─────────────────────┐
                          │  ADMIN DASHBOARD     │
                          │  Human-in-the-Loop   │
                          │  Review & Approve    │
                          └──────────┬──────────┘
                                     ▼
                    ┌────────────────────────────────┐
                    │    EXECUTION SPOKES (Posters)   │
                    │  Reddit │ YouTube │ X │ Quora   │
                    └────────────────────────────────┘
```

**Why this design?**

- **Isolation**: A rate-limit hit on Reddit doesn't block YouTube processing. Each spoke operates independently.
- **Normalisation**: Every spoke transforms its platform-specific data into a single standard schema. The hub doesn't care *where* a post came from — it processes them all identically.
- **Extensibility**: Adding a new platform (e.g., LinkedIn, Instagram) means writing one new ingester spoke. The entire pipeline, RAG engine, and dashboard work unchanged.

### 3.2 The Ingestion Layer

Each ingester is built to respect its platform's ecosystem:

- **Reddit**: Searches 4 Indian finance subreddits (`r/IndiaInvestments`, `r/personalfinanceindia`, `r/CreditCardsIndia`, `r/indiapersonalfinance`) with 12 financial keyword queries. Uses PRAW's built-in rate limiting.

- **YouTube**: Uses consolidated search queries (3 groups with `|` OR operators) to minimise API quota consumption. Fetches top-level comments from discovered videos and enriches each comment with the parent video's title and description for better context during filtering.

- **X (Twitter)**: Uses a two-group query structure — `(financial keywords) AND (India geo-context)` — so every fetched tweet is both financially relevant and India-specific. Terms like "lakh", "crore", "Nifty", "Sensex" serve as geo-anchors.

- **Quora**: Since Quora has no API, we use Playwright to launch a headless Chromium browser, navigate to seed question pages about Indian finance, and extract related questions from the sidebar. The entire browser operation runs in a separate thread to avoid conflicts with the server's event loop — a non-trivial engineering challenge on Windows.

---

## 4. The 2-Tier Filtering Pipeline

### 4.1 Why Two Tiers?

Social media is overwhelmingly noise. In a typical run, we might fetch 300+ posts across all platforms. Of those, maybe 20-30 are genuine leads. Sending all 300 to an LLM for analysis would be slow, expensive, and wasteful.

The solution is a **funnel**:

```
  300 raw posts
       │
  ┌────▼─────┐
  │  Tier-1  │  Fast keyword + regex check
  │  Filter  │  Zero LLM cost
  └────┬─────┘
       │  ~60 posts survive (~80% dropped)
  ┌────▼─────┐
  │  Tier-2  │  LLM intent scoring (Gemini Flash)
  │  Filter  │  Concurrent (5 parallel calls)
  └────┬─────┘
       │  ~20 posts survive
       ▼
  RAG + Generation
```

### 4.2 Tier-1: The Keyword Net

**Cost**: Zero. Pure regex and string matching.

A curated set of ~30 financial trigger keywords (`"mutual fund"`, `"SIP"`, `"loan"`, `"tax saving"`, `"ELSS"`, etc.) plus regex patterns for financial amounts (`"10 lakh"`, `"5 crore"`) and advice-seeking phrases (`"where to invest"`, `"best fund"`).

If a post contains none of these signals, it is immediately discarded. This eliminates roughly 80% of all fetched content with zero computational cost.

**Exception**: X (Twitter) posts bypass Tier-1 entirely. Tweets are too short (≤280 characters) for keyword matching to be reliable — a genuine financial question might be just *"SIP worth it?"* with no other keywords. Instead, X posts go directly to Tier-2 with a lowered threshold.

### 4.3 Tier-2: LLM Intent Validation

**Cost**: 1 Gemini Flash API call per post (concurrent, semaphore-limited to 5).

This is where the system distinguishes between someone *asking for advice* and someone *complaining, joking, or sharing news*. The LLM scores each post 0-100 with a detailed rubric:

| Score Range | Intent Level | Example |
|------------|-------------|---------|
| 90-100 | **Strong Lead** | *"Which mutual fund should I start SIP in?"* |
| 85-89 | **Moderate Lead** | *"How should I plan for retirement?"* |
| 70-84 | **Weak / Ambiguous** | *"My SIP gave 15% returns last year"* |
| 40-69 | **Noise** | *"Bank app is down again"* |
| 0-39 | **Irrelevant** | *"lol this meme about taxes"* |

**Only posts scoring ≥ 85 (or ≥ 75 for X) advance to the RAG stage.** Everything else is logged and dropped.

The prompt is platform-aware — it tells the LLM whether it's looking at a full Reddit paragraph, a short tweet, a YouTube comment with video context, or a Quora question. This platform context significantly improves scoring accuracy.

---

## 5. RAG — Why Not Just Match by Intent?

### 5.1 The Naive Approach and Why It Fails

A simpler system might work like this: *"The user asked about mutual funds → recommend a mutual fund."* But ICICI alone has 30+ mutual fund schemes. Which one? The Bluechip Fund? The Overnight Fund? The Infrastructure Fund?

Random matching is worse than no matching. Recommending an ultra-high-risk infrastructure fund to someone asking about safe savings is not just unhelpful — it's potentially harmful and a regulatory violation.

### 5.2 Hybrid Search Architecture

The RAG engine uses a **FAISS + BM25 hybrid search** with Reciprocal Rank Fusion to find the single best-matching scheme for each user query:

**Dense Search (FAISS)**: The `all-MiniLM-L6-v2` sentence transformer converts the user's post into a 384-dimensional vector and searches against pre-computed embeddings of all scheme descriptions. This captures *semantic* similarity — it understands that *"Where should I park money safely?"* is semantically close to the Fixed Deposit scheme, even without sharing keywords.

**Sparse Search (BM25)**: Traditional keyword overlap matching using each scheme's curated `bm25_keywords` field. This catches *exact term matches* that semantic search might miss — for instance, if someone explicitly mentions "ELSS" or "PPF", BM25 directly surfaces those schemes.

**Score Fusion (RRF)**: Reciprocal Rank Fusion combines both ranked lists into a single final ranking, without requiring score normalisation across different scales.

### 5.3 Why Embeddings Are Pre-computed

The scheme dataset is static — ICICI's product lineup doesn't change every hour. So all scheme embeddings are computed **once**, saved as a FAISS index file on disk, and loaded into memory at server startup. At query time, only the user's post text needs to be embedded (a single vector computation taking ~10ms), and the FAISS search over ~50 schemes takes microseconds.

This means the entire RAG retrieval — from raw post text to best-matching scheme — completes in **under 50 milliseconds**.

---

## 6. Grounded Comment Generation

### 6.1 Platform-Specific Prompts

A Reddit comment that sounds like a tweet gets downvoted. A Quora answer that sounds like a Reddit post feels out of place. Each platform has its own tone, length, and formatting expectations.

The generator uses **separate prompt templates per platform**:

| Platform | Tone | Length | Style |
|----------|------|--------|-------|
| Reddit | Casual, like a friend chatting about money | 2-3 sentences | Plain text, no markdown |
| YouTube | Warm, engaging, community-member feel | 2-3 sentences | Plain text |
| X (Twitter) | Punchy, direct, value-packed | Under 250 characters | Ultra-compact |
| Quora | Educational, authoritative yet warm | 3-4 sentences | Flowing prose |

### 6.2 Strict Grounding Rules

The LLM is explicitly instructed to **only use information from the retrieved scheme data**. It cannot invent features, promise returns, cite interest rates not in the data, or mention competitor banks. Every generated comment includes soft calls-to-action (*"you might want to check out details on icicibank.com"*) rather than pushy sales language.

This is a critical regulatory safeguard. Financial product recommendations are heavily regulated in India. By grounding every response exclusively in the scheme's official description, we eliminate the risk of the LLM hallucinating financial claims.

### 6.3 Concurrent Generation

Comment generation is the slowest stage — each Gemini API call takes 3-5 seconds. With 60 posts passing Tier-2, sequential processing would take ~4 minutes.

The pipeline runs generation concurrently using `asyncio.gather` with a semaphore limiting to 5 parallel API calls. This reduces the same 60-post batch to **~30 seconds** — a 8x speedup.

---

## 7. Human-in-the-Loop — Why Not Fully Automate?

### 7.1 The Argument for Full Automation

A fully automated system would be faster. Detect a lead, generate a comment, post it — all within seconds. In theory, this maximises reach and response speed.

### 7.2 Why We Chose Not To

**Regulatory Risk**: Financial product suggestions carry legal weight in India. An AI system that autonomously posts financial recommendations without human oversight creates regulatory liability. SEBI and RBI regulations require that financial product communications meet specific disclosure and accuracy standards. A human reviewer ensures every posted comment meets these requirements.

**Brand Safety**: Even with a 85+ intent threshold, edge cases exist. Sarcasm, cultural context, and rapidly evolving internet language create situations where the AI misreads intent. A single inappropriate comment on a viral post could cause significant reputational damage. The cost of one bad post far exceeds the benefit of faster response times.

**Platform Terms of Service**: Reddit, YouTube, and X all explicitly prohibit "coordinated inauthentic behaviour" and "automated bulk posting." A fully automated system risks account suspension or permanent bans. Human-triggered posting — where a person reviews, approves, and clicks "Post" — maintains compliance with platform ToS.

**Quality Control Loop**: Human review creates a feedback signal. When reviewers consistently reject a certain type of generated comment, it reveals prompt engineering issues or gaps in the scheme dataset. This feedback loop drives iterative improvement in ways that a fully autonomous system cannot.

### 7.3 The Dashboard

The admin dashboard presents each generated draft alongside the original post, the matched scheme, the intent score, and a one-click approve/reject interface. Comments can be expanded to read the full text before approval.

For Quora, where API-based posting is impossible, the dashboard provides a "Copy & Open" workflow — the human copies the generated answer and manually pastes it on Quora.

---

## 8. Why Quora Can't Be Fully Automated

Quora is the only platform in this pipeline where even *reading* requires browser automation. There is no public API, no JSON endpoint, no RSS feed. Every interaction requires rendering a full JavaScript-heavy web application in a headless browser.

**Reading**: We use Playwright to launch headless Chromium, navigate to seed question URLs about Indian finance, and extract related question links from the page. Login modals must be dismissed programmatically. Each page load takes 5+ seconds, and we add respectful delays between navigations.

**Writing**: Quora's anti-automation measures make programmatic posting extremely fragile. The platform detects headless browsers, requires authenticated sessions, and uses dynamic element selectors that change frequently. Any automated posting attempt risks:
- Immediate account suspension
- CAPTCHA challenges that halt the automation
- Shadow-banning where posts appear to be published but are invisible to other users

**Our Approach**: For Quora, the pipeline handles everything up to generating the answer. The dashboard shows the Quora question URL alongside the AI-generated answer. The human reviewer opens the Quora page, verifies the context, and manually posts the answer. This respects Quora's platform policies while still providing the AI-generated content advantage.

---

## 9. Data Layer

### 9.1 Database Design

The system uses SQLite with WAL (Write-Ahead Logging) mode for the PoC. Three core tables track the entire lifecycle:

- **IngestedPosts**: Every fetched post from any platform, with its Tier-1 pass/fail status, Tier-2 score, and metadata. Even posts that fail filtering are stored for analytics.
- **DraftComments**: AI-generated responses linked to their source posts, with the matched scheme name, relevance score, review status (`pending → queued → posted / rejected`), and timestamps for each state transition.
- **PipelineRuns**: Metrics for each ingestion run — posts fetched, posts filtered, drafts generated, timestamps, and completion status. This enables monitoring pipeline health over time.

### 9.2 Deduplication

A hybrid deduplication layer prevents the system from processing the same post twice:
- **In-memory cache**: Fast dictionary lookup using `post_id` with a 72-hour TTL. Catches duplicates within the same server session.
- **Database check**: Queries the `IngestedPosts` table by `post_id`. Catches duplicates across server restarts.

### 9.3 Pydantic Validation

Standardised Pydantic models (`IngestedPost`, `BCIScheme`, `DraftComment`) enforce data shape across every pipeline boundary. When a Reddit ingester produces a post dict and a YouTube ingester produces a post dict, both must conform to the same schema before entering the hub. This eliminates an entire class of "it worked on Reddit but crashed on YouTube" bugs.

Enums for `Platform` (`reddit | youtube | x | quora`) and `ReviewStatus` (`pending | approved | rejected | posted | failed`) ensure that typos in status strings never propagate through the system.

---

## 10. Execution and Rate Limiting

### 10.1 Throttled Posting

Even after human approval, comments are not posted all at once. The execution layer uses platform-specific rate limiting:

| Platform | Delay Between Posts | Reason |
|----------|-------------------|--------|
| Reddit | 10+ seconds | PRAW enforces OAuth2 rate limits |
| YouTube | 2 seconds | Quota-based, but rapid posting triggers spam detection |
| X | 2 seconds | API rate limits on write endpoints |
| Quora | Manual | Human paces their own posting |

### 10.2 Batch Queue Processing

The system supports both single-comment posting (review and post one at a time) and batch queue processing (approve all pending drafts for a platform, then post them sequentially in a background task with rate limiting).

---

## 11. Key Design Decisions — Summary

| Decision | Alternative Considered | Why We Chose This |
|----------|----------------------|-------------------|
| 2-tier filtering | Single LLM filter for all posts | Tier-1 eliminates 80% noise at zero cost, saving both time and money |
| Hybrid RAG (FAISS + BM25) | Intent-based random scheme matching | Ensures the *right* product is recommended, not just *a* product |
| Human-in-the-loop | Full automation | Regulatory compliance, brand safety, platform ToS |
| Per-platform prompts | Single generic prompt | Each platform has different tone/length expectations |
| Pre-computed embeddings | Real-time embedding of schemes | Scheme data is static; pre-computing saves ~50 scheme embeddings per query |
| Concurrent generation | Sequential LLM calls | 8x faster pipeline execution (4 min → 30 sec) |
| Hub-and-spoke architecture | Monolithic pipeline | Platform isolation, extensibility, independent failure handling |
| Thread-isolated Playwright | Direct async Playwright | Windows event loop compatibility with FastAPI |
| SQLite with WAL | PostgreSQL | Zero-setup PoC, WAL enables concurrent reads during writes |

---

## 12. Results and Observations

From live pipeline runs on real social media data:

- **Reddit**: Highest lead quality. Indian finance subreddits have users who write detailed, advice-seeking posts. High Tier-2 pass rate (~30-40% of fetched posts score ≥ 85).
- **YouTube**: Highest volume. Comment threads on finance videos generate hundreds of comments, but most are reactions ("great video!") rather than advice-seeking. Lower Tier-2 pass rate (~10-15%).
- **X (Twitter)**: Smallest volume due to API cost constraints. India-centric query filtering ensures relevance, but tweet brevity makes intent classification harder. Tier-2 threshold lowered to 75 for this reason.
- **Quora**: Good lead quality (questions are inherently advice-seeking) but lowest volume due to browser automation limitations.

---

## 13. Future Scope

- **Feedback Loop**: Track which posted comments receive upvotes/engagement and use this signal to fine-tune the Tier-2 scoring rubric and generation prompts.
- **Multi-language Support**: Expand beyond English to Hindi and regional languages, which dominate Indian social media conversations about personal finance.
- **Production Database**: Migrate from SQLite to PostgreSQL for multi-worker deployments and proper connection pooling.
- **LinkedIn & Instagram**: Add ingestion spokes for professional and visual-first platforms where financial advice discussions are growing.
- **A/B Testing**: Test different comment tones and lengths to identify what resonates best on each platform.

---
