# AiStockCN System Manual

This manual covers the current Docker Compose runtime, quantitative pipeline, research workers and safe operating procedures.

**Audience:** AiStockCN administrators and engineers

**Documentation baseline:** 14 August 2026

## Operating principles

1. Treat PostgreSQL deployment state and immutable artifact manifests as authoritative.
2. Build or restart only the services affected by a change.
3. Keep customer, credential, uploaded-document and runtime data outside Git.
4. Validate configuration before changing a running service.
5. Preserve run history; rerun failed work instead of rewriting prior records.

## Runtime services

| Service | Process | Responsibility |
| --- | --- | --- |
| `panel-web` | Next.js | Public product, authentication and server-side API gateway |
| `panel-api` | `uvicorn app.main:app` | Shared capability contract plus A-share data, models, portfolios and operations |
| `us-market-api` | `uvicorn app.us_market_main:app` | Read-only US market product data |
| `research-api` | `uvicorn app.research_main:app` | Research requests, documents, facts and evaluation |
| `research-worker` | `python -m app.research_worker` | Extraction, embeddings and filing-change jobs |
| `research-coverage-worker` | `python -m app.research_coverage_worker` | Issuer-level filing and financial-fact orchestration |
| `data-prep` | Python task container | Market-data, feature, training and backtest jobs |

## Configuration

Create local runtime files from the safe templates:

```bash
cp run/panel.env.example run/panel.env
cp run/panel_users.example.json run/panel_users.json
```

Set unique secrets and scrypt password hashes. Generate a password hash with:

```bash
node apps/web/scripts/hash-password.mjs 'replace-with-a-strong-password'
```

Do not commit the generated files. The Compose runtime also expects:

- the configured PostgreSQL network and AiStockCN schema;
- `pgvector` for research embeddings;
- the configured Ollama model on the AI-services network;
- persistent volumes for research documents and model caches.

## Validate and start

```bash
docker compose config --quiet
docker compose build panel-api us-market-api research-api panel-web
docker compose up -d \
  panel-api us-market-api research-api research-worker \
  research-coverage-worker panel-web
docker compose ps
```

Do not include `panel-web-fei` in an ordinary AiStockCN rebuild. It has an independent production boundary.

## US adjusted-history and model candidate

Backfill provider-adjusted OHLCV with durable lineage and a resumable run ID:

```bash
docker compose run --rm --entrypoint python data-prep scripts/backfill_us_daily_bars.py --years 3
```

Train the isolated `us_5d_v1` profile and run purged expanding-window validation:

```bash
docker compose run --rm --entrypoint python data-prep scripts/train_us_5d_model.py
```

The training command writes an immutable candidate and validation record. It never activates the model or enables US order submission.

## Health verification

Check container state and the public product:

```bash
docker compose ps
curl --fail --silent --show-error https://aistockcn.com/ >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8003/health
curl --fail --silent --show-error http://127.0.0.1:8004/health
```

Verify private APIs from their trusted frontend service:

```bash
docker compose exec panel-web node -e \
  "fetch('http://panel-api:8000/').then(r => { if (!r.ok) process.exit(1); console.log(r.status) })"

docker compose exec panel-web node -e \
  "fetch('http://research-api:8000/health').then(r => r.json()).then(console.log)"
```

Inspect recent service logs without following indefinitely:

```bash
docker compose logs --tail=100 panel-web research-api research-worker
```

## Deploy an application change

Build first, then recreate only the changed services. For a Research API change shared by workers:

```bash
docker compose build research-api
docker compose up -d --no-deps \
  research-api research-worker research-coverage-worker
docker compose ps research-api research-worker research-coverage-worker
```

For a customer-web change:

```bash
docker compose build panel-web
docker compose up -d --no-deps panel-web
docker compose ps panel-web
```

Run the health checks and inspect logs after every recreation.

## Quantitative workflow

### 1. Market-data preparation

`batch_download_all_a.py` coordinates A-share universe and raw market-data refresh. Persisted outputs include stock registry snapshots, daily price files and valuation data.

### 2. Training features

`feature_engineering.py` builds a model-ready panel with profile-specific future-return targets. Training data includes labels and must never be used as the live inference input.

### 3. Inference features

`build_inference_features.py` creates the current scoring snapshot with the stable feature schema and no future labels.

### 4. Training and candidate publication

`train_profile_runner.py` trains the selected profile and publishes an immutable Model Registry candidate containing model files, training metadata, inference scores and SHA-256 checksums. Training does not activate the candidate.

Example:

```bash
docker compose run --rm data-prep \
  python train_profile_runner.py --profiles medium_10d_v2
```

### 5. Walk-forward evaluation

`backtest_profile_runner.py` runs expanding-window out-of-sample evaluation with the profile's execution assumptions.

```bash
docker compose run --rm data-prep \
  python backtest_profile_runner.py --profile medium_10d_v2
```

Every result should be referenced by run ID, date range and method version. Do not compare gross legacy results with fee-aware realistic execution results as if they used the same assumptions.

### 6. Validation and activation

The administrator records validation in the Model Registry, then activates an eligible version. Activation is atomic and creates an audit event. Models, Picks and Paper resolve the same deployment row.

The profile catalog in `run/model_profiles.json` defines training parameters only; editing its default does not activate a model.

### 7. Paper reconciliation

`paper_trade_futu.py` resolves the paper-enabled deployment, verifies its manifest and keeps that model revision fixed for the reconciliation cycle. `paper_trade_daemon.py` starts a new cycle only when a new eligible signal snapshot is available.

## Research workflow

### SEC and document processing

1. The Research API creates or discovers an immutable document record.
2. A PostgreSQL queue records work and retry state.
3. A research worker extracts text and native locators.
4. The worker chunks text, creates BGE embeddings and stores them in pgvector.
5. Source status and lineage become visible to the administrator workspace.

### Filing changes

Filing-change runs are versioned. A rerun creates a linked record and review decisions are append-only. Operators should inspect both citations before confirming a material change.

### Retrieval evaluation

Run benchmark evaluation after changing chunking, embeddings, lexical search, fusion weights or reranker behavior. Compare Top-1 accuracy and MRR with the persisted lexical baseline before promoting the change.

## Test commands

Focused research service tests:

```bash
docker compose run --rm --no-deps -v "$PWD/tests:/tests:ro" research-api \
  python -m unittest discover -s /tests -p 'test_research_service.py'
```

Frontend production build:

```bash
npm --prefix apps/web run build
```

Repository-wide Python tests can be run in the established data-prep environment when validating shared pipeline changes.

## Incident response

### A page cannot reach an API

1. Check `docker compose ps`.
2. Test the target API from `panel-web`, not from an untrusted network location.
3. Confirm service names and private-network membership in the resolved Compose config.
4. Inspect the request ID and recent API logs.
5. Recreate only the failed service after configuration validation.

### A research request stops progressing

1. Inspect `research-api` and `research-worker` logs using the request or run ID.
2. Confirm Ollama and PostgreSQL connectivity from the relevant service network.
3. Check the durable job state in the Research Operations page.
4. Use the supported retry or rerun action so history is retained.

### A model shown by pages is inconsistent

1. Read the active `model_deployments` row and revision.
2. Confirm Models, Picks and Paper report the same version.
3. Verify the artifact manifest before paper execution.
4. Use a registry rollback or activation; never repair deployment state by copying model files.

## Backup scope

Operational recovery must include:

- PostgreSQL application, registry, research and review tables;
- immutable model artifacts and manifests;
- research source documents or configured object storage;
- ignored runtime configuration from the secure secret store;
- required persistent model-cache and document volumes where applicable.

Source code alone is not a complete operational backup.
