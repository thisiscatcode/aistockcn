create table if not exists us_selection_daily_snapshots (
  trade_date date not null,
  list_type text not null,
  rank integer not null,
  code text not null,
  exchange text not null,
  score numeric,
  signal_date date,
  row_data jsonb not null,
  source_dates jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (trade_date, list_type, rank),
  unique (trade_date, list_type, code, exchange),
  check (list_type in ('lobster', 'cat')),
  check (rank >= 1 and rank <= 50)
);

create index if not exists us_selection_daily_snapshots_date_idx
  on us_selection_daily_snapshots (trade_date desc);

create index if not exists us_selection_daily_snapshots_stock_idx
  on us_selection_daily_snapshots (code, exchange, trade_date desc);
