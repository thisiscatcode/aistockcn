create table if not exists us_stock_master (
  symbol text primary key,
  market text,
  stock_type text,
  stock_name text,
  stock_name_zh text,
  stock_industry text,
  stock_industry_en text,
  stock_industry_short text,
  market_cap numeric,
  market_cap_source text,
  market_cap_as_of date,
  market_cap_is_estimated boolean,
  market_cap_validation_status text,
  market_cap_attempted_at timestamptz,
  circulating_shares_yi numeric,
  earnings_per_share numeric,
  pe_ratio numeric,
  ipo_date date,
  currency text,
  is_active boolean not null default true,
  del_flg boolean not null default false,
  fav_flg boolean not null default false,
  display_num integer,
  daily_updated_at timestamptz,
  details_updated_at timestamptz,
  universe_updated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table us_stock_master
  add column if not exists stock_type text,
  add column if not exists stock_name_zh text,
  add column if not exists stock_industry_en text,
  add column if not exists stock_industry_short text,
  add column if not exists market_cap numeric,
  add column if not exists market_cap_source text,
  add column if not exists market_cap_as_of date,
  add column if not exists market_cap_is_estimated boolean,
  add column if not exists market_cap_validation_status text,
  add column if not exists market_cap_attempted_at timestamptz,
  add column if not exists circulating_shares_yi numeric,
  add column if not exists earnings_per_share numeric,
  add column if not exists pe_ratio numeric,
  add column if not exists ipo_date date,
  add column if not exists currency text,
  add column if not exists is_active boolean not null default true,
  add column if not exists del_flg boolean not null default false,
  add column if not exists fav_flg boolean not null default false,
  add column if not exists display_num integer,
  add column if not exists daily_updated_at timestamptz,
  add column if not exists details_updated_at timestamptz,
  add column if not exists universe_updated_at timestamptz,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

create index if not exists us_stock_master_active_market_idx
  on us_stock_master (is_active, market, symbol);

create index if not exists us_stock_master_details_updated_idx
  on us_stock_master (details_updated_at asc nulls first, symbol asc);

create index if not exists us_stock_master_market_cap_backfill_idx
  on us_stock_master (fav_flg desc, details_updated_at asc nulls first, symbol)
  where is_active = true and del_flg = false and (market_cap is null or market_cap <= 0);

create index if not exists us_stock_master_market_cap_attempt_idx
  on us_stock_master (market_cap_attempted_at asc nulls first, fav_flg desc, symbol)
  where is_active = true and del_flg = false and (market_cap is null or market_cap <= 0);

create table if not exists us_stock_daily_metrics (
  trade_date date not null,
  symbol text not null references us_stock_master(symbol) on delete cascade,
  close numeric,
  price_diff numeric,
  volume numeric,
  turnover numeric,
  average_trade numeric,
  transaction_count numeric,
  massive_updated_at timestamptz,
  imported_at timestamptz not null default now(),
  primary key (trade_date, symbol)
);

alter table us_stock_daily_metrics
  add column if not exists price_diff numeric,
  add column if not exists volume numeric,
  add column if not exists turnover numeric,
  add column if not exists average_trade numeric,
  add column if not exists transaction_count numeric,
  add column if not exists massive_updated_at timestamptz,
  add column if not exists imported_at timestamptz not null default now();

create index if not exists us_stock_daily_metrics_symbol_date_idx
  on us_stock_daily_metrics (symbol, trade_date desc);

create table if not exists us_stock_daily_bars (
  trade_date date not null,
  symbol text not null references us_stock_master(symbol) on delete cascade,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric not null,
  vwap numeric,
  transaction_count numeric,
  provider text not null,
  adjustment_state text not null check (adjustment_state in ('adjusted', 'unadjusted')),
  provider_timestamp bigint,
  ingestion_run_id text not null,
  source_payload_sha256 text not null,
  imported_at timestamptz not null default now(),
  primary key (trade_date, symbol, provider, adjustment_state)
);

create index if not exists us_stock_daily_bars_symbol_date_idx
  on us_stock_daily_bars(symbol, trade_date desc);
create index if not exists us_stock_daily_bars_lineage_idx
  on us_stock_daily_bars(ingestion_run_id, imported_at);

create table if not exists us_market_ingestion_runs (
  id text primary key,
  provider text not null,
  adjustment_state text not null,
  date_from date not null,
  date_to date not null,
  status text not null check (status in ('running', 'completed', 'partial', 'failed')),
  requested_symbols integer not null default 0,
  completed_symbols integer not null default 0,
  failed_symbols integer not null default 0,
  row_count bigint not null default 0,
  checkpoint jsonb not null default '{}'::jsonb,
  last_error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists us_stock_keywords (
  id integer generated by default as identity primary key,
  key_code text not null default 'futu',
  key_name text not null,
  fav_flg boolean not null default false,
  display_num integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (key_name)
);

create index if not exists us_stock_keywords_fav_display_idx
  on us_stock_keywords (fav_flg desc, display_num asc, key_name asc);

create table if not exists us_stock_key_map (
  symbol text not null references us_stock_master(symbol) on delete cascade,
  key_code text not null default 'futu',
  key_name text not null,
  place_num integer not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, key_name)
);

create index if not exists us_stock_key_map_key_name_idx
  on us_stock_key_map (key_name);

create table if not exists us_stock_favorite_stocks (
  symbol text primary key references us_stock_master(symbol) on delete cascade,
  display_num integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists us_stock_favorite_stocks_display_idx
  on us_stock_favorite_stocks (display_num asc, symbol asc);

create table if not exists us_market_holidays (
  exchange text not null,
  at_date date not null,
  event_name text,
  trading_hour text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (exchange, at_date)
);

create table if not exists us_selection_job_runs (
  id bigint generated by default as identity primary key,
  lane text not null,
  target_date date,
  status text not null,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  total_count integer not null default 0,
  done_count integer not null default 0,
  failed_count integer not null default 0,
  skipped_count integer not null default 0,
  last_symbol text,
  last_error text,
  container_name text,
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists us_selection_job_runs_lane_target_idx
  on us_selection_job_runs (lane, target_date, started_at desc);

create unique index if not exists us_selection_job_runs_completed_once_idx
  on us_selection_job_runs (lane, target_date)
  where status = 'success' and target_date is not null;
