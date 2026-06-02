from __future__ import annotations

from fastapi import APIRouter

from app.services.batch import get_batch_status
from app.services.fei_db_sync import get_fei_db_sync_status
from app.services.fei_stock_attributes_control import get_fei_stock_attributes_status
from app.services.pipeline_control import get_pipeline_run_status
from app.services.reference_control import get_reference_batch_status
from app.services.us_selection_control import get_us_selection_status
from app.services.workflow import get_workflow_status

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("/batch")
def batch_status() -> dict[str, object]:
    return get_batch_status()


@router.get("/workflow")
def workflow_status() -> dict[str, object]:
    return get_workflow_status()


@router.get("/pipeline")
def pipeline_status() -> dict[str, object]:
    return get_pipeline_run_status()


@router.get("/reference")
def reference_status() -> dict[str, object]:
    return get_reference_batch_status()


@router.get("/fei-stock-attributes")
def fei_stock_attributes_status() -> dict[str, object]:
    return get_fei_stock_attributes_status()


@router.get("/fei-db-sync")
def fei_db_sync_status() -> dict[str, object]:
    return get_fei_db_sync_status()


@router.get("/us-selection")
def us_selection_status() -> dict[str, object]:
    return get_us_selection_status()
