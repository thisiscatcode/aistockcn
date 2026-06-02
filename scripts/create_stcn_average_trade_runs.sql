create table if not exists stcn_average_trade_runs (
  id bigserial primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null check (status in ('success', 'no_update', 'failed')),
  source_latest_trade_date date,
  fetched_rows integer not null default 0,
  upserted_rows integer not null default 0,
  error text
);

create index if not exists ix_stcn_average_trade_runs_started_at
  on stcn_average_trade_runs (started_at desc);

create index if not exists ix_stcn_average_trade_runs_status_source_date
  on stcn_average_trade_runs (status, source_latest_trade_date);
