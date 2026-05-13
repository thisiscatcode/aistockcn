# Production Research Results

This page summarizes the latest aggregate research and model artifacts produced by the production pipeline. The public repository excludes raw market data, broker credentials, live account state, and per-symbol trading records; only aggregate metrics are documented here.

## Latest Training Snapshot

| Metric | Value |
| --- | ---: |
| Profile | `short_5d` |
| Label horizon | 5 trading days |
| Label threshold | 2.0% forward return |
| Training rows | 3,298,426 |
| Validation rows | 302,788 |
| Training window | 2023-04-20 to 2026-01-28 |
| Validation window | 2026-01-29 to 2026-05-06 |
| Validation AUC | 0.5916 |
| Validation accuracy | 0.5743 |
| Validation precision | 0.4085 |
| Validation recall | 0.5299 |
| Validation positive rate | 0.3440 |

## Walk-Forward OOS Backtest

| Metric | Value |
| --- | ---: |
| Backtest window | 2024-05-09 to 2026-03-11 |
| Rows evaluated | 3,403,990 |
| Symbols evaluated | 5,009 |
| Trading dates | 700 |
| Rebalances | 90 |
| Minimum training window | 252 trading days |
| Rebalance frequency | Every 5 trading days |
| Retrain frequency | Every 20 rebalance dates |
| Portfolio size | Top 5 ranked names |
| OOS AUC | 0.5445 |
| OOS accuracy | 0.5789 |
| OOS precision | 0.3733 |
| OOS recall | 0.3742 |
| Gross total return | 675.49% |
| Gross CAGR | 191.13% |
| Maximum drawdown | -15.74% |
| Winning rebalance rate | 60.00% |
| Average rebalance return | 2.57% |
| Rebalance return volatility | 7.58% |

## Production Controls

- The control panel separates read-only review access from admin workflow controls.
- Runtime secrets are loaded from ignored local files and are not committed.
- Broker-facing order reconciliation is routed through a gateway agent rather than embedded directly in the web UI.
- Pipeline state is restartable through persisted state files and per-step artifacts.
- The dashboard exposes data freshness, reference-data coverage, model metadata, backtest outputs, and paper-trading state in one operator surface.

## Interpretation

The current model shows measurable out-of-sample signal quality, with validation AUC above 0.59 and strict walk-forward OOS AUC above 0.54 across the full A-share universe. Portfolio results are reported as gross research metrics from the saved production artifact; deployment decisions should continue to account for execution constraints, transaction costs, liquidity, limit-up/limit-down behavior, and broker gateway availability.
