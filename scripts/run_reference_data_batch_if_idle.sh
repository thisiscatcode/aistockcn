#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$ROOT_DIR/run/reference_data_auto.lock"

mkdir -p "$ROOT_DIR/run" "$ROOT_DIR/logs"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) reference auto-run skipped: lock is held"
  exit 0
fi

if docker ps --format '{{.Names}}' | grep -Eq '^aistockcn-reference-data-'; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) reference auto-run skipped: reference batch already running"
  exit 0
fi

if docker ps --format '{{.Names}}' | grep -Eq '^aistockcn-(full-pipeline|full-market-3y|step[0-9]-)'; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) reference auto-run skipped: A-share pipeline is running"
  exit 0
fi

cd "$ROOT_DIR"
exec env START_DATE="${START_DATE:-20200101}" \
  END_DATE="${END_DATE:-$(date -u +%Y%m%d)}" \
  SLEEP_SECONDS="${SLEEP_SECONDS:-0.2}" \
  LIMIT="${LIMIT:-0}" \
  SKIP_INDUSTRY="${SKIP_INDUSTRY:-0}" \
  OVERWRITE="${OVERWRITE:-0}" \
  bash "$ROOT_DIR/run_reference_data_batch.sh"
