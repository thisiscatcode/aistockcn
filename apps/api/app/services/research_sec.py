from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.config import Settings, get_settings
from app.services.research import normalize_us_symbol
from app.services.research_documents import (
    ResearchDocumentError,
    _clean_document_type,
    _s3_client,
    _upload_document_to_s3,
    _write_connection,
)


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_document}"
SUPPORTED_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K")
FORM_DOCUMENT_TYPES = {
    "10-K": "annual_report",
    "20-F": "annual_report",
    "40-F": "annual_report",
    "10-Q": "quarterly_report",
    "8-K": "current_report",
    "6-K": "current_report",
}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "div", "dl", "dt",
    "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
    "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "ix:hidden", "ix:header"}
_SEC_REQUEST_LOCK = threading.Lock()
_SEC_LAST_REQUEST_AT = 0.0


class _FilingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_tag: str | None = None
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.skip_tag:
            if normalized == self.skip_tag:
                self.skip_depth += 1
            return
        attributes = {key.lower(): str(value or "").lower() for key, value in attrs}
        style = attributes.get("style", "")
        if (
            normalized in SKIP_TAGS
            or "display:none" in style.replace(" ", "")
            or attributes.get("aria-hidden") == "true"
        ):
            self.skip_tag = normalized
            self.skip_depth = 1
            return
        if normalized in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self.skip_tag:
            if normalized == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if normalized in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_tag:
            return
        if tag.lower() in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def extract_sec_filing_text(payload: bytes) -> str:
    parser = _FilingHTMLParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    lines = []
    for line in "".join(parser.parts).splitlines():
        normalized = " ".join(line.split())
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def _sec_request(url: str, *, settings: Settings | None = None) -> bytes:
    global _SEC_LAST_REQUEST_AT
    resolved = settings or get_settings()
    request = Request(
        url,
        headers={
            "User-Agent": resolved.research_sec_user_agent,
            "Accept-Encoding": "gzip",
            "Accept": "application/json,text/html,application/xhtml+xml",
        },
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with _SEC_REQUEST_LOCK:
                wait_seconds = (
                    resolved.research_sec_request_interval_seconds
                    - (time.monotonic() - _SEC_LAST_REQUEST_AT)
                )
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                _SEC_LAST_REQUEST_AT = time.monotonic()
            with urlopen(request, timeout=30) as response:
                payload = response.read(resolved.research_max_upload_bytes + 1)
                if len(payload) > resolved.research_max_upload_bytes:
                    raise ResearchDocumentError("sec_document_too_large")
                if str(response.headers.get("Content-Encoding") or "").lower() == "gzip":
                    payload = gzip.decompress(payload)
                return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(0.5 * (2 ** attempt))
    raise ResearchDocumentError("sec_request_failed") from last_error


@lru_cache(maxsize=1)
def _ticker_cik_map() -> dict[str, str]:
    payload = json.loads(_sec_request(SEC_TICKERS_URL).decode("utf-8"))
    result: dict[str, str] = {}
    for item in payload.values() if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        try:
            cik = f"{int(item.get('cik_str')):010d}"
        except (TypeError, ValueError):
            continue
        if ticker:
            result[ticker] = cik
    return result


def resolve_sec_cik(symbol: str) -> str:
    normalized_symbol = normalize_us_symbol(symbol)
    cik = _ticker_cik_map().get(normalized_symbol)
    if not cik:
        raise ResearchDocumentError("sec_cik_not_found")
    return cik


def _recent_filing_rows(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    columns = [
        "accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "act", "form",
        "fileNumber", "filmNumber", "items", "size", "isXBRL", "isInlineXBRL",
        "primaryDocument", "primaryDocDescription",
    ]
    length = max((len(recent.get(column) or []) for column in columns), default=0)
    rows: list[dict[str, Any]] = []
    for index in range(length):
        row = {
            column: (recent.get(column) or [])[index] if index < len(recent.get(column) or []) else None
            for column in columns
        }
        rows.append(row)
    return rows


def discover_sec_filings(
    *,
    symbol: str,
    forms: list[str] | None = None,
    limit_per_form: int = 1,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    cik = resolve_sec_cik(normalized_symbol)
    selected_forms = []
    for raw in forms or list(SUPPORTED_FORMS):
        form = str(raw).strip().upper()
        if form not in SUPPORTED_FORMS:
            raise ResearchDocumentError("unsupported_sec_form")
        if form not in selected_forms:
            selected_forms.append(form)
    safe_limit = max(1, min(int(limit_per_form), 5))
    submissions = json.loads(
        _sec_request(SEC_SUBMISSIONS_URL.format(cik=cik)).decode("utf-8")
    )
    counts = {form: 0 for form in selected_forms}
    filings: list[dict[str, Any]] = []
    cik_unpadded = str(int(cik))
    for row in _recent_filing_rows(submissions):
        form = str(row.get("form") or "").upper()
        if form not in counts or counts[form] >= safe_limit:
            continue
        accession_number = str(row.get("accessionNumber") or "").strip()
        primary_document = Path(str(row.get("primaryDocument") or "").strip()).name
        if not accession_number or not primary_document:
            continue
        accession_path = re.sub(r"[^0-9]", "", accession_number)
        source_url = SEC_ARCHIVES_URL.format(
            cik=cik_unpadded,
            accession=accession_path,
            primary_document=primary_document,
        )
        report_date = str(row.get("reportDate") or "")
        filings.append({
            "symbol": normalized_symbol,
            "company_name": submissions.get("name"),
            "cik": cik,
            "form": form,
            "accession_number": accession_number,
            "filing_date": row.get("filingDate"),
            "report_date": report_date or None,
            "fiscal_year": int(report_date[:4]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date) else None,
            "primary_document": primary_document,
            "primary_document_description": row.get("primaryDocDescription"),
            "source_url": source_url,
            "filing_index_url": source_url.rsplit("/", 1)[0] + f"/{accession_number}-index.html",
            "is_xbrl": bool(row.get("isXBRL")),
            "is_inline_xbrl": bool(row.get("isInlineXBRL")),
        })
        counts[form] += 1
        if all(count >= safe_limit for count in counts.values()):
            break
    return {
        "symbol": normalized_symbol,
        "cik": cik,
        "company_name": submissions.get("name"),
        "forms": selected_forms,
        "filings": filings,
    }


def _save_sec_filing(filing: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    accession_number = str(filing["accession_number"])
    with _write_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from research_documents where sec_accession_number = %s",
                [accession_number],
            )
            existing = cur.fetchone()
            if existing:
                return {**dict(existing), "duplicate": True}

    content = _sec_request(str(filing["source_url"]), settings=settings)
    if not extract_sec_filing_text(content):
        raise ResearchDocumentError("sec_filing_has_no_extractable_text")
    digest = hashlib.sha256(content).hexdigest()
    document_id = str(uuid4())
    filename = f"{filing['symbol']}-{filing['form']}-{filing['filing_date']}-{accession_number}.html"
    upload_dir = settings.research_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = upload_dir / f"{document_id}.html"
    storage_path.write_bytes(content)
    object_key = (
        f"research-documents/US/{filing['symbol']}/{document_id}.html"
        if settings.research_s3_bucket
        else None
    )
    source_metadata = {
        key: filing.get(key)
        for key in (
            "company_name", "form", "report_date", "primary_document_description",
            "filing_index_url", "is_xbrl", "is_inline_xbrl",
        )
    }
    try:
        with _write_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into research_documents (
                      id, symbol, filename, document_type, filing_date, fiscal_year,
                      source_url, storage_path, object_key, sha256, size_bytes, status, source_format,
                      native_page_numbers, sec_cik, sec_accession_number, sec_primary_document,
                      source_metadata, market, issuer_id, source_provider, exchange, language, currency,
                      report_period
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'uploaded',
                              'sec_html', false, %s, %s, %s, %s::jsonb,
                              'US', %s, 'SEC', %s, 'en', 'USD', %s)
                    returning *
                    """,
                    [
                        document_id, filing["symbol"], filename,
                        _clean_document_type(FORM_DOCUMENT_TYPES[str(filing["form"])]),
                        date.fromisoformat(str(filing["filing_date"])) if filing.get("filing_date") else None,
                        filing.get("fiscal_year"),
                        filing["source_url"], str(storage_path), object_key, digest, len(content), filing["cik"],
                        accession_number, filing["primary_document"], json.dumps(source_metadata),
                        f"US:{filing['symbol']}", None,
                        date.fromisoformat(str(filing["report_date"])) if filing.get("report_date") else None,
                    ],
                )
                if object_key:
                    _upload_document_to_s3(
                        settings=settings,
                        path=storage_path,
                        object_key=object_key,
                        content_type="text/html; charset=utf-8",
                    )
                document = dict(cur.fetchone())
            conn.commit()
        return {**document, "duplicate": False}
    except Exception:
        storage_path.unlink(missing_ok=True)
        if object_key and settings.research_s3_bucket:
            try:
                _s3_client(settings).delete_object(Bucket=settings.research_s3_bucket, Key=object_key)
            except Exception:
                pass
        raise


def sync_sec_filings(
    *,
    symbol: str,
    forms: list[str] | None = None,
    limit_per_form: int = 1,
) -> dict[str, Any]:
    settings = get_settings()
    discovery = discover_sec_filings(symbol=symbol, forms=forms, limit_per_form=limit_per_form)
    documents: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for filing in discovery["filings"]:
        try:
            documents.append(_save_sec_filing(filing, settings=settings))
        except ResearchDocumentError as exc:
            errors.append({"accession_number": str(filing["accession_number"]), "code": str(exc)})
    return {
        "symbol": discovery["symbol"],
        "cik": discovery["cik"],
        "company_name": discovery["company_name"],
        "discovered": len(discovery["filings"]),
        "queued": sum(1 for item in documents if not item.get("duplicate")),
        "duplicates": sum(1 for item in documents if item.get("duplicate")),
        "documents": documents,
        "errors": errors,
    }
