# AiStockCN System Design

AiStockCN is a multi-market financial research and operations platform. It combines market-data pipelines, quantitative model governance, portfolio workflows and source-grounded US company research behind one authenticated product.

**Audience:** product engineering, AI engineering, quantitative research and operations

**Documentation baseline:** 14 August 2026

## Design goals

- Keep China A-share and US market data, currencies, models and execution rules isolated.
- Provide one coherent customer product without coupling long-running workloads to page requests.
- Make every model deployment, financial calculation and AI citation traceable to persisted inputs.
- Separate customer research from administrative and operational controls.
- Prefer deterministic financial computation and immutable artifacts where consistency matters.
- Make failures observable and work safely retryable.

## System context

```mermaid
flowchart LR
    U["Investor or administrator"] --> W["Next.js product"]

    W --> A["A-share Panel API"]
    W --> M["US Market API"]
    W --> R["Research API"]

    A --> CN["A-share data, models, portfolios"]
    M --> US["US universe, prices, selections"]
    R --> SEC["SEC filings and Company Facts"]
    R --> PG["PostgreSQL / pgvector"]
    R --> L["Local Ollama"]

    R --> Q["Durable research queues"]
    Q --> DW["Document workers"]
    Q --> CW["Issuer orchestration worker"]

    A --> MR["Model Registry"]
    MR --> PT["Paper execution workflow"]
```

## Product surfaces

| Surface | Authorization | Backend |
| --- | --- | --- |
| A-share Overview, Explorer, Picks and Paper | Investor or administrator | `panel-api` |
| US Overview, Explorer, Picks and Paper | Investor or administrator | `us-market-api` plus selected panel services |
| Research Copilot | Investor or administrator | `research-api` |
| Platform operations | Administrator | `panel-api` |
| Research operations and evaluation | Administrator | `research-api` |

The web application is the public boundary. Internal FastAPI services bind to loopback on the host and accept requests only from configured networks or trusted service identities.

## Application architecture

### Next.js product

`apps/web` provides authentication, authorization, market-aware navigation and server-side request forwarding. It owns the customer presentation boundary and prevents browser clients from reaching internal APIs directly.

The A-share interface retains its established route family. US pages use a dedicated workstation shell and left navigation. Research Copilot is shared from the US workspace and uses company-level task navigation inside the selected security.

### Panel API

`app.main:app` serves the established A-share data and control plane:

- pipeline and reference-data status;
- dataset exploration;
- selections and inference snapshots;
- Model Registry state and activation;
- portfolio and paper-trading reconciliation;
- administrator workflow controls.

### US Market API

`app.us_market_main:app` is a separate read-only service for:

- the US stock master and exchange universe;
- current daily observations and coverage metadata;
- company search;
- rules-based selection snapshots;
- US model and paper activation gates.

The independent `us_5d_v1` profile cannot consume A-share training samples or execution rules. Historical-data, corporate-action and walk-forward gates control model and paper activation.

### Research API and workers

`app.research_main:app` handles company research, source documents, financial facts, retrieval, agent execution, filing changes and evaluation. CPU- and I/O-intensive work runs in separate workers.

PostgreSQL queues use atomic claims with `FOR UPDATE SKIP LOCKED`. Work state and retry metadata are durable, allowing an interrupted worker to resume without relying on in-memory process state.

## Research data model

```mermaid
erDiagram
    COMPANY ||--o{ DOCUMENT : has
    DOCUMENT ||--o{ CHUNK : contains
    COMPANY ||--o{ FINANCIAL_FACT : reports
    COMPANY ||--o{ RESEARCH_RUN : scopes
    RESEARCH_RUN ||--o{ RETRIEVED_EVIDENCE : records
    DOCUMENT ||--o{ FILING_CHANGE_RUN : compares
    FILING_CHANGE_RUN ||--o{ FILING_CHANGE : yields
    FILING_CHANGE ||--o{ REVIEW_EVENT : receives

    DOCUMENT {
      uuid id
      string symbol
      string accession
      string source_type
      string locator_type
      string sha256
      string status
    }
    CHUNK {
      uuid id
      uuid document_id
      int locator
      text content
      vector embedding
    }
    FINANCIAL_FACT {
      string symbol
      string taxonomy
      string concept
      string unit
      date period_end
      string accession
      decimal value
    }
    FILING_CHANGE_RUN {
      uuid id
      string algorithm_version
      json thresholds
      string status
    }
```

Actual schema initialization is implemented in the research document, financial and filing-change services. The diagram shows ownership and lineage rather than every physical column.

## Retrieval and answer generation

1. Document extraction preserves PDF page numbers or honest SEC HTML passage locators.
2. Text is split into overlapping chunks and embedded with `BAAI/bge-small-en-v1.5`.
3. PostgreSQL English full-text search produces lexical candidates.
4. `pgvector` cosine similarity produces semantic candidates.
5. Reciprocal-rank fusion combines both result sets.
6. A PyTorch cross-encoder reranks the candidate passages.
7. The agent receives a bounded evidence set plus approved tool output.
8. The server attaches citation metadata and validates the structured response.

The evidence record exists independently from the model's prose. This makes a cited claim inspectable even if the synthesis layer is changed.

## Deterministic financial boundary

SEC facts are stored with original taxonomy, concept, unit, period, filing form and accession. Canonical concept priorities select comparable values without deleting source lineage.

Annual and quarterly changes, margins, free cash flow, returns and volatility are computed in Python. The LLM can plan these tools and interpret the result; it cannot replace the typed calculation output.

## Quantitative pipeline

```mermaid
flowchart LR
    I["Universe and market-data ingestion"] --> N["Normalized Parquet artifacts"]
    N --> F["Training feature panel"]
    N --> S["Inference feature snapshot"]
    F --> T["Profile training"]
    T --> C["Immutable candidate + checksums"]
    C --> V["Walk-forward validation"]
    V --> R["PostgreSQL Model Registry"]
    R --> P["Ranked picks"]
    R --> E["Paper execution resolver"]
    S --> C
```

Training does not activate a model. Each candidate is written to an immutable artifact path with a SHA-256 manifest. Validation state and deployment state live in PostgreSQL.

## Model Registry

The Model Registry removes ambiguity between the model shown in Models, the snapshot used by Picks and the artifact used by Paper Trading.

| Table | Responsibility |
| --- | --- |
| `model_versions` | Market, version, profile, artifact path, manifest, training dates, validation and metrics |
| `model_deployments` | Exactly one active version per market, paper permission and monotonic revision |
| `model_activation_events` | Previous/new version, actor, reason, paper state and audit history |

Activation updates the deployment and audit event in one transaction. Consumers resolve the same deployment row. The paper executor verifies artifact checksums and keeps one resolved revision for the entire reconciliation cycle.

`run/model_profiles.json` is a training-profile catalog, not deployment state.

## Reliability controls

| Risk | Control |
| --- | --- |
| Long AI response | SSE lifecycle events and 10-second heartbeats |
| Unknown agent action | Schema validation and a server-side tool allow-list |
| Hallucinated citation | Server-owned source metadata attached after retrieval |
| Numeric inconsistency | Deterministic typed calculation tools |
| Duplicate document | SHA-256 deduplication and accession lineage |
| Interrupted background work | Durable PostgreSQL state, atomic claim and bounded retry |
| Conflicting model consumers | Transactional Model Registry deployment row |
| Unauthorized operations | Signed session, role checks and private API network boundary |
| Opaque retrieval change | Persisted Top-1, MRR and lexical-baseline evaluation |

## Security model

- Passwords are stored as scrypt hashes; plaintext password configuration is rejected.
- Session cookies are signed, HTTP-only and secure in production.
- Administrator authorization is checked on server routes and page entry points.
- Internal APIs restrict source networks and service identities.
- Runtime secrets, customer documents, model caches, datasets and logs are ignored by Git.
- Example configuration defines shape only and must be replaced before use.
- SEC access uses declared identification and controlled request pacing.

## Deployment model

Docker Compose is the local and current server deployment entry point. The main runtime separates:

- `panel-web`;
- `panel-api`;
- `us-market-api`;
- `research-api`;
- scaled `research-worker` processes;
- `research-coverage-worker`;
- existing PostgreSQL/pgvector and Ollama services on private networks.

Services are restarted independently, so research ingestion does not require rebuilding or restarting the A-share execution path.

## Observability

- request IDs and structured API latency logs;
- pipeline state and per-step artifacts;
- research run and filing-change history;
- document and job status in the administrator workspace;
- selection snapshot and market-data freshness;
- Model Registry activation and rollback audit events;
- persisted retrieval evaluation runs.
