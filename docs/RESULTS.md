# Quantitative Model Evaluation Record

This document records reproducible aggregate metrics from saved AiStockCN artifacts. It is an evaluation record, not a statement of customer returns, live-account performance or future investment results.

**Artifact baseline:** 13 August 2026

**Market:** China A-shares

## Latest immutable model candidate

| Field | Value |
| --- | --- |
| Model version | `cn-medium_10d_v2-20260813T135516Z-26eef061` |
| Profile | `medium_10d_v2` |
| Trained at | 2026-08-13 13:55 UTC |
| Validation status in candidate record | `pending` |
| Objective | LightGBM regression |
| Target | Cross-sectionally demeaned 10-trading-day future return |
| Return definition | Next-day open to horizon close |
| Score | Cross-sectional percentile rank |
| Training rows | 3,159,602 |
| Validation rows | 586,646 |
| Training dates | 2023-04-20 to 2026-01-28 |
| Validation dates | 2026-01-29 to 2026-07-30 |

### Holdout metrics

| Metric | Value |
| --- | ---: |
| Mean absolute error | 0.07255 |
| Root mean squared error | 0.10797 |
| Information coefficient | 0.01398 |
| Rank information coefficient | 0.06304 |

Source: immutable registry record and training metadata under `quant_data/model_registry/CN/cn-medium_10d_v2-20260813T135516Z-26eef061/` in the production workspace. Runtime datasets and model binaries are excluded from the public repository.

## Latest saved realistic walk-forward run

| Field | Value |
| --- | --- |
| Run ID | `20260806T200252Z__medium_10d_v2` |
| Method | `realistic_execution_v1` |
| Evaluation dates | 2025-05-23 to 2026-07-17 |
| Rows evaluated | 3,719,855 |
| Symbols evaluated | 4,991 |
| Trading dates | 789 |
| Minimum training window | 504 trading days |
| Rebalances | 57 |
| Rebalance frequency | Every 5 trading days |
| Retrain frequency | Every 4 rebalances |
| Portfolio size | 20 names |
| Maximum replacements | 4 names per rebalance |
| Research capital | RMB 1,000,000 |

### Predictive and portfolio metrics

| Metric | Value |
| --- | ---: |
| Out-of-sample MAE | 0.06206 |
| Out-of-sample RMSE | 0.09861 |
| Out-of-sample IC | -0.00713 |
| Out-of-sample Rank IC | 0.05492 |
| Net simulated total return | -14.52% |
| Net simulated CAGR | -12.57% |
| Maximum drawdown | -26.31% |
| Winning rebalance rate | 52.63% |
| Total simulated fees | RMB 19,437.51 |
| Execution skips | 20 |

## Execution assumptions

The recorded run uses a T+1 open-proxy simulation with:

- 100-share board lots;
- 5% cash buffer;
- 50 bps simulated slippage;
- commission, minimum commission, platform fee and sell stamp duty;
- liquidity participation limits;
- minimum trading-amount filters;
- price-limit skip rules;
- target-value sizing and bounded constituent replacement.

These assumptions materially differ from older gross-return experiments. Metrics from different method versions must not be compared without normalizing execution, fees, capital and rebalance rules.

## Governance

- A training run publishes an immutable candidate; it does not activate that candidate.
- Validation status and deployment state are separate records.
- The live `model_deployments` row is the authoritative source for the model used by Models, Picks and Paper.
- Activation and rollback write append-only audit events.
- Paper execution resolves one deployment revision, verifies checksums and holds it for the full reconciliation cycle.
- Research metrics remain distinct from broker-reported account performance.

## Interpretation

Rank IC is positive in both the current holdout and saved walk-forward artifact, while the fee-aware portfolio result for the recorded period is negative. The appropriate product conclusion is that predictive ranking quality and investable portfolio performance must be evaluated separately. Capital deployment requires an approved validation record that includes transaction costs, liquidity, price limits, corporate actions and operational readiness.

## Reproduce the profile evaluation

```bash
docker compose run --rm data-prep \
  python train_profile_runner.py --profiles medium_10d_v2

docker compose run --rm data-prep \
  python backtest_profile_runner.py --profile medium_10d_v2
```

New runs create new IDs and artifacts; they do not alter the record documented above.
