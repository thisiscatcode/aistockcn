from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from app.config import Settings, get_settings
from app.services.research import normalize_research_symbol
from app.services.research_documents import (
    ResearchDocumentError,
    _s3_client,
    _upload_document_to_s3,
    _write_connection,
)


CNINFO_STOCKS_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_ROOT = "https://static.cninfo.com.cn/"
CATEGORIES = {
    "annual_report": "category_ndbg_szsh",
    "semiannual_report": "category_bndbg_szsh",
    "quarterly_report": "category_sjdbg_szsh",
}


def _request(url: str, *, data: dict[str, str] | None = None, timeout: float = 35) -> bytes:
    body = urlencode(data).encode() if data else None
    request = Request(
        url,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 AiStockCN/1.0 research@aistockcn.com",
            "Accept": "application/json, text/javascript, */*; q=0.01" if data else "application/pdf,application/json,*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.cninfo.com.cn/",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise ResearchDocumentError("cn_disclosure_request_failed") from exc


@lru_cache(maxsize=1)
def _issuer_map() -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(_request(CNINFO_STOCKS_URL).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ResearchDocumentError("cn_issuer_map_invalid") from exc
    issuers: dict[str, dict[str, str]] = {}
    for item in payload.get("stockList") or []:
        code = str(item.get("code") or "").strip()
        org_id = str(item.get("orgId") or "").strip()
        if re.fullmatch(r"\d{6}", code) and org_id:
            issuers[code] = {"org_id": org_id, "name": str(item.get("zwjc") or "").strip()}
    return issuers


def _exchange(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    if symbol.startswith(("5", "6", "68")):
        return "SSE"
    return "SZSE"


def _query_scope(exchange: str) -> tuple[str, str]:
    if exchange == "SSE":
        return "sse", "sh"
    if exchange == "BSE":
        return "third", "bj"
    return "szse", "sz"


def _report_period(title: str) -> date | None:
    match = re.search(r"(20\d{2})年", title)
    if not match:
        return None
    year = int(match.group(1))
    if "半年度" in title or "中期" in title:
        return date(year, 6, 30)
    if "第一季度" in title:
        return date(year, 3, 31)
    if "第三季度" in title:
        return date(year, 9, 30)
    return date(year, 12, 31)


def discover_cn_disclosures(
    *,
    symbol: str,
    document_types: list[str] | None = None,
    years: int = 3,
    limit_per_type: int = 2,
) -> dict[str, Any]:
    normalized = normalize_research_symbol(symbol, "CN")
    issuer = _issuer_map().get(normalized)
    if not issuer:
        raise ResearchDocumentError("cn_issuer_not_found")
    exchange = _exchange(normalized)
    column, plate = _query_scope(exchange)
    today = datetime.now(UTC).date()
    start = today - timedelta(days=max(1, min(years, 10)) * 366)
    selected = document_types or ["annual_report", "semiannual_report", "quarterly_report"]
    filings: list[dict[str, Any]] = []
    for document_type in selected:
        category = CATEGORIES.get(document_type)
        if not category:
            raise ResearchDocumentError("unsupported_cn_document_type")
        payload = {
            "pageNum": "1", "pageSize": "30", "column": column, "tabName": "fulltext",
            "plate": plate, "stock": f"{normalized},{issuer['org_id']}", "searchkey": "", "secid": "",
            "category": category, "trade": "", "seDate": f"{start.isoformat()}~{today.isoformat()}",
            "sortName": "", "sortType": "", "isHLtitle": "true",
        }
        try:
            response = json.loads(_request(CNINFO_QUERY_URL, data=payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ResearchDocumentError("cn_disclosure_response_invalid") from exc
        accepted = 0
        for item in response.get("announcements") or []:
            title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or "")).strip()
            adjunct = str(item.get("adjunctUrl") or "").strip()
            if not title or not adjunct.lower().endswith(".pdf") or "摘要" in title:
                continue
            timestamp = int(item.get("announcementTime") or 0)
            published = datetime.fromtimestamp(timestamp / 1000, tz=UTC).date() if timestamp else None
            filings.append({
                "market": "CN", "symbol": normalized, "company_name": issuer["name"],
                "exchange": exchange, "source_provider": exchange if exchange in {"SSE", "BSE"} else "CNINFO",
                "source_platform": "CNINFO", "source_issuer_id": issuer["org_id"],
                "announcement_id": str(item.get("announcementId") or ""), "title": title,
                "document_type": document_type, "filing_date": published,
                "report_period": _report_period(title), "fiscal_year": _report_period(title).year if _report_period(title) else None,
                "source_url": CNINFO_PDF_ROOT + adjunct.lstrip("/"),
            })
            accepted += 1
            if accepted >= max(1, min(limit_per_type, 5)):
                break
    return {"market": "CN", "symbol": normalized, "exchange": exchange, "company_name": issuer["name"], "filings": filings}


def _save_filing(filing: dict[str, Any], settings: Settings) -> dict[str, Any]:
    announcement_id = str(filing["announcement_id"])
    with _write_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("select * from research_documents where market='CN' and announcement_id=%s", [announcement_id])
            existing = cur.fetchone()
            if existing:
                return {**dict(existing), "duplicate": True}
    content = _request(str(filing["source_url"]))
    if len(content) < 5 or content[:5] != b"%PDF-":
        raise ResearchDocumentError("cn_disclosure_invalid_pdf")
    digest = hashlib.sha256(content).hexdigest()
    document_id = str(uuid4())
    filename = f"{filing['symbol']}-{filing['document_type']}-{announcement_id}.pdf"
    settings.research_upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = settings.research_upload_dir / f"{document_id}.pdf"
    storage_path.write_bytes(content)
    object_key = f"research-documents/CN/{filing['symbol']}/{document_id}.pdf" if settings.research_s3_bucket else None
    metadata = {key: filing.get(key) for key in ("title", "company_name", "source_platform", "source_issuer_id")}
    try:
        with _write_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into research_issuers(id, market, symbol, exchange, source_issuer_id, name, name_zh, currency, language)
                    values (%s, 'CN', %s, %s, %s, %s, %s, 'CNY', 'zh')
                    on conflict (market, symbol) do update set exchange=excluded.exchange, source_issuer_id=excluded.source_issuer_id,
                      name=excluded.name, name_zh=excluded.name_zh, updated_at=now()
                    """,
                    [f"CN:{filing['symbol']}", filing["symbol"], filing["exchange"], filing["source_issuer_id"], filing["company_name"], filing["company_name"]],
                )
                cur.execute(
                    """
                    insert into research_documents(
                      id, market, issuer_id, symbol, filename, document_type, filing_date, fiscal_year,
                      report_period, source_url, source_provider, exchange, announcement_id, storage_path,
                      object_key, sha256, size_bytes, status, source_format, native_page_numbers,
                      language, currency, source_metadata
                    ) values (%s,'CN',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'uploaded','pdf',true,'zh','CNY',%s::jsonb)
                    returning *
                    """,
                    [document_id, f"CN:{filing['symbol']}", filing["symbol"], filename, filing["document_type"], filing["filing_date"], filing["fiscal_year"],
                     filing["report_period"], filing["source_url"], filing["source_provider"], filing["exchange"], announcement_id,
                     str(storage_path), object_key, digest, len(content), json.dumps(metadata, ensure_ascii=False)],
                )
                document = dict(cur.fetchone())
                if object_key:
                    _upload_document_to_s3(settings=settings, path=storage_path, object_key=object_key, content_type="application/pdf")
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


def sync_cn_disclosures(**kwargs: Any) -> dict[str, Any]:
    discovery = discover_cn_disclosures(**kwargs)
    settings = get_settings()
    documents: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for filing in discovery["filings"]:
        try:
            documents.append(_save_filing(filing, settings))
        except ResearchDocumentError as exc:
            errors.append({"announcement_id": str(filing["announcement_id"]), "code": str(exc)})
    return {
        **{key: discovery[key] for key in ("market", "symbol", "exchange", "company_name")},
        "discovered": len(discovery["filings"]), "queued": sum(not item.get("duplicate") for item in documents),
        "duplicates": sum(bool(item.get("duplicate")) for item in documents), "documents": documents, "errors": errors,
    }
