# AiStockCN Research Copilot

Production-oriented US equity research on top of AiStockCN's existing market-data platform. The customer site remains isolated at `aistockcn.com`; the copilot is deployed at `research.aistockcn.com`.

## Deployment status

| Component | Status |
| --- | --- |
| Public Research Copilot | Live at `research.aistockcn.com` |
| Customer platform | Live at `aistockcn.com` on an isolated frontend image |
| Current public runtime | Docker Compose on the existing AiStockCN host |
| Paid LLM API | Not required; the current agent uses local Ollama |

## What is live

- Company search over the existing US equity universe and market-history tables.
- Official SEC EDGAR discovery and sync for the latest 10-K, 10-Q and 8-K, using accession-number deduplication and declared fair-access identification.
- PDF upload with validation, SHA-256 deduplication and page-preserving extraction.
- Background ingestion worker using PostgreSQL `FOR UPDATE SKIP LOCKED`.
- BGE embeddings in `pgvector`, PostgreSQL full-text search, reciprocal-rank fusion and a PyTorch cross-encoder reranker.
- Natural-language answers that render document evidence separately from model inference and preserve server-owned source locators.
- A local Ollama `qwen2.5:3b` planner/synthesizer; no paid OpenAI key is required.
- Structured tool plans, server-side tool allow-listing, SSE progress events and multi-company comparison.
- A live reranker benchmark with persisted Top-1 accuracy, MRR and lexical-baseline results.
- Request IDs, structured latency logs, retries with exponential backoff, rate limiting and privacy-conscious run telemetry.
- Docker Compose services for the API, background worker and frontend.

## Architecture

```mermaid
flowchart LR
    U["User"] --> W["Next.js research frontend"]
    W --> A["FastAPI research API"]
    A --> P["Structured agent planner\nOllama qwen2.5:3b"]
    A --> D["AiStockCN US market data\nPostgreSQL"]
    A --> E["SEC EDGAR\nsubmissions + filing archive"]
    A --> H["Hybrid retrieval\nFTS + pgvector + RRF"]
    H --> R["PyTorch cross-encoder\nreranker"]
    A --> Q["PostgreSQL queue\nSKIP LOCKED"]
    A --> S["Shared volume or encrypted S3\nsource documents"]
    E --> S
    Q --> K["Document ingestion worker"]
    S --> K
    K --> V["Pages, chunks, vectors\nPostgreSQL / pgvector"]
    V --> H
    A --> O["Logs, run telemetry,\nevaluation results"]
```

The LLM never provides the citation metadata shown by the UI. The server attaches `document_id`, filename, locator and source URL from retrieval results. Uploaded PDFs retain native page numbers. SEC filing HTML has no reliable native pagination, so it is cited as `SEC filing HTML · passage N` and is never mislabeled as a PDF page. Model-generated interpretation is kept in a separate field and rendered in a separate card.

## Source-grounding contract

Every completed research response separates:

- `evidence`: retrieved document passages carrying server-owned document and locator metadata;
- `inference`: model synthesis generated from evidence and deterministic tool output;
- `limitations`: unavailable filings, missing coverage and other qualifications;
- `trace`: the allow-listed tools executed by the agent.

This prevents a fluent model answer from being presented as documentary evidence. Users can follow the original source link and inspect the cited PDF page or SEC HTML passage.

## Request path

1. The authenticated frontend sends a company-scoped question.
2. The local LLM returns a JSON tool plan. The API drops any tool not in the server allow-list.
3. The executor queries company/market data, runs deterministic return and volatility calculations, and conditionally runs document retrieval.
4. Hybrid retrieval combines PostgreSQL English FTS and cosine search over BGE vectors using reciprocal-rank fusion.
5. `cross-encoder/ms-marco-MiniLM-L-6-v2` reranks the candidate passages with PyTorch.
6. The local LLM synthesizes only from the supplied context.
7. The API emits SSE lifecycle events and a final structured response with evidence, inference, limitations and trace.

## Local development

The research stack is deliberately separate from the customer frontend image.

```bash
docker build -t aistockcn-research-api:20260813-sec-v1 -f apps/api/Dockerfile.research .
docker build -t aistockcn-research-web:20260813-sec-v1 -f apps/web/Dockerfile .
docker compose up -d research-api research-worker panel-web-research
docker compose ps research-api research-worker panel-web-research
```

Required runtime values already used by the current installation are read from `run/panel.env`. Do not commit that file. Optional cloud document storage is enabled with `RESEARCH_S3_BUCKET`; local Compose uses the shared `research-uploads` volume when the variable is empty.

The Compose configuration intentionally joins the existing `paper-db` and `ai-services` networks because the copilot is integrated with the live platform database and local Ollama service. A new machine must provide equivalent PostgreSQL/pgvector and Ollama services rather than expecting seeded sample data.

## User workflow

1. Open `research.aistockcn.com` and select a company from the AiStockCN US equity universe.
2. Sync the latest 10-K, 10-Q and 8-K from SEC EDGAR, or upload a PDF. The document moves through queued, extracting and search-ready states while preserving its source lineage.
3. Ask a company-specific question. The API streams progress while the agent selects and executes its allow-listed document, market-data and calculation tools.
4. Review the answer's Document evidence, Model inference and Limitations sections. Each passage includes its filename and an honest native-page or SEC-HTML locator.
5. Compare two or three companies. The system executes the required tools for each company before synthesizing the comparison.
6. Use the evaluation page to monitor Top-1 accuracy, MRR, lexical baseline and per-query ranks when the retrieval pipeline changes.

## Operational boundaries

- Docker Compose is the current public runtime.
- Real credentials, uploaded documents, logs, model caches and runtime state are excluded from Git.
- The example secret files define configuration shape only and must never be applied unchanged.
