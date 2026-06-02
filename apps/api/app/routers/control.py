from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.admin_settings import update_admin_settings
from app.services.batch import BatchControlError, start_batch, stop_batch
from app.services.model import activate_model_for_paper
from app.services.paper import PaperGatewayError, cancel_paper_trading_order
from app.services.paper_control import start_paper_trading_daemon, stop_paper_trading_daemon
from app.services.fei_stock_attributes_control import start_fei_stock_attributes, stop_fei_stock_attributes
from app.services.pipeline_control import start_pipeline_run, start_step, stop_pipeline_run, stop_step
from app.services.reference_control import start_reference_batch, stop_reference_batch
from app.services.us_selection_control import set_us_selection_scheduler_enabled, start_us_selection, stop_us_selection

router = APIRouter(prefix="/api/control", tags=["control"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.post("/admin/settings")
def admin_settings_update(
    payload: dict[str, object],
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    return update_admin_settings(
        exclude_st_from_model_candidates=bool(payload.get("exclude_st_from_model_candidates", True)),
    )


@router.post("/batch/start")
def batch_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/batch/stop")
def batch_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/pipeline/start")
def pipeline_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_pipeline_run()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/pipeline/stop")
def pipeline_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_pipeline_run()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/step/{step_key}/start")
def step_start(
    step_key: str,
    profile: str | None = None,
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_step(step_key, profile_name=profile)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/step/{step_key}/stop")
def step_stop(step_key: str, x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_step(step_key)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/paper/start")
def paper_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_paper_trading_daemon()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/model/activate")
def model_activate(profile: str, x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        result = activate_model_for_paper(profile)
        return {"code": "model_activated", **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail={"code": "missing_model_artifacts", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_profile", "message": str(exc)}) from exc


@router.post("/paper/stop")
def paper_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_paper_trading_daemon()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/paper/orders/{order_id}/cancel")
def paper_order_cancel(order_id: str, x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return cancel_paper_trading_order(order_id)
    except PaperGatewayError as exc:
        raise HTTPException(status_code=502, detail={"code": "cancel_failed", "message": str(exc)}) from exc


@router.post("/reference/start")
def reference_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_reference_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/reference/stop")
def reference_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_reference_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/fei-stock-attributes/start")
def fei_stock_attributes_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_fei_stock_attributes()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/fei-stock-attributes/stop")
def fei_stock_attributes_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_fei_stock_attributes()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/us-selection/start")
def us_selection_start(
    mode: str = "full",
    target_date: str | None = None,
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    parsed_target_date = None
    if target_date:
        try:
            from datetime import datetime

            parsed_target_date = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_target_date", "message": "target_date must be YYYY-MM-DD"}) from exc
    try:
        return start_us_selection(mode=mode, target_date=parsed_target_date)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/us-selection/stop")
def us_selection_stop(
    mode: str | None = None,
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_us_selection(mode=mode)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/us-selection/scheduler/start")
def us_selection_scheduler_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    return set_us_selection_scheduler_enabled(True)


@router.post("/us-selection/scheduler/stop")
def us_selection_scheduler_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    return set_us_selection_scheduler_enabled(False)
