# System Design Spec

## Goal

Build an operator-friendly multi-market quant workflow that can ingest data, train market-specific models, produce ranked signals, run backtests, and coordinate paper trading through external gateways.

The A-share workflow is stable and remains the system of record for its existing routes and artifacts. United States equity functionality is additive rather than a refactor of this workflow.

## Additive US Market Architecture

- `apps/web/app/us` provides dedicated `/us/*` product pages.
- `app.us_market_main` runs as a separate, read-only `us-market-api` service.
- The service reads `us_stock_master`, `us_stock_daily_metrics`, US selection snapshots and job history.
- The existing panel API and A-share pages keep their current contracts.
- The US model is an independent `us_5d_v1` pipeline; it must never consume A-share training samples or execution rules.
- US paper trading remains disabled until historical coverage, corporate-action handling and walk-forward validation pass.

The initial US market-data gate requires at least 504 trading dates. Until that gate passes, the product may display company data and rules-based screening but must report the ML model as `insufficient_history` and paper trading as `gated`.

## Web-Fei Protection Boundary

Web-Fei is versioned in the separate private [aistockcn-web-fei](https://github.com/thisiscatcode/aistockcn-web-fei) repository and is outside the US product scope. The current production checkout remains at `apps/web-fei`; its container image, runtime configuration, API contracts and database semantics must remain unchanged. US deployments target only the dedicated US API/workers and the main `apps/web` frontend.

## Main Components

- `download_data.py` and `batch_download_all_a.py`
  - universe refresh and raw parquet ingestion
- `feature_engineering.py`
  - training feature generation
- `build_inference_features.py`
  - inference-only feature generation
- `train_lightgbm.py`
  - model training, metadata export, and scoring
- `backtest_walk_forward.py`
  - walk-forward historical evaluation
- `paper_trade_futu.py` and `paper_trade_daemon.py`
  - paper-trading orchestration
- `apps/api`
  - operational API layer
- `apps/web`
  - dashboard and control surface

## Architecture

The system is organized around local parquet artifacts and deterministic workflow steps.

1. Step 1 refreshes the stock universe and raw market data.
2. Step 2 converts raw data into the training panel.
3. Step 3 builds the latest inference snapshot.
4. Step 4 trains the model and writes scores.
5. Step 5 runs backtests on historical windows.
6. Step 6 consumes scored snapshots and reconciles paper-trading intent.

The API and dashboard sit on top of those artifacts and runtime logs rather than duplicating state in a separate application database.

## Deployment Model

- Docker Compose is the primary local and server deployment entry point.
- The panel API serves both inspection and workflow-control routes.
- API client IP checks should stay narrow: localhost plus explicitly trusted local services only.
- The web app reads the panel auth config from mounted runtime files.

## Security Model

- Public repos should include only example config files.
- Runtime secrets are expected to live in local `run/` files that are git-ignored.
- The panel uses signed cookies and an admin key for workflow control endpoints.
- Recent changes also redact the paper-trading agent key from generated control-panel log stubs.

## Operational Priorities

- clear artifact lineage
- restartable batch jobs
- inspectable logs and state files
- low-friction local deployment
- explicit workflow visibility for operators
