# System Manual

## End-to-End Workflow

### Data Prepare

`batch_download_all_a.py` coordinates the full-market data refresh.

Outputs include:

- active stock universe snapshots
- canonical stock registry history
- per-symbol daily kline parquet files
- per-symbol daily valuation parquet files

### Training Features

`feature_engineering.py` merges raw artifacts into a model-ready training table and derives labels such as forward return and binary classification targets.

### Inference Features

`build_inference_features.py` creates the latest scoring snapshot with the same stable feature schema but without future labels.

### Training And Scoring

`train_lightgbm.py` trains a profile, saves metadata, and writes ranked inference scores. `train_profile_runner.py` then publishes those files as a new immutable Model Registry candidate with a checksum manifest. Training does not activate a model.

### Validation And Activation

PostgreSQL is the single source of truth for deployment state:

- `model_versions` stores immutable candidates and validation results;
- `model_deployments` stores one active version per market and whether Paper Trading may use it;
- `model_activation_events` stores actor, reason, previous/new version and revision for audit and rollback.

The Models and Picks APIs resolve this deployment row. The admin activation endpoint changes it in one transaction. No model files are copied and the training-profile catalog is never used as active state.

### Backtesting

`backtest_walk_forward.py` runs expanding-window walk-forward backtests and writes comparable run artifacts for later review.

### Paper Trading

`paper_trade_futu.py` resolves the paper-enabled deployment from PostgreSQL, verifies all artifact checksums, and converts that exact score snapshot into target holdings and simulated orders for an external Futu gateway. One resolved version is held for the entire reconciliation cycle.

`paper_trade_daemon.py` keeps watching for new score snapshots and only reconciles when a new signal set appears.

## Operational Scripts

The repository includes dedicated runner scripts for stable container naming, log capture, and PID/state artifacts:

- `run_a_share_3y_batch.sh`
- `run_full_market_3y_batch.sh`
- `run_step2_feature_engineering.sh`
- `run_step3_inference_features.sh`
- `run_step4_train_score.sh`
- `run_step5_backtest.sh`
- `run_paper_trading_daemon.sh`

## Artifact Philosophy

This project uses inspectable immutable artifacts for data/model payloads and a small transactional database control plane for state that must be consistent:

- parquet datasets for core pipeline outputs
- JSON metadata embedded with each model artifact
- PostgreSQL for model validation, activation, paper enablement and audit history
- log files for batch and daemon visibility

That choice makes the system easier to inspect, validate, and operate in a small-team environment.
