from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import get_settings
from app.services.batch import BatchControlError, _docker_client, _get_container_by_ref
from app.services.files import read_json, tail_file, write_json_atomic
from app.services.log_translation import translate_log_lines

FEI_STOCK_ATTRIBUTES_LOG_TAIL = 80
FEI_STOCK_ATTRIBUTES_IMAGE = "aistockcn-panel-api:latest"
FEI_STOCK_ATTRIBUTES_CONTAINER_PREFIX = "aistockcn-fei-stock-attributes-"
FEI_STOCK_ATTRIBUTES_PID_FILE = "fei_stock_attributes.pid"
FEI_STOCK_ATTRIBUTES_LOG_PREFIX = "fei_stock_attributes"
FEI_STOCK_ATTRIBUTES_STATUS_FILE = "fei_stock_attributes_status.json"
FEI_STOCK_ATTRIBUTES_CHECKPOINT_FILE = "fei_stock_attributes_checkpoint.json"
FEI_STOCK_ATTRIBUTES_NETWORK = os.getenv("PAPER_DB_NETWORK", "elearn_default")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pid_file() -> Path:
    return get_settings().run_dir / FEI_STOCK_ATTRIBUTES_PID_FILE


def _status_file() -> Path:
    return get_settings().run_dir / FEI_STOCK_ATTRIBUTES_STATUS_FILE


def _checkpoint_file() -> Path:
    return get_settings().run_dir / FEI_STOCK_ATTRIBUTES_CHECKPOINT_FILE


def _latest_matching_log_file(logs_dir: Path) -> Path | None:
    candidates = sorted(logs_dir.glob(f"{FEI_STOCK_ATTRIBUTES_LOG_PREFIX}_*.log"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _write_log_stub(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _container_command(container: Any) -> str:
    config = container.attrs.get("Config", {})
    parts: list[str] = []
    for value in [config.get("Entrypoint"), config.get("Cmd")]:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def _find_running_container() -> Any | None:
    pid_file = _pid_file()
    if pid_file.exists():
        container_ref = pid_file.read_text(encoding="utf-8").strip()
        if container_ref:
            container = _get_container_by_ref(container_ref)
            if container is not None and container.status == "running":
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
        if container.name.startswith(FEI_STOCK_ATTRIBUTES_CONTAINER_PREFIX):
            matched.append(container)
            continue
        if "import_stock_master_attributes.py" in _container_command(container):
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


def _status_label(status: str) -> str:
    return {
        "running": "Running",
        "success": "Success",
        "failed": "Failed",
        "blocked": "Blocked",
        "stopped": "Stopped",
        "idle": "Idle",
    }.get(status, "Unknown")


def _command(log_file: str) -> list[str]:
    return [
        "scripts/import_stock_master_attributes.py",
        "--sleep",
        "3",
        "--status-file",
        "run/fei_stock_attributes_status.json",
        "--checkpoint-file",
        "run/fei_stock_attributes_checkpoint.json",
        "--log-file",
        log_file,
    ]


def start_fei_stock_attributes() -> dict[str, Any]:
    active = _find_running_container()
    if active is not None:
        raise BatchControlError(
            "already_running",
            f"Fei stock attributes job is already running in {active.name}.",
            status_code=409,
        )

    settings = get_settings()
    if not settings.paper_db_url and not os.getenv("APP_DB_URL"):
        raise BatchControlError("database_unavailable", "APP_DB_URL or PAPER_DB_URL is not configured.", status_code=503)

    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)
    try:
        client.images.get(FEI_STOCK_ATTRIBUTES_IMAGE)
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", f"Image {FEI_STOCK_ATTRIBUTES_IMAGE} is missing.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", "Unable to inspect Docker images.", status_code=503) from exc

    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp()
    container_name = f"{FEI_STOCK_ATTRIBUTES_CONTAINER_PREFIX}{timestamp}"
    log_file = settings.logs_dir / f"{FEI_STOCK_ATTRIBUTES_LOG_PREFIX}_{timestamp}.log"
    command = _command(f"logs/{log_file.name}")

    _write_log_stub(
        log_file,
        [
            "Fei stock attributes job started from admin panel.",
            f"ARGS: python {' '.join(command)}",
            "MODE: single worker, 3 seconds between 10jqka EPS requests",
            f"STARTED_AT: {_now_iso()}",
        ],
    )
    write_json_atomic(_status_file(), {
        "status": "running",
        "stage": "starting",
        "updated_at": _now_iso(),
        "started_at": _now_iso(),
        "total_codes": 0,
        "next_index": 0,
        "done_count": 0,
        "remaining_count": 0,
        "progress_pct": None,
        "share_updated_count": 0,
        "eps_updated_count": 0,
        "sina_industry_updated_count": 0,
        "keyword_updated_count": 0,
        "keyword_map_updated_count": 0,
        "keyword_failed_count": 0,
        "shareholder_research_updated_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "last_code": None,
        "last_error": None,
    }, ensure_ascii=False)

    environment = {
        "TZ": "UTC",
        "PROJECT_ROOT": "/workspace",
        "HOST_PROJECT_ROOT": str(settings.host_project_root),
        "PAPER_DB_URL": settings.paper_db_url or "",
    }
    app_db_url = os.getenv("APP_DB_URL")
    if app_db_url:
        environment["APP_DB_URL"] = app_db_url

    try:
        container = client.containers.run(
            FEI_STOCK_ATTRIBUTES_IMAGE,
            command=command,
            name=container_name,
            detach=True,
            auto_remove=True,
            entrypoint="python",
            working_dir="/workspace",
            environment=environment,
            network=FEI_STOCK_ATTRIBUTES_NETWORK,
            volumes={str(settings.host_project_root): {"bind": "/workspace", "mode": "rw"}},
        )
    except DockerException as exc:
        write_json_atomic(_status_file(), {
            "status": "failed",
            "stage": "start_failed",
            "updated_at": _now_iso(),
            "completed_at": _now_iso(),
            "last_error": str(exc),
        }, ensure_ascii=False)
        raise BatchControlError("start_failed", f"Failed to start Fei stock attributes job: {exc}", status_code=500) from exc

    _pid_file().write_text(f"{container.id}\n", encoding="utf-8")

    return {
        "ok": True,
        "action": "start",
        "target": "fei-stock-attributes",
        "code": "started",
        "message": f"Fei stock attributes job started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_fei_stock_attributes() -> dict[str, Any]:
    container = _find_running_container()
    if container is None:
        raise BatchControlError("not_running", "Fei stock attributes job is not currently running.", status_code=409)

    try:
        container.stop(timeout=30)
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop Fei stock attributes job: {exc}", status_code=500) from exc

    status = read_json(_status_file())
    status.update({
        "status": "stopped",
        "updated_at": _now_iso(),
        "completed_at": _now_iso(),
        "last_error": status.get("last_error") or "Stopped from admin panel",
    })
    write_json_atomic(_status_file(), status, ensure_ascii=False)

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir)
    if latest_log_file is not None:
        with latest_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"Stopped from admin panel at {_now_iso()}\n")

    return {
        "ok": True,
        "action": "stop",
        "target": "fei-stock-attributes",
        "code": "stopped",
        "message": "Fei stock attributes job has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
    }


def get_fei_stock_attributes_status() -> dict[str, Any]:
    settings = get_settings()
    container = _find_running_container()
    container_info = _snapshot_container(container)
    status_state = read_json(_status_file())
    checkpoint = read_json(_checkpoint_file())
    latest_log_file = _latest_matching_log_file(settings.logs_dir)

    log_lines: list[str] = []
    log_source = "none"
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=FEI_STOCK_ATTRIBUTES_LOG_TAIL)
        if log_lines:
            log_source = "docker"
    if latest_log_file is not None:
        file_lines = tail_file(latest_log_file, lines=FEI_STOCK_ATTRIBUTES_LOG_TAIL)
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
    next_index = int(status_state.get("next_index") or checkpoint.get("next_index") or 0)
    done_count = int(status_state.get("done_count") or min(next_index, total_codes))
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
        "status_file": str(_status_file()),
        "checkpoint_file": str(_checkpoint_file()),
        "updated_at": status_state.get("updated_at") or checkpoint.get("updated_at"),
        "started_at": status_state.get("started_at"),
        "completed_at": status_state.get("completed_at"),
        "stage": status_state.get("stage"),
        "last_code": status_state.get("last_code") or checkpoint.get("last_code"),
        "last_error": status_state.get("last_error"),
        "done_count": done_count,
        "remaining_count": int(status_state.get("remaining_count") or max(total_codes - done_count, 0)),
        "total_codes": total_codes,
        "progress_pct": progress_pct,
        "share_updated_count": int(status_state.get("share_updated_count") or 0),
        "eps_updated_count": int(status_state.get("eps_updated_count") or 0),
        "sina_industry_updated_count": int(status_state.get("sina_industry_updated_count") or 0),
        "keyword_updated_count": int(status_state.get("keyword_updated_count") or 0),
        "keyword_map_updated_count": int(status_state.get("keyword_map_updated_count") or 0),
        "keyword_failed_count": int(status_state.get("keyword_failed_count") or 0),
        "shareholder_research_updated_count": int(status_state.get("shareholder_research_updated_count") or 0),
        "failed_count": int(status_state.get("failed_count") or 0),
        "skipped_count": int(status_state.get("skipped_count") or 0),
        "log_file": str(latest_log_file) if latest_log_file else None,
        "log_source": log_source,
        "log_lines": translate_log_lines(log_lines),
    }
