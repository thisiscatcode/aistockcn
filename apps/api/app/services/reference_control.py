from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import get_settings
from app.services.batch import BatchControlError, _docker_client, _get_container_by_ref, get_batch_status
from app.services.files import read_json, run_command, tail_file
from app.services.log_translation import translate_log_lines

REFERENCE_LOG_TAIL = 60
REFERENCE_PID_FILE = "reference_data.pid"
REFERENCE_LOG_PREFIX = "reference_data"
REFERENCE_CONTAINER_PREFIX = "aistockcn-reference-data-"
DATA_PREP_IMAGE = "aistockcn-data-prep:latest"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pid_file() -> Path:
    return get_settings().run_dir / REFERENCE_PID_FILE


def _latest_matching_log_file(logs_dir: Path, pattern: str) -> Path | None:
    candidates = sorted(logs_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _append_control_log_line(path: Path | None, line: str) -> None:
    if path is None:
        return
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


def _container_command(container: Any) -> str:
    config = container.attrs.get("Config", {})
    parts: list[str] = []
    for value in [config.get("Entrypoint"), config.get("Cmd")]:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def _find_latest_matching_container() -> Any | None:
    pid_file = _pid_file()
    if pid_file.exists():
        container_ref = pid_file.read_text(encoding="utf-8").strip()
        if container_ref:
            container = _get_container_by_ref(container_ref)
            if container is not None:
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
        if container.name.startswith(REFERENCE_CONTAINER_PREFIX):
            matched.append(container)
            continue
        if "refresh_reference_data.py" in _container_command(container):
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
    if client is not None:
        try:
            container = client.containers.get(container_name)
            log_bytes = container.logs(tail=lines)
            return log_bytes.decode("utf-8", errors="replace").splitlines()
        except (DockerException, NotFound):
            pass

    ok, output = run_command(["docker", "logs", "--tail", str(lines), container_name], timeout=10)
    return output.splitlines() if ok and output else []


def _write_log_stub(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_reference_can_start() -> None:
    batch_status = get_batch_status()
    if batch_status.get("is_running"):
        raise BatchControlError(
            "batch_running",
            "Step 1 data prepare is running. Stop or wait for it before refreshing reference data.",
            status_code=409,
        )
    from app.services.pipeline_control import get_pipeline_run_status

    pipeline_status = get_pipeline_run_status()
    if pipeline_status.get("is_running"):
        raise BatchControlError(
            "pipeline_running",
            "Daily pipeline is running. Stop or wait for it before refreshing reference data.",
            status_code=409,
        )


def _reference_command() -> list[str]:
    return [
        "refresh_reference_data.py",
        "--sleep",
        "0.2",
    ]


def start_reference_batch() -> dict[str, Any]:
    active = _find_latest_matching_container()
    if active is not None and active.status == "running":
        raise BatchControlError("already_running", f"Reference batch is already running in {active.name}.", status_code=409)
    _assert_reference_can_start()

    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)
    try:
        client.images.get(DATA_PREP_IMAGE)
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", f"Image {DATA_PREP_IMAGE} is missing.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", "Unable to inspect Docker images.", status_code=503) from exc

    settings = get_settings()
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp()
    container_name = f"{REFERENCE_CONTAINER_PREFIX}{timestamp}"
    log_file = settings.logs_dir / f"{REFERENCE_LOG_PREFIX}_{timestamp}.log"
    command = _reference_command()

    try:
        container = client.containers.run(
            DATA_PREP_IMAGE,
            command=command,
            name=container_name,
            detach=True,
            entrypoint="python",
            working_dir="/app",
            environment={"TZ": "UTC"},
            volumes={str(settings.host_project_root): {"bind": "/app", "mode": "rw"}},
        )
    except DockerException as exc:
        raise BatchControlError("start_failed", f"Failed to start reference batch: {exc}", status_code=500) from exc

    _pid_file().write_text(f"{container.id}\n", encoding="utf-8")
    _write_log_stub(
        log_file,
        [
            "Reference batch started from control panel.",
            f"CONTAINER: {container.name}",
            f"CONTAINER_ID: {container.id}",
            f"ARGS: python {' '.join(command)}",
            "LIVE_LOG_SOURCE: docker",
            f"STARTED_AT: {_now_iso()}",
        ],
    )

    return {
        "ok": True,
        "action": "start",
        "target": "reference",
        "code": "started",
        "message": f"Reference batch started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_reference_batch() -> dict[str, Any]:
    container = _find_latest_matching_container()
    if container is None:
        raise BatchControlError("not_found", "No reference batch container record was found.", status_code=404)
    if container.status != "running":
        raise BatchControlError("not_running", "Reference batch is not currently running.", status_code=409)

    try:
        container.stop(timeout=30)
        container.reload()
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop reference batch: {exc}", status_code=500) from exc

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir, f"{REFERENCE_LOG_PREFIX}_*.log")
    _append_control_log_line(latest_log_file, f"Stopped from control panel at {_now_iso()}\n")

    return {
        "ok": True,
        "action": "stop",
        "target": "reference",
        "code": "stopped",
        "message": f"Reference batch {container.name} has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
        "status": container.status,
    }


def get_reference_batch_status() -> dict[str, Any]:
    settings = get_settings()
    container = _find_latest_matching_container()
    container_info = _snapshot_container(container)
    state = read_json(settings.reference_batch_state_path)
    reference_status = read_json(settings.reference_status_path)
    latest_log_file = _latest_matching_log_file(settings.logs_dir, f"{REFERENCE_LOG_PREFIX}_*.log")

    log_lines: list[str] = []
    log_source = "none"
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=REFERENCE_LOG_TAIL)
        if log_lines:
            log_source = "docker"
    if not log_lines and latest_log_file is not None:
        log_lines = tail_file(latest_log_file, lines=REFERENCE_LOG_TAIL)
        log_source = "file" if log_lines else "none"

    total_codes = int(state.get("total_codes") or reference_status.get("active_stock_count") or 0)
    done_codes = state.get("done_codes") if isinstance(state.get("done_codes"), list) else []
    failed_codes = state.get("failed_codes") if isinstance(state.get("failed_codes"), dict) else {}
    done_count = len(done_codes)
    failed_count = len(failed_codes)
    progress_pct = round((done_count / total_codes) * 100, 2) if total_codes else None

    if container_info["is_running"]:
        status = "running"
    elif container_info["container_name"] and container_info["exit_code"] not in (None, 0):
        status = "failed"
    elif state.get("completed_at"):
        status = "completed"
    elif latest_log_file is not None:
        status = "stopped"
    else:
        status = "idle"

    top_failures = [
        {"reason": reason, "count": count}
        for reason, count in Counter(str(reason) for reason in failed_codes.values()).most_common(8)
    ]
    pipeline_running = False
    try:
        from app.services.pipeline_control import get_pipeline_run_status

        pipeline_running = bool(get_pipeline_run_status().get("is_running"))
    except Exception:
        pipeline_running = False

    return {
        "status": status,
        "status_label": {
            "running": "Running",
            "completed": "Completed",
            "failed": "Failed",
            "stopped": "Stopped",
            "idle": "Idle",
        }.get(status, "Unknown"),
        "is_running": container_info["is_running"],
        "can_start": not container_info["is_running"] and not get_batch_status().get("is_running") and not pipeline_running,
        "can_stop": container_info["is_running"],
        "container_id": container_info["container_id"],
        "container_name": container_info["container_name"],
        "container_status": container_info["container_status"],
        "container_started_at": container_info["started_at"],
        "container_finished_at": container_info["finished_at"],
        "container_exit_code": container_info["exit_code"],
        "oom_killed": container_info["oom_killed"],
        "state_file": str(settings.reference_batch_state_path),
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
        "last_code": state.get("last_code"),
        "last_error": state.get("last_error"),
        "done_count": done_count,
        "failed_count": failed_count,
        "total_codes": total_codes,
        "progress_pct": progress_pct,
        "failure_reasons_top": top_failures,
        "reference_status_file": str(settings.reference_status_path),
        "reference_status_updated_at": reference_status.get("generated_at"),
        "target_trade_date": reference_status.get("target_trade_date"),
        "valuation_reference_ready_count": int(reference_status.get("valuation_reference_ready_count") or 0),
        "valuation_reference_missing_count": int(reference_status.get("valuation_reference_missing_count") or 0),
        "valuation_reference_stale_count": int(reference_status.get("valuation_reference_stale_count") or 0),
        "industry_missing_count": int(reference_status.get("industry_missing_count") or 0),
        "log_file": str(latest_log_file) if latest_log_file else None,
        "log_source": log_source,
        "log_lines": translate_log_lines(log_lines),
    }


def get_reference_batch_logs(*, lines: int = 120) -> dict[str, Any]:
    container = _find_latest_matching_container()
    container_info = _snapshot_container(container)
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=lines)
        if log_lines:
            return {
                "source": "docker",
                "container_name": container_info["container_name"],
                "lines": translate_log_lines(log_lines),
            }

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir, f"{REFERENCE_LOG_PREFIX}_*.log")
    if latest_log_file is not None:
        return {
            "source": "file",
            "path": str(latest_log_file),
            "lines": translate_log_lines(tail_file(latest_log_file, lines=lines)),
        }
    return {"source": "none", "lines": []}
