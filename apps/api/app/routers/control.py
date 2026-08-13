from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.admin_settings import update_admin_settings
from app.services.batch import BatchControlError, start_batch, stop_batch
from app.services.model import activate_model_for_paper
from app.serializers import to_jsonable
from app.services.model_registry import ModelRegistryError, rollback_model, update_validation_status
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
def model_activate(
    profile: str,
    reason: str = "Activated from the control panel.",
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        result = activate_model_for_paper(profile, reason=reason)
        return to_jsonable({"code": "model_activated", **result})
    except (ValueError, ModelRegistryError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_profile", "message": str(exc)}) from exc


@router.post("/model/validation")
def model_validation(
    payload: dict[str, object],
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        result = update_validation_status(
            market=str(payload.get("market") or "CN"),
            model_version=str(payload.get("model_version") or ""),
            validation_status=str(payload.get("validation_status") or ""),
            metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None,
        )
        return to_jsonable({"code": "model_validation_updated", "model": result})
    except ModelRegistryError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_model_validation", "message": str(exc)}) from exc


@router.post("/model/rollback")
def model_rollback(
    market: str = "CN",
    reason: str = "Rolled back from the control panel.",
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        deployment = rollback_model(market=market, actor="panel_admin", reason=reason)
        return to_jsonable({"code": "model_rolled_back", "deployment": deployment})
    except ModelRegistryError as exc:
        raise HTTPException(status_code=409, detail={"code": "rollback_unavailable", "message": str(exc)}) from exc


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
