create table if not exists stock_daily_metrics (
  trade_date date not null,
  code text not null,
  exchange text not null,
  close numeric,
  volume numeric,
  amount numeric,
  average_trade numeric,
  turnover numeric,
  imported_at timestamptz not null default now(),
  primary key (trade_date, code, exchange)
);

alter table stock_daily_metrics
  add column if not exists volume numeric,
  add column if not exists amount numeric;
