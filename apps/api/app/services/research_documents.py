from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import fitz
from fastapi import UploadFile

from app.config import Settings, get_settings
from app.services.research import ResearchError, normalize_us_symbol
from app.services.research_chunking import chunk_page_text
from app.services.research_models import embed_texts

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

try:
    import boto3
except Exception:  # pragma: no cover - optional outside the research image
    boto3 = None


RESEARCH_SCHEMA_SQL = """
create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists unaccent;

create table if not exists research_documents (
  id text primary key,
  symbol text not null references us_stock_master(symbol),
  filename text not null,
  document_type text not null default 'annual_report',
  filing_date date,
  fiscal_year integer,
  source_url text,
  storage_path text not null,
  object_key text,
  sha256 text not null,
  size_bytes bigint not null,
  page_count integer,
  chunk_count integer not null default 0,
  status text not null default 'uploaded',
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (symbol, sha256)
);

create index if not exists research_documents_symbol_idx
  on research_documents(symbol, filing_date desc nulls last, created_at desc);
create index if not exists research_documents_status_idx on research_documents(status);
alter table research_documents add column if not exists object_key text;
alter table research_documents add column if not exists source_format text not null default 'pdf';
alter table research_documents add column if not exists native_page_numbers boolean not null default true;
alter table research_documents add column if not exists sec_cik text;
alter table research_documents add column if not exists sec_accession_number text;
alter table research_documents add column if not exists sec_primary_document text;
alter table research_documents add column if not exists source_metadata jsonb not null default '{}'::jsonb;
create unique index if not exists research_documents_sec_accession_idx
  on research_documents(sec_accession_number) where sec_accession_number is not null;

create table if not exists research_document_pages (
  id text primary key,
  document_id text not null references research_documents(id) on delete cascade,
  page_number integer not null,
  content text not null,
  char_count integer not null,
  created_at timestamptz not null default now(),
  unique (document_id, page_number)
);

create table if not exists research_document_chunks (
  id text primary key,
  document_id text not null references research_documents(id) on delete cascade,
  page_number integer not null,
  chunk_index integer not null,
  content text not null,
  char_count integer not null,
  embedding vector(384),
  embedding_model text,
  search_vector tsvector generated always as (to_tsvector('english', content)) stored,
  created_at timestamptz not null default now(),
  unique (document_id, page_number, chunk_index)
);

create index if not exists research_chunks_document_idx
  on research_document_chunks(document_id, page_number, chunk_index);
alter table research_document_chunks add column if not exists locator_type text not null default 'page';
alter table research_document_chunks add column if not exists locator text;
create index if not exists research_chunks_search_idx
  on research_document_chunks using gin(search_vector);
create index if not exists research_chunks_content_trgm_idx
  on research_document_chunks using gin(content gin_trgm_ops);
create index if not exists research_chunks_embedding_hnsw_idx
  on research_document_chunks using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create table if not exists research_evaluation_runs (
  id text primary key,
  benchmark_name text not null,
  model_name text not null,
  case_count integer not null,
  top1_accuracy double precision not null,
  mean_reciprocal_rank double precision not null,
  baseline_top1_accuracy double precision not null,
  details jsonb not null,
  duration_ms double precision not null,
  created_at timestamptz not null default now()
);

create index if not exists research_evaluation_runs_created_idx
  on research_evaluation_runs(created_at desc);

create table if not exists research_agent_runs (
  id text primary key,
  run_type text not null,
  symbols text[] not null,
  question_sha256 text not null,
  status text not null,
  duration_ms double precision,
  evidence_count integer not null default 0,
  tool_plan jsonb,
  error_code text,
  created_at timestamptz not null default now()
);

create index if not exists research_agent_runs_created_idx
  on research_agent_runs(created_at desc);
"""


class ResearchDocumentError(ResearchError):
    pass


def _s3_client(settings: Settings) -> Any:
    if boto3 is None:
        raise ResearchDocumentError("s3_client_unavailable")
    return boto3.client("s3", region_name=settings.research_aws_region)


def _upload_document_to_s3(
    *, settings: Settings, path: Path, object_key: str, content_type: str
) -> None:
    if not settings.research_s3_bucket:
        return
    _s3_client(settings).upload_file(
        str(path),
        settings.research_s3_bucket,
        object_key,
        ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"},
    )


def _ensure_local_document(*, settings: Settings, document: dict[str, Any]) -> Path:
    path = Path(document["storage_path"])
    if path.exists():
        return path
    object_key = document.get("object_key")
    if not settings.research_s3_bucket or not object_key:
        raise ResearchDocumentError("document_file_missing")
    path.parent.mkdir(parents=True, exist_ok=True)
    _s3_client(settings).download_file(settings.research_s3_bucket, str(object_key), str(path))
    return path


@contextmanager
def _write_connection(settings: Settings | None = None) -> Iterator[Any]:
    resolved = settings or get_settings()
    if not resolved.paper_db_url:
        raise ResearchDocumentError("database_not_configured")
    if psycopg is None or dict_row is None:
        raise ResearchDocumentError("database_driver_unavailable")
    with psycopg.connect(
        resolved.paper_db_url,
        row_factory=dict_row,
        connect_timeout=8,
    ) as conn:
        yield conn


def init_research_document_schema() -> None:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(RESEARCH_SCHEMA_SQL)
        conn.commit()


def _clean_document_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "_", value.strip().lower()).strip("_")
    return normalized[:64] or "annual_report"


async def save_uploaded_pdf(
    *,
    upload: UploadFile,
    symbol: str,
    document_type: str,
    filing_date: date | None,
    fiscal_year: int | None,
    source_url: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = normalize_us_symbol(symbol)
    filename = Path(upload.filename or "document.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise ResearchDocumentError("pdf_required")

    document_id = str(uuid4())
    upload_dir = settings.research_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = upload_dir / f"{document_id}.pdf"
    digest = hashlib.sha256()
    size = 0
    first_bytes = b""
    try:
        with storage_path.open("wb") as destination:
            while content := await upload.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = content[:5]
                size += len(content)
                if size > settings.research_max_upload_bytes:
                    raise ResearchDocumentError("file_too_large")
                digest.update(content)
                destination.write(content)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if size == 0 or first_bytes != b"%PDF-":
        storage_path.unlink(missing_ok=True)
        raise ResearchDocumentError("invalid_pdf")

    sha256 = digest.hexdigest()
    object_key = f"research-documents/{normalized_symbol}/{document_id}.pdf" if settings.research_s3_bucket else None
    with _write_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from research_documents where symbol = %s and sha256 = %s",
                [normalized_symbol, sha256],
            )
            existing = cur.fetchone()
            if existing:
                storage_path.unlink(missing_ok=True)
                return {**dict(existing), "duplicate": True}
            try:
                if object_key:
                    _upload_document_to_s3(
                        settings=settings,
                        path=storage_path,
                        object_key=object_key,
                        content_type="application/pdf",
                    )
                cur.execute(
                    """
                    insert into research_documents (
                      id, symbol, filename, document_type, filing_date, fiscal_year,
                      source_url, storage_path, object_key, sha256, size_bytes, status,
                      source_format, native_page_numbers
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', 'pdf', true)
                    returning *
                    """,
                    [
                        document_id,
                        normalized_symbol,
                        filename,
                        _clean_document_type(document_type),
                        filing_date,
                        fiscal_year,
                        (source_url or "").strip() or None,
                        str(storage_path),
                        object_key,
                        sha256,
                        size,
                    ],
                )
                row = dict(cur.fetchone())
                conn.commit()
                return {**row, "duplicate": False}
            except Exception:
                conn.rollback()
                storage_path.unlink(missing_ok=True)
                if object_key and settings.research_s3_bucket:
                    try:
                        _s3_client(settings).delete_object(Bucket=settings.research_s3_bucket, Key=object_key)
                    except Exception:
                        pass
                raise


def index_research_document(document_id: str) -> dict[str, Any]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from research_documents where id = %s", [document_id])
            document = cur.fetchone()
            if not document:
                raise ResearchDocumentError("document_not_found")
            cur.execute(
                "update research_documents set status = 'processing', error_message = null, updated_at = now() where id = %s",
                [document_id],
            )
            conn.commit()

    try:
        settings = get_settings()
        source_path = _ensure_local_document(settings=settings, document=dict(document))
        source_format = str(document.get("source_format") or "pdf")
        pages: list[tuple[Any, ...]] = []
        chunks: list[tuple[Any, ...]] = []
        if source_format == "pdf":
            with fitz.open(source_path) as pdf:
                for page_index, page in enumerate(pdf, start=1):
                    text = page.get_text("text").strip()
                    pages.append((str(uuid4()), document_id, page_index, text, len(text)))
                    for chunk_index, content in enumerate(chunk_page_text(text)):
                        chunks.append(
                            (
                                str(uuid4()), document_id, page_index, chunk_index, content, len(content),
                                "page", f"page {page_index}",
                            )
                        )
        elif source_format == "sec_html":
            from app.services.research_sec import extract_sec_filing_text

            text = extract_sec_filing_text(source_path.read_bytes())
            for chunk_index, content in enumerate(chunk_page_text(text)):
                chunks.append(
                    (
                        str(uuid4()), document_id, 0, chunk_index, content, len(content),
                        "html_passage", f"SEC filing HTML · passage {chunk_index + 1}",
                    )
                )
        else:
            raise ResearchDocumentError("unsupported_document_format")

        if not chunks:
            raise ResearchDocumentError("document_has_no_extractable_text")

        embeddings = embed_texts([str(chunk[4]) for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise ResearchDocumentError("embedding_count_mismatch")
        embedded_chunks = [
            (
                *chunk,
                "[" + ",".join(f"{value:.8f}" for value in embedding) + "]",
                settings.research_embedding_model,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from research_document_pages where document_id = %s", [document_id])
                cur.executemany(
                    """
                    insert into research_document_pages (id, document_id, page_number, content, char_count)
                    values (%s, %s, %s, %s, %s)
                    """,
                    pages,
                )
                cur.executemany(
                    """
                    insert into research_document_chunks (
                      id, document_id, page_number, chunk_index, content, char_count,
                      locator_type, locator, embedding, embedding_model
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                    """,
                    embedded_chunks,
                )
                cur.execute(
                    """
                    update research_documents
                    set status = 'indexed', page_count = %s, chunk_count = %s,
                        error_message = null, updated_at = now()
                    where id = %s
                    returning *
                    """,
                    [len(pages) if source_format == "pdf" else None, len(chunks), document_id],
                )
                result = dict(cur.fetchone())
            conn.commit()
        return result
    except Exception as exc:
        with _write_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update research_documents
                    set status = 'failed', error_message = %s, updated_at = now()
                    where id = %s
                    """,
                    [str(exc)[:1000], document_id],
                )
            conn.commit()
        raise


def index_research_document_safely(document_id: str) -> None:
    try:
        index_research_document(document_id)
    except Exception:
        return


def index_pdf_document(document_id: str) -> dict[str, Any]:
    """Backward-compatible entry point for existing callers."""
    return index_research_document(document_id)


def index_pdf_document_safely(document_id: str) -> None:
    index_research_document_safely(document_id)


def claim_next_uploaded_document() -> str | None:
    """Atomically claim one queued source document so workers cannot process it twice."""
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id
                from research_documents
                where status = 'uploaded'
                   or (status = 'processing' and updated_at < now() - interval '1 hour')
                order by created_at
                for update skip locked
                limit 1
                """
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            document_id = str(row["id"])
            cur.execute(
                """
                update research_documents
                set status = 'processing', error_message = null, updated_at = now()
                where id = %s
                """,
                [document_id],
            )
        conn.commit()
    return document_id


def list_research_documents(*, symbol: str | None = None) -> dict[str, Any]:
    params: list[Any] = []
    where = ""
    if symbol:
        where = "where symbol = %s"
        params.append(normalize_us_symbol(symbol))
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select id, symbol, filename, document_type, filing_date, fiscal_year,
                       source_url, sha256, size_bytes, page_count, chunk_count, status,
                       error_message, source_format, native_page_numbers, sec_cik,
                       sec_accession_number, sec_primary_document, source_metadata,
                       created_at, updated_at
                from research_documents
                {where}
                order by filing_date desc nulls last, created_at desc
                limit 100
                """,
                params,
            )
            rows = [dict(row) for row in cur.fetchall()]
    return {"rows": len(rows), "documents": rows}


def get_research_document(document_id: str) -> dict[str, Any]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, symbol, filename, document_type, filing_date, fiscal_year,
                       source_url, sha256, size_bytes, page_count, chunk_count, status,
                       error_message, source_format, native_page_numbers, sec_cik,
                       sec_accession_number, sec_primary_document, source_metadata,
                       created_at, updated_at
                from research_documents where id = %s
                """,
                [document_id],
            )
            row = cur.fetchone()
    if not row:
        raise ResearchDocumentError("document_not_found")
    return dict(row)


def get_research_document_file(document_id: str) -> tuple[Path, str, str]:
    with _write_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from research_documents where id = %s", [document_id])
            row = cur.fetchone()
    if not row:
        raise ResearchDocumentError("document_not_found")
    document = dict(row)
    path = _ensure_local_document(settings=get_settings(), document=document)
    media_type = "application/pdf" if str(document.get("source_format") or "pdf") == "pdf" else "text/html"
    return path, str(document["filename"]), media_type
