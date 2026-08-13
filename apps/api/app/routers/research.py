from __future__ import annotations

import json
import time
from datetime import date
from typing import Iterator

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.research import (
    ResearchError,
    answer_research_question,
    compare_research_companies,
    get_company_snapshot,
    plan_research_tools,
    search_companies,
)
from app.services.research_documents import (
    ResearchDocumentError,
    get_research_document,
    get_research_document_file,
    index_research_document_safely,
    index_pdf_document_safely,
    list_research_documents,
    save_uploaded_pdf,
)
from app.services.research_evaluation import list_evaluation_runs, run_reranker_evaluation
from app.services.research_observability import record_agent_run
from app.services.research_retrieval import retrieve_document_evidence
from app.services.research_sec import discover_sec_filings, sync_sec_filings


router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchQuestionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    question: str = Field(min_length=1, max_length=800)


class ResearchRetrieveRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    question: str = Field(min_length=1, max_length=800)
    top_k: int = Field(default=6, ge=1, le=12)


class ResearchComparisonRequest(BaseModel):
    symbols: list[str] = Field(min_length=2, max_length=3)
    question: str = Field(min_length=1, max_length=800)


class ResearchSECFilingRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    forms: list[str] = Field(default_factory=lambda: ["10-K", "10-Q", "8-K"], min_length=1, max_length=3)
    limit_per_form: int = Field(default=1, ge=1, le=5)


@router.get("/documents")
def research_documents(symbol: str | None = Query(default=None, max_length=15)) -> dict[str, object]:
    try:
        return list_research_documents(symbol=symbol)
    except ResearchError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc


@router.post("/documents/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_research_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    symbol: str = Form(...),
    document_type: str = Form(default="annual_report"),
    filing_date: date | None = Form(default=None),
    fiscal_year: int | None = Form(default=None),
    source_url: str | None = Form(default=None),
) -> dict[str, object]:
    try:
        document = await save_uploaded_pdf(
            upload=file,
            symbol=symbol,
            document_type=document_type,
            filing_date=filing_date,
            fiscal_year=fiscal_year,
            source_url=source_url,
        )
        if (
            get_settings().research_inline_indexing
            and not document.get("duplicate")
            and document.get("status") == "uploaded"
        ):
            background_tasks.add_task(index_pdf_document_safely, str(document["id"]))
        return document
    except ResearchDocumentError as exc:
        code = str(exc)
        status_code = 413 if code == "file_too_large" else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.post("/documents/sec/discover")
def discover_research_sec_filings(request: ResearchSECFilingRequest) -> dict[str, object]:
    try:
        return discover_sec_filings(
            symbol=request.symbol,
            forms=request.forms,
            limit_per_form=request.limit_per_form,
        )
    except ResearchDocumentError as exc:
        code = str(exc)
        status_code = 404 if code == "sec_cik_not_found" else 502 if code == "sec_request_failed" else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.post("/documents/sec/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_research_sec_filings(
    request: ResearchSECFilingRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    try:
        result = sync_sec_filings(
            symbol=request.symbol,
            forms=request.forms,
            limit_per_form=request.limit_per_form,
        )
        if get_settings().research_inline_indexing:
            for document in result.get("documents", []):
                if not document.get("duplicate") and document.get("status") == "uploaded":
                    background_tasks.add_task(index_research_document_safely, str(document["id"]))
        return result
    except ResearchDocumentError as exc:
        code = str(exc)
        status_code = 404 if code == "sec_cik_not_found" else 502 if code == "sec_request_failed" else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.get("/documents/{document_id}")
def research_document(document_id: str) -> dict[str, object]:
    try:
        return get_research_document(document_id)
    except ResearchDocumentError as exc:
        code = str(exc)
        status_code = 404 if code == "document_not_found" else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.get("/documents/{document_id}/file")
def research_document_file(document_id: str) -> FileResponse:
    try:
        path, filename, media_type = get_research_document_file(document_id)
        safe_filename = filename.replace('"', "")
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
        )
    except ResearchDocumentError as exc:
        code = str(exc)
        status_code = 404 if code in {"document_not_found", "document_file_missing"} else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.post("/retrieve")
def research_retrieve(request: ResearchRetrieveRequest) -> dict[str, object]:
    try:
        return retrieve_document_evidence(
            symbol=request.symbol,
            question=request.question,
            top_k=request.top_k,
        )
    except ResearchDocumentError as exc:
        code = str(exc)
        raise HTTPException(status_code=400, detail={"code": code, "message": code}) from exc


@router.get("/evaluations")
def research_evaluations(limit: int = Query(default=10, ge=1, le=30)) -> dict[str, object]:
    return list_evaluation_runs(limit=limit)


@router.post("/evaluations/run")
def research_evaluation_run() -> dict[str, object]:
    return run_reranker_evaluation()


@router.get("/companies")
def research_companies(
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=12, ge=1, le=30),
) -> dict[str, object]:
    try:
        return search_companies(query=query, limit=limit)
    except ResearchError as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc), "message": str(exc)}) from exc


@router.get("/companies/{symbol}")
def research_company_snapshot(
    symbol: str,
    history_limit: int = Query(default=30, ge=5, le=260),
) -> dict[str, object]:
    try:
        return get_company_snapshot(symbol=symbol, history_limit=history_limit)
    except ResearchError as exc:
        status_code = 404 if str(exc) == "company_not_found" else 400
        raise HTTPException(status_code=status_code, detail={"code": str(exc), "message": str(exc)}) from exc


@router.post("/ask")
def research_question(request: ResearchQuestionRequest) -> dict[str, object]:
    try:
        result = answer_research_question(symbol=request.symbol, question=request.question)
        record_agent_run(
            run_type="question",
            symbols=[str(result["symbol"])],
            question=request.question,
            status="completed",
            duration_ms=float(result.get("duration_ms") or 0),
            evidence_count=len(result.get("document_evidence") or []) + len(result.get("data_evidence") or []),
            tool_plan=result.get("tool_plan"),
        )
        return result
    except ResearchError as exc:
        code = str(exc)
        if code == "company_not_found":
            status_code = 404
        elif code.startswith("research_model_"):
            status_code = 503
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc


@router.post("/ask/stream")
def research_question_stream(request: ResearchQuestionRequest) -> StreamingResponse:
    """Stream agent lifecycle events and the final source-grounded result as SSE."""
    def events() -> Iterator[str]:
        started_at = time.perf_counter()
        yield f"event: status\ndata: {json.dumps({'stage': 'planning', 'message': 'Selecting research tools'})}\n\n"
        try:
            plan = plan_research_tools(question=request.question)
            yield f"event: plan\ndata: {json.dumps(plan)}\n\n"
            yield f"event: status\ndata: {json.dumps({'stage': 'executing', 'message': 'Running validated tools'})}\n\n"
            result = answer_research_question(
                symbol=request.symbol,
                question=request.question,
                tool_plan=plan,
            )
            record_agent_run(
                run_type="question_stream",
                symbols=[str(result["symbol"])],
                question=request.question,
                status="completed",
                duration_ms=float(result.get("duration_ms") or 0),
                evidence_count=len(result.get("document_evidence") or []) + len(result.get("data_evidence") or []),
                tool_plan=plan,
            )
            for step in result.get("agent_steps", []):
                yield f"event: tool\ndata: {json.dumps(step, default=str)}\n\n"
            yield f"event: result\ndata: {json.dumps(result, default=str)}\n\n"
        except ResearchError as exc:
            record_agent_run(
                run_type="question_stream",
                symbols=[request.symbol.upper()],
                question=request.question,
                status="failed",
                duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                error_code=str(exc),
            )
            yield f"event: error\ndata: {json.dumps({'code': str(exc), 'message': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/compare")
def research_comparison(request: ResearchComparisonRequest) -> dict[str, object]:
    started_at = time.perf_counter()
    try:
        result = compare_research_companies(symbols=request.symbols, question=request.question)
        record_agent_run(
            run_type="comparison",
            symbols=list(result["symbols"]),
            question=request.question,
            status="completed",
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
            evidence_count=len(result.get("document_evidence") or []),
        )
        return result
    except ResearchError as exc:
        record_agent_run(
            run_type="comparison",
            symbols=[symbol.upper() for symbol in request.symbols],
            question=request.question,
            status="failed",
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
            error_code=str(exc),
        )
        code = str(exc)
        status_code = 404 if code == "company_not_found" else 400
        if code.startswith("research_model_"):
            status_code = 503
        raise HTTPException(status_code=status_code, detail={"code": code, "message": code}) from exc
