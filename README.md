# liber
A Multi-Agent Book Recommendation System

# Book Intelligence Agent — MVP Spec (Token-Efficient)

*A Production-Oriented Multi-Agent Book Recommendation System with Token Optimizations*

---

# 1. MVP Goal

Build and deploy a minimal but production-minded system that:

- Uses **Open Library + Google Books APIs** for structured metadata
- **Scrapes reviews only** from Goodreads or alternatives
- Builds embeddings efficiently
- Uses a **3-agent pipeline**:
  - Profile user taste
  - Retrieve candidates
  - Generate explainable recommendations
- Exposes a public API
- Tracks latency, cost, token usage

---

# 2. Token-Saving Principles Applied

1. Preprocess metadata via APIs → no LLM needed
2. Summarize multiple reviews before embedding → fewer tokens
3. Cache embeddings and user taste profiles → avoid recomputation
4. Limit LLM input to top-N candidates → avoid sending full corpus
5. Structured JSON prompts for explanations → avoid verbose output
6. Choose smaller LLMs for summarization; reserve GPT-4-turbo for reasoning

---

# 3. System Overview (MVP Architecture)

```
                ┌────────────────────┐
                │     Web Client     │
                └─────────┬──────────┘
                          │
                      FastAPI
                          │
                ┌─────────▼──────────┐
                │  Agent Orchestrator│
                └─────────┬──────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
 Taste Profiler     Candidate Retriever   Explanation Agent
                          │
                ┌─────────▼──────────┐
                │ Recommendation API │
                └─────────┬──────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
  PostgreSQL          pgvector            Redis
 (Metadata DB)      (Embeddings)         (Cache)
                          │
                ┌─────────▼──────────┐
                │ Scraper Pipeline   │
                └────────────────────┘
```

---

# 4. Data Layer

## 4.1 Metadata (APIs Only)
- **Open Library API** for books, authors, subjects
- **Google Books API** as fallback
- Clean JSON → directly stored in PostgreSQL  
*No LLM calls needed → saves tokens*

## 4.2 Reviews (Scraped)
- Goodreads / alternatives
- Limit to **top 5–10 reviews per book**
- Preprocess HTML → extract text only
- Optional: summarize multiple reviews before embedding

## 4.3 Embeddings
- Store **review summaries + metadata** in **pgvector**
- Batch embedding generation
- Cache embeddings → avoid recomputation

---

# 5. Agent Pipeline (MVP)

### Agent 1: Taste Profiler
- Input: 3–5 favorite books
- Uses **cached embeddings + API metadata**
- Optional LLM call to summarize taste profile
- Output: structured JSON taste profile

### Agent 2: Candidate Retriever
- Uses **vector similarity search** in pgvector
- Filter top-N candidates
- **Only top candidates sent to LLM** for explanation

### Agent 3: Explanation Generator
- Structured JSON output: concise 2–3 sentence explanation
- Uses **taste profile + top-N candidates**
- Token-efficient prompts

---

# 6. Orchestration Flow

```
User Input
  → Taste Profile (cached embeddings)
  → Vector Search (pgvector)
  → Top-N selection
  → Explanation (LLM)
  → Return results
```

- Track **token usage, latency, embedding hits**
- Cache all reusable outputs

---

# 7. Storage Layer

- **PostgreSQL**: metadata, reviews, scrape logs, user profiles  
- **pgvector**: embeddings for metadata & reviews  
- **Redis**: cache for recommendations, embeddings, taste profiles  

---

# 8. Scraper Pipeline

- Queue-based (Redis + RQ)
- Scrape **only review text**
- Limit per book → reduce unnecessary LLM calls
- Rate-limited + retry/backoff
- Store raw HTML separately for debugging
- Preprocess → summarize → embed

---

# 9. Performance & Scaling

- Batch embeddings → reduces token/API cost
- Async FastAPI endpoints → lower latency
- Use smaller models for summarization → GPT-3.5
- Only GPT-4-turbo for reasoning/explanation

---

# 10. Deployment

- Dockerized containers: Backend, PostgreSQL, Redis
- Host: AWS EC2 / Fly.io
- Health checks, logging, metrics

---

# 11. What This MVP Demonstrates

- Hybrid ingestion pipeline: API + review scraping
- Token-efficient LLM usage
- Multi-agent orchestration
- Production-ready API + caching
- Observability on cost, latency, token consumption

---

# End of Token-Optimized MVP Spec
