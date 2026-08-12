from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import Settings, get_settings
from app.serializers import records_to_json
from app.services.batch import BatchControlError, _docker_client, _get_container_by_ref
from app.services.files import read_json, tail_file, write_json_atomic
from app.services.log_translation import translate_log_lines

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency availability is environment-specific
    psycopg = None
    dict_row = None


US_SELECTION_IMAGE = "aistockcn-panel-api:latest"
US_SELECTION_CONTAINER_PREFIX = "aistockcn-us-selection-"
US_SELECTION_PID_FILE = "us_selection_update.pid"
US_SELECTION_STATUS_FILE = "us_selection_update_status.json"
US_SELECTION_CHECKPOINT_FILE = "us_selection_update_checkpoint.json"
US_SELECTION_LOG_PREFIX = "us_selection_update"
US_SELECTION_LOG_TAIL = 80
US_SELECTION_NETWORK = os.getenv("PAPER_DB_NETWORK", "elearn_default")
US_SELECTION_TIMEZONE = "America/New_York"

MODE_ARGS = {
    "price": ["--update-prices"],
    "average-trade": ["--update-average-trade"],
    "details": ["--update-details"],
    "universe": ["--refresh-universe"],
    "full": ["--full"],
}

LANE_LABELS = {
    "price": "Price Close",
    "average-trade": "Average Trade",
    "details": "Details / Concepts",
    "universe": "Universe / Holidays",
    "full": "Full Manual",
}

_LOCK = threading.Lock()
_STOP_EVENT: threading.Event | None = None
_THREAD: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _status_file(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).run_dir / US_SELECTION_STATUS_FILE


def _checkpoint_file(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).run_dir / US_SELECTION_CHECKPOINT_FILE


def _pid_file(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).run_dir / US_SELECTION_PID_FILE


def _latest_matching_log_file(logs_dir: Path) -> Path | None:
    candidates = sorted(logs_dir.glob(f"{US_SELECTION_LOG_PREFIX}_*.log"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _write_log_stub(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _status_label(status: str) -> str:
    return {
        "running": "Running",
        "success": "Success",
        "failed": "Failed",
        "blocked": "Blocked",
        "stopped": "Stopped",
        "idle": "Idle",
    }.get(status, "Unknown")


def _container_command(container: Any) -> str:
    config = container.attrs.get("Config", {})
    parts: list[str] = []
    for value in [config.get("Entrypoint"), config.get("Cmd")]:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def _find_running_container(mode: str | None = None) -> Any | None:
    pid_file = _pid_file()
    if pid_file.exists():
        container_ref = pid_file.read_text(encoding="utf-8").strip()
        if container_ref:
            container = _get_container_by_ref(container_ref)
            if container is not None and container.status == "running":
                if mode is None or f"--update-{mode}" in _container_command(container) or f"us-selection-{mode}" in container.name:
                    return container

    client = _docker_client()
    if client is None:
        return None
    try:
        containers = client.containers.list(all=True)
    except DockerException:
        return None

    matched: list[Any] = []
    for container in containers:
        if container.status != "running":
            continue
        if not container.name.startswith(US_SELECTION_CONTAINER_PREFIX):
            continue
        if mode is None or f"{US_SELECTION_CONTAINER_PREFIX}{mode}-" in container.name:
            matched.append(container)
    if not matched:
        return None
    return sorted(matched, key=lambda item: item.attrs.get("Created", ""))[-1]


def _snapshot_container(container: Any | None) -> dict[str, Any]:
    if container is None:
        return {
            "container_id": None,
            "container_name": None,
            "container_status": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "oom_killed": False,
            "is_running": False,
        }
    state = container.attrs.get("State", {})
    return {
        "container_id": container.id,
        "container_name": container.name,
        "container_status": container.status,
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": bool(state.get("OOMKilled")),
        "is_running": container.status == "running",
    }


def _tail_container_logs(container_name: str, *, lines: int) -> list[str]:
    client = _docker_client()
    if client is None:
        return []
    try:
        container = client.containers.get(container_name)
        log_bytes = container.logs(tail=lines)
        return log_bytes.decode("utf-8", errors="replace").splitlines()
    except (DockerException, NotFound):
        return []


def _connect(settings: Settings):
    if not settings.paper_db_url:
        raise BatchControlError("database_unavailable", "PAPER_DB_URL is not configured.", status_code=503)
    if psycopg is None or dict_row is None:
        raise BatchControlError("database_unavailable", "psycopg is not installed.", status_code=503)
    return psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5)


def _recent_lane_runs(settings: Settings) -> list[dict[str, Any]]:
    if not settings.paper_db_url or psycopg is None or dict_row is None:
        return []
    try:
        with psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5, options="-c default_transaction_read_only=on") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select distinct on (lane)
                      lane,
                      target_date,
                      status,
                      started_at,
                      completed_at,
                      total_count,
                      done_count,
                      failed_count,
                      skipped_count,
                      last_symbol,
                      last_error,
                      container_name
                    from us_selection_job_runs
                    order by lane, started_at desc
                    """
                )
                return records_to_json([dict(row) for row in cur.fetchall()])
    except Exception:
        return []


def _completed_run_exists(lane: str, target_date: date | None) -> bool:
    if target_date is None:
        return False
    settings = get_settings()
    if not settings.paper_db_url or psycopg is None or dict_row is None:
        return False
    try:
        with psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5, options="-c default_transaction_read_only=on") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1
                    from us_selection_job_runs
                    where lane = %s
                      and target_date = %s
                      and status = 'success'
                    limit 1
                    """,
                    [lane, target_date],
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _us_details_missing_count(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if not settings.paper_db_url or psycopg is None or dict_row is None:
        return 0
    try:
        with psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5, options="-c default_transaction_read_only=on") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select count(*) as missing_count
                    from us_stock_master
                    where is_active = true
                      and del_flg = false
                      and (
                        details_updated_at is null
                        or circulating_shares_yi is null
                        or circulating_shares_yi <= 0
                      )
                    """
                )
                row = cur.fetchone()
                return int(row["missing_count"] or 0) if row else 0
    except Exception:
        return 0


def _full_market_holiday(target_date: date) -> bool:
    settings = get_settings()
    if not settings.paper_db_url or psycopg is None or dict_row is None:
        return False
    try:
        with psycopg.connect(settings.paper_db_url, row_factory=dict_row, connect_timeout=5, options="-c default_transaction_read_only=on") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1
                    from us_market_holidays
                    where exchange = 'US'
                      and at_date = %s
                      and (trading_hour is null or trading_hour = '')
                    limit 1
                    """,
                    [target_date],
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _parse_time(value: str, default: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = (value or default).split(":", maxsplit=1)
        return min(max(int(hour_text), 0), 23), min(max(int(minute_text), 0), 59)
    except ValueError:
        hour_text, minute_text = default.split(":", maxsplit=1)
        return int(hour_text), int(minute_text)


def _ny_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(US_SELECTION_TIMEZONE))


def _mode_command(mode: str, target_date: date | None, log_file: Path) -> list[str]:
    if mode not in MODE_ARGS:
        raise BatchControlError("invalid_mode", f"Unsupported US selection mode: {mode}", status_code=400)
    command = [
        "scripts/update_us_selection_data.py",
        *MODE_ARGS[mode],
        "--status-file",
        f"run/{US_SELECTION_STATUS_FILE}",
        "--checkpoint-file",
        f"run/{US_SELECTION_CHECKPOINT_FILE}",
        "--log-file",
        f"logs/{log_file.name}",
        "--container-name",
        f"{US_SELECTION_CONTAINER_PREFIX}{mode}-{_timestamp()}",
        "--skip-completed",
    ]
    if target_date is not None:
        command.extend(["--target-date", target_date.isoformat()])
    return command


def start_us_selection(mode: str = "full", *, target_date: date | None = None, scheduled: bool = False) -> dict[str, Any]:
    if mode not in MODE_ARGS:
        raise BatchControlError("invalid_mode", f"Unsupported US selection mode: {mode}", status_code=400)
    active = _find_running_container(mode)
    if active is not None:
        raise BatchControlError("already_running", f"US selection {mode} is already running in {active.name}.", status_code=409)

    settings = get_settings()
    if not settings.paper_db_url and not os.getenv("APP_DB_URL"):
        raise BatchControlError("database_unavailable", "APP_DB_URL or PAPER_DB_URL is not configured.", status_code=503)

    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)
    try:
        client.images.get(US_SELECTION_IMAGE)
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", f"Image {US_SELECTION_IMAGE} is missing.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", "Unable to inspect Docker images.", status_code=503) from exc

    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp()
    container_name = f"{US_SELECTION_CONTAINER_PREFIX}{mode}-{timestamp}"
    log_file = settings.logs_dir / f"{US_SELECTION_LOG_PREFIX}_{mode}_{timestamp}.log"
    command = _mode_command(mode, target_date, log_file)
    command[command.index("--container-name") + 1] = container_name

    _write_log_stub(
        log_file,
        [
            f"US selection {mode} job started {'by scheduler' if scheduled else 'from admin panel'}.",
            f"ARGS: python {' '.join(command)}",
            f"TARGET_DATE: {target_date.isoformat() if target_date else '-'}",
            f"STARTED_AT: {_now_iso()}",
        ],
    )
    write_json_atomic(
        _status_file(settings),
        {
            "status": "running",
            "stage": "starting",
            "lane": mode,
            "target_date": target_date.isoformat() if target_date else None,
            "updated_at": _now_iso(),
            "started_at": _now_iso(),
            "total_codes": 0,
            "done_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "last_code": None,
            "last_error": None,
        },
        ensure_ascii=False,
    )

    environment = {
        "TZ": "UTC",
        "PROJECT_ROOT": "/workspace",
        "HOST_PROJECT_ROOT": str(settings.host_project_root),
        "PAPER_DB_URL": settings.paper_db_url or "",
        "FINNHUB_API_KEY": os.getenv("FINNHUB_API_KEY", ""),
        "MASSIVE_API_KEY": os.getenv("MASSIVE_API_KEY", ""),
    }
    for key, value in os.environ.items():
        if key.startswith("US_SELECTION_"):
            environment[key] = value
    app_db_url = os.getenv("APP_DB_URL")
    if app_db_url:
        environment["APP_DB_URL"] = app_db_url

    try:
        container = client.containers.run(
            US_SELECTION_IMAGE,
            command=command,
            name=container_name,
            detach=True,
            auto_remove=True,
            entrypoint="python",
            working_dir="/workspace",
            environment=environment,
            network=US_SELECTION_NETWORK,
            volumes={str(settings.host_project_root): {"bind": "/workspace", "mode": "rw"}},
        )
    except DockerException as exc:
        write_json_atomic(
            _status_file(settings),
            {"status": "failed", "stage": "start_failed", "updated_at": _now_iso(), "completed_at": _now_iso(), "last_error": str(exc)},
            ensure_ascii=False,
        )
        raise BatchControlError("start_failed", f"Failed to start US selection {mode} job: {exc}", status_code=500) from exc

    _pid_file(settings).write_text(f"{container.id}\n", encoding="utf-8")
    return {
        "ok": True,
        "action": "start",
        "target": "us-selection",
        "mode": mode,
        "code": "started",
        "message": f"US selection {mode} job started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_us_selection(mode: str | None = None) -> dict[str, Any]:
    container = _find_running_container(mode)
    if container is None:
        raise BatchControlError("not_running", "US selection job is not currently running.", status_code=409)
    try:
        container.stop(timeout=30)
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop US selection job: {exc}", status_code=500) from exc

    status = read_json(_status_file())
    status.update({"status": "stopped", "updated_at": _now_iso(), "completed_at": _now_iso(), "last_error": status.get("last_error") or "Stopped from admin panel"})
    write_json_atomic(_status_file(), status, ensure_ascii=False)
    latest_log_file = _latest_matching_log_file(get_settings().logs_dir)
    if latest_log_file is not None:
        with latest_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"Stopped from admin panel at {_now_iso()}\n")
    return {
        "ok": True,
        "action": "stop",
        "target": "us-selection",
        "mode": mode,
        "code": "stopped",
        "message": "US selection job has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
    }


def get_us_selection_status() -> dict[str, Any]:
    settings = get_settings()
    container = _find_running_container()
    container_info = _snapshot_container(container)
    status_state = read_json(_status_file(settings))
    checkpoint = read_json(_checkpoint_file(settings))
    latest_log_file = _latest_matching_log_file(settings.logs_dir)
    lane_runs = _recent_lane_runs(settings)

    log_lines: list[str] = []
    log_source = "none"
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=US_SELECTION_LOG_TAIL)
        if log_lines:
            log_source = "docker"
    if latest_log_file is not None:
        file_lines = tail_file(latest_log_file, lines=US_SELECTION_LOG_TAIL)
        if file_lines:
            log_lines = file_lines
            log_source = "file"

    raw_status = str(status_state.get("status") or "").strip().lower()
    if container_info["is_running"]:
        status = "running"
    elif raw_status == "running":
        status = "failed"
    elif raw_status:
        status = raw_status
    else:
        status = "idle"

    total_codes = int(status_state.get("total_codes") or checkpoint.get("total_codes") or 0)
    done_count = int(status_state.get("done_count") or checkpoint.get("done_count") or 0)
    progress_pct = status_state.get("progress_pct")
    if progress_pct is None and total_codes:
        progress_pct = round((done_count / total_codes) * 100, 2)

    return {
        "status": status,
        "status_label": _status_label(status),
        "is_running": container_info["is_running"],
        "can_start": not container_info["is_running"],
        "can_stop": container_info["is_running"],
        "container_id": container_info["container_id"],
        "container_name": container_info["container_name"],
        "container_status": container_info["container_status"],
        "container_started_at": container_info["started_at"],
        "container_finished_at": container_info["finished_at"],
        "container_exit_code": container_info["exit_code"],
        "oom_killed": container_info["oom_killed"],
        "status_file": str(_status_file(settings)),
        "checkpoint_file": str(_checkpoint_file(settings)),
        "updated_at": status_state.get("updated_at") or checkpoint.get("updated_at"),
        "started_at": status_state.get("started_at"),
        "completed_at": status_state.get("completed_at"),
        "stage": status_state.get("stage"),
        "lane": status_state.get("lane"),
        "target_date": status_state.get("target_date") or checkpoint.get("target_date"),
        "last_code": status_state.get("last_code") or checkpoint.get("last_symbol"),
        "last_error": status_state.get("last_error"),
        "done_count": done_count,
        "remaining_count": int(status_state.get("remaining_count") or max(total_codes - done_count, 0)),
        "total_codes": total_codes,
        "progress_pct": progress_pct,
        "failed_count": int(status_state.get("failed_count") or checkpoint.get("failed_count") or 0),
        "skipped_count": int(status_state.get("skipped_count") or checkpoint.get("skipped_count") or 0),
        "lane_runs": lane_runs,
        "log_file": str(latest_log_file) if latest_log_file else None,
        "log_source": log_source,
        "log_lines": translate_log_lines(log_lines),
        "scheduler": _scheduler_snapshot(),
    }


def _scheduler_state_path(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).run_dir / "us_selection_scheduler_state.json"


def _scheduler_snapshot() -> dict[str, Any]:
    state = read_json(_scheduler_state_path())
    return {
        "enabled": get_settings().us_selection_auto_run_enabled,
        "timezone": US_SELECTION_TIMEZONE,
        "state_file": str(_scheduler_state_path()),
        **state,
    }


def _write_scheduler_state(payload: dict[str, Any]) -> None:
    write_json_atomic(_scheduler_state_path(), payload, ensure_ascii=True)


def _set_env_file_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    next_lines: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{key}="):
            next_lines.append(f"{key}={value}")
            replaced = True
        else:
            next_lines.append(line)
    if not replaced:
        next_lines.append(f"{key}={value}")
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    tmp_path.replace(path)


def set_us_selection_scheduler_enabled(enabled: bool) -> dict[str, Any]:
    settings = get_settings()
    value = "1" if enabled else "0"
    _set_env_file_value(settings.run_dir / "panel.env", "US_SELECTION_AUTO_RUN_ENABLED", value)
    os.environ["US_SELECTION_AUTO_RUN_ENABLED"] = value
    get_settings.cache_clear()

    state = read_json(_scheduler_state_path())
    _write_scheduler_state(
        {
            **state,
            "enabled": enabled,
            "last_control_action": "enabled" if enabled else "disabled",
            "last_control_at": _now_iso(),
        }
    )

    if enabled:
        start_us_selection_scheduler()
    else:
        stop_us_selection_scheduler()

    return {
        "ok": True,
        "action": "start" if enabled else "stop",
        "target": "us-selection-scheduler",
        "code": "scheduler_enabled" if enabled else "scheduler_disabled",
        "enabled": enabled,
        "message": f"US selection scheduler {'enabled' if enabled else 'disabled'}.",
    }


def _due(local_now: datetime, time_value: str, default: str) -> bool:
    hour, minute = _parse_time(time_value, default)
    return (local_now.hour, local_now.minute) >= (hour, minute)


def _maybe_start_scheduled_lane(mode: str, target_date: date | None, state_key: str, state: dict[str, Any]) -> dict[str, Any]:
    if _find_running_container(mode) is not None:
        return {**state, "last_skip_reason": f"{mode}_already_running"}
    if target_date is not None and _completed_run_exists(mode, target_date):
        return {**state, "last_skip_reason": f"{mode}_already_completed", f"last_{state_key}": target_date.isoformat()}
    try:
        result = start_us_selection(mode, target_date=target_date, scheduled=True)
        return {
            **state,
            f"last_attempted_{state_key}": target_date.isoformat() if target_date else _ny_now().date().isoformat(),
            "last_triggered_at": _now_iso(),
            "last_triggered_mode": mode,
            "last_result": {"ok": True, "code": result.get("code"), "container_name": result.get("container_name")},
        }
    except BatchControlError as exc:
        return {
            **state,
            "last_error_at": _now_iso(),
            "last_error": exc.message,
            "last_result": {"ok": False, "code": exc.code, "message": exc.message},
        }


def _maybe_start_us_selection_jobs() -> None:
    settings = get_settings()
    local_now = _ny_now()
    local_date = local_now.date()
    state = {
        **read_json(_scheduler_state_path(settings)),
        "last_checked_at": _now_iso(),
        "last_checked_local_date": local_date.isoformat(),
        "timezone": US_SELECTION_TIMEZONE,
    }

    if local_now.weekday() < 5 and _due(local_now, settings.us_selection_price_time, "16:31"):
        if not _full_market_holiday(local_date) and state.get("last_price_date") != local_date.isoformat():
            state = _maybe_start_scheduled_lane("price", local_date, "price_date", state)

    if local_now.weekday() in {1, 2, 3, 4, 5} and _due(local_now, settings.us_selection_average_time, "00:30"):
        target = local_date - timedelta(days=1)
        if not _full_market_holiday(target) and state.get("last_average_date") != target.isoformat():
            state = _maybe_start_scheduled_lane("average-trade", target, "average_date", state)

    details_missing_count = _us_details_missing_count(settings)
    state["details_missing_count"] = details_missing_count
    if details_missing_count > 0:
        state = _maybe_start_scheduled_lane("details", None, "details_local_date", state)
    elif _due(local_now, settings.us_selection_details_time, "03:00") and state.get("last_details_local_date") != local_date.isoformat():
        state = _maybe_start_scheduled_lane("details", None, "details_local_date", state)

    if local_now.weekday() == 5 and _due(local_now, settings.us_selection_universe_time, "06:00") and state.get("last_universe_local_date") != local_date.isoformat():
        state = _maybe_start_scheduled_lane("universe", local_date, "universe_local_date", state)

    _write_scheduler_state(state)


def _run_scheduler_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            _maybe_start_us_selection_jobs()
        except Exception as exc:
            state = read_json(_scheduler_state_path())
            _write_scheduler_state({**state, "last_checked_at": _now_iso(), "last_error_at": _now_iso(), "last_error": str(exc)})
        stop_event.wait(get_settings().us_selection_auto_run_poll_seconds)


def start_us_selection_scheduler() -> None:
    settings = get_settings()
    if not settings.us_selection_auto_run_enabled:
        return
    global _STOP_EVENT, _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP_EVENT = threading.Event()
        _THREAD = threading.Thread(target=_run_scheduler_loop, args=(_STOP_EVENT,), name="us-selection-auto-run", daemon=True)
        _THREAD.start()


def stop_us_selection_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _LOCK:
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        if _THREAD is not None and _THREAD.is_alive():
            _THREAD.join(timeout=2)
        _STOP_EVENT = None
        _THREAD = None
