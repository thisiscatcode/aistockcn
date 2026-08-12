# User Guide

## Switching between A-shares and US stocks

Authenticated pages now show a market selector in the header:

- **US Stocks** opens the additive `/us/*` workspace in USD and New York market time.
- **A-Shares** returns to the established pages and existing A-share workflow.

The selected market is remembered in the browser. The two sides do not combine currencies, model artifacts, paper accounts or execution rules.

The US workspace currently provides live company data, rules-based selection, Research Copilot access and ingestion monitoring. The Models and Paper pages deliberately show validation gates until sufficient history and walk-forward results exist; a visible gated state is not a system error.

## What The Dashboard Is For

The web panel is built for operators and product users who need to inspect the current state of the quant workflow without opening files or shell logs manually.

## Main Pages

### Overview

- quick health snapshot
- latest dataset and model signals
- recent batch pulse

### Pipeline

- daily pipeline status
- per-step runtime details
- workflow control actions for admins

### Explorer

- inspect saved parquet datasets
- search, sort, and export records

### Models

- latest training metrics
- backtest summary
- feature importance

### Picks

- latest ranked inference results
- highest-scoring names in the current snapshot

### Paper

- paper-trading daemon status
- gateway health
- target holdings, live positions, and order history

### Admin

- schema and artifact alignment checks
- workflow map and runtime artifact overview

## Typical Review Flow

1. Open `Overview` for the current snapshot.
2. Inspect `Pipeline` to verify the latest workflow state.
3. Open `Picks` to review ranked signals.
4. Use `Models` to inspect validation and backtest metrics.
5. Use `Paper` when reviewing the downstream execution path.

## Login

The public repository includes only example auth files. For local use:

```bash
cp run/panel.env.example run/panel.env
cp run/panel_users.example.json run/panel_users.json
```

Update those local copies with your own secrets before starting the panel.
Panel users now use `password_hash` entries instead of plaintext `password`.
Generate a new hash with:

```bash
node apps/web/scripts/hash-password.mjs 'replace-with-a-real-password'
```
