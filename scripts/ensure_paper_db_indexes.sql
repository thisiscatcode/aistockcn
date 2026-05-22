create index if not exists ix_agent_fills_owner_symbol_created_at
  on agent_fills (agent_id, market, symbol, created_at);

create index if not exists ix_agent_fills_owner_created_at
  on agent_fills (agent_id, market, created_at);

create index if not exists ix_agent_order_snapshots_owner_symbol_created_at
  on agent_order_snapshots (agent_id, market, symbol, created_at);

create index if not exists ix_agent_order_snapshots_owner_status_created_at
  on agent_order_snapshots (agent_id, market, order_status, created_at);

create index if not exists ix_trade_audit_logs_agent_created_at
  on trade_audit_logs (agent_id, created_at);
