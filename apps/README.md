# AiStockCN Application Services

This directory contains the customer-facing web application and the FastAPI services that support AiStockCN's China A-share, US equity and source-grounded research workflows.

## Applications

| Path | Responsibility | Runtime |
| --- | --- | --- |
| `api/` | Panel API, isolated US Market API, Research API and background research workers | FastAPI / Python 3.12 |
| `web/` | Authenticated AiStockCN product, including A-shares, US Intelligence and Research Copilot | Next.js 15 / React 19 |
| `web-fei/` | Protected production checkout maintained under a separate repository boundary | Next.js |

## API entry points

| Module | Service | Purpose |
| --- | --- | --- |
| `app.main:app` | `panel-api` | A-share data, model registry, selections, portfolios and operations |
| `app.us_market_main:app` | `us-market-api` | Read-only US market universe, observations, selections and model readiness |
| `app.research_main:app` | `research-api` | Company research, filings, financial facts, retrieval, agent execution and evaluation |
| `app.research_worker` | `research-worker` | Document extraction, chunking, embedding and filing-change jobs |
| `app.research_coverage_worker` | `research-coverage-worker` | Issuer-level SEC filing and financial-fact orchestration |

The browser never calls these internal APIs directly. The Next.js server authenticates the user, applies role checks and forwards approved requests over the private Compose network.

## Service boundaries

- Existing A-share routes continue through `panel-api`.
- US market pages read through the isolated, read-only `us-market-api`.
- Research workloads use `research-api` plus background workers so document processing cannot block the customer interface.
- Customer pages require an authenticated investor or administrator session.
- Operational research pages under `/admin/research` require the administrator role.

## Build and run

From the repository root:

```bash
docker compose build panel-api us-market-api research-api panel-web
docker compose up -d \
  panel-api us-market-api research-api research-worker \
  research-coverage-worker panel-web
docker compose ps
```

Runtime credentials belong in ignored files under `run/`; only the `.example` templates are safe to commit.

See the [documentation index](../docs/README.md) for the customer guide, architecture and operating procedures.
