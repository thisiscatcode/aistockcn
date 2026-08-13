create table if not exists model_versions (
  id text primary key,
  market text not null check (market in ('CN', 'US')),
  model_version text not null,
  profile text not null,
  artifact_path text not null,
  artifact_manifest jsonb not null default '{}'::jsonb,
  trained_at timestamptz not null,
  training_date date not null,
  training_data_start date,
  training_data_end date,
  prediction_as_of date,
  validation_status text not null check (
    validation_status in ('pending', 'passed', 'failed', 'legacy_unreviewed')
  ),
  validation_metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (market, model_version)
);

create index if not exists model_versions_market_profile_idx
  on model_versions(market, profile, trained_at desc);
create index if not exists model_versions_validation_idx
  on model_versions(market, validation_status, trained_at desc);

create table if not exists model_deployments (
  market text primary key check (market in ('CN', 'US')),
  active_model_id text not null references model_versions(id),
  paper_enabled boolean not null default false,
  activated_at timestamptz not null,
  activated_by text not null,
  revision bigint not null default 1,
  updated_at timestamptz not null default now()
);

create table if not exists model_activation_events (
  id text primary key,
  market text not null check (market in ('CN', 'US')),
  previous_model_id text references model_versions(id),
  new_model_id text not null references model_versions(id),
  paper_enabled boolean not null,
  actor text not null,
  reason text,
  revision bigint not null,
  created_at timestamptz not null default now()
);

create index if not exists model_activation_events_market_created_idx
  on model_activation_events(market, created_at desc);
