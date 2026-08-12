# A-Share Medium 10D V2

`medium_10d_v2` is an additive profile. It does not replace or rename the existing `short_1d` through `short_5d` profiles.

## Strategy definition

- Universe: current A-share model candidate universe with the existing ST exclusion. A historical Stock Connect eligibility filter is still required before live deployment through Futu.
- Signal horizon: 10 trading days.
- Label: return from the next trading day's open to the horizon close, so the target starts at an executable T+1 price.
- Model: LightGBM regression on the future return after demeaning targets within each trade date.
- Score: cross-sectional percentile rank from 0 to 1. The raw regression output is saved as `raw_score`.
- Portfolio: 20 stocks, evaluated every 5 trading days.
- Turnover control: replace at most 4 held symbols per rebalance and do not resize retained holdings.
- Research capital: RMB 1,000,000 for realistic lot-size and fixed-fee backtesting. This does not change the live or paper-trading budget.
- Deployment status: `research`; activation for paper trading is blocked until validation is complete.

## Commands

Train and score only the new profile:

```bash
docker run --rm --entrypoint python \
  -v /opt/aistockcn:/app -w /app \
  aistockcn-data-prep:latest \
  train_profile_runner.py --profiles medium_10d_v2
```

Run its full realistic walk-forward backtest without changing the active profile:

```bash
docker run --rm --entrypoint python \
  -v /opt/aistockcn:/app -w /app \
  aistockcn-data-prep:latest \
  backtest_profile_runner.py --profile medium_10d_v2
```

The profile is available for paper-trading activation. Its first full-market walk-forward run (`20260803T212656Z__medium_10d_v2`) returned -22.08% with a -28.63% maximum drawdown, so it must remain paper-only until a revised version passes the deployment gate.

## Next data upgrades

The first implementation deliberately works with the existing price, volume, valuation, market-cap, and industry data. The next research stage should add point-in-time profitability, quality, growth, dividend, event, and historical Stock Connect eligibility data before considering real-money use.
