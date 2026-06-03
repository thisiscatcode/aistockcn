#!/usr/bin/env python3
"""Import latest stock attributes into stock_master.

The importer updates only the lightweight attributes used by the Fei selection
page: latest float shares from daily valuation parquet files and EPS from the
same 10jqka page used by the legacy project. It also syncs Sina industry and
concept keywords into stock_key_map.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

try:
    import psycopg
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None


EPS_PATTERN = re.compile(r"<dt>\s*每股收益：\s*</dt>\s*<dd>\s*([-+]?\d+(?:\.\d+)?)\s*元\s*</dd>")
INDUSTRY_PATTERN = re.compile(r"^([A-Z]\d{2})(.+)$")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
EASTMONEY_SHAREHOLDER_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
EASTMONEY_SHAREHOLDER_SOURCE = "eastmoney_f10_holdernum"

SHARE_UPDATE_SQL = """
update stock_master
set
  float_shares = coalesce(%s::numeric, float_shares),
  float_shares_yi = coalesce(%s::numeric, float_shares_yi),
  share_snapshot_date = coalesce(%s::date, share_snapshot_date),
  industry_code = coalesce(%s::text, industry_code),
  industry_name = coalesce(%s::text, industry_name),
  industry_short_name = coalesce(%s::text, industry_short_name),
  industry_classification = coalesce(%s::text, industry_classification),
  imported_at = now()
where code = %s
  and exchange = %s
"""

EPS_UPDATE_SQL = """
update stock_master
set
  earnings_per_share = %s::numeric,
  earnings_per_share_updated_at = now(),
  imported_at = now()
where code = %s
  and exchange = %s
"""

SINA_INDUSTRY_UPDATE_SQL = """
update stock_master
set
  "industry_name_SINA" = %s::text,
  imported_at = now()
where code = %s
  and exchange = %s
"""

KEYWORD_UPSERT_SQL = """
insert into stock_keywords (
  key_code,
  key_name,
  created_at,
  updated_at
)
values (
  'sina',
  %s,
  now(),
  now()
)
on conflict (key_name) do update
set
  key_code = excluded.key_code,
  updated_at = now()
"""

DELETE_STOCK_KEYWORD_MAP_SQL = "delete from stock_key_map where code = %s and exchange = %s"

KEYWORD_MAP_UPSERT_SQL = """
insert into stock_key_map (
  code,
  exchange,
  key_code,
  key_name,
  place_num,
  created_at,
  updated_at
)
values (
  %s,
  %s,
  'sina',
  %s,
  %s,
  now(),
  now()
)
on conflict (code, exchange, key_name) do update
set
  key_code = excluded.key_code,
  place_num = excluded.place_num,
  updated_at = now()
"""

SHAREHOLDER_RESEARCH_UPSERT_SQL = """
insert into stock_shareholder_research (
  report_date,
  code,
  exchange,
  secucode,
  holder_total_num,
  total_num_ratio,
  avg_free_shares,
  avg_freeshares_ratio,
  hold_focus,
  source,
  imported_at
) values (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
)
on conflict (report_date, code, exchange) do update set
  secucode = excluded.secucode,
  holder_total_num = excluded.holder_total_num,
  total_num_ratio = excluded.total_num_ratio,
  avg_free_shares = excluded.avg_free_shares,
  avg_freeshares_ratio = excluded.avg_freeshares_ratio,
  hold_focus = excluded.hold_focus,
  source = excluded.source,
  imported_at = now()
"""

DELETE_OLD_SHAREHOLDER_RESEARCH_SQL = "delete from stock_shareholder_research where report_date < %s"

STOP_REQUESTED = False


@dataclass(frozen=True)
class EpsFetchResult:
    eps: float | None
    blocked: bool = False
    error: str | None = None


@dataclass(frozen=True)
class SinaConceptResult:
    industry: list[str]
    concepts: list[str]
    blocked: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ShareholderResearchRow:
    report_date: date
    code: str
    exchange: str
    secucode: str
    holder_total_num: Any
    total_num_ratio: Any
    avg_free_shares: Any
    avg_freeshares_ratio: Any
    hold_focus: str | None


@dataclass(frozen=True)
class ShareholderResearchFetchResult:
    rows: list[ShareholderResearchRow]
    blocked: bool = False
    error: str | None = None


class Tee:
    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def handle_signal(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(f"Stop requested by signal {signum}; finishing current stock and checkpointing.", flush=True)


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def setup_log_file(path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = Tee(sys.stdout, handle)  # type: ignore[assignment]
    sys.stderr = Tee(sys.stderr, handle)  # type: ignore[assignment]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import stock_master float shares and EPS attributes.")
    parser.add_argument(
        "--valuation-dir",
        default="quant_data/daily_valuation",
        help="Directory containing per-stock daily valuation parquet files.",
    )
    parser.add_argument(
        "--stock-list",
        default="quant_data/stock_list.parquet",
        help="Path to stock_list.parquet for local industry metadata.",
    )
    parser.add_argument(
        "--schema-sql",
        default="scripts/create_stock_master.sql",
        help="Path to the SQL file that creates/updates stock_master.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL"),
        help="Postgres DSN. Defaults to APP_DB_URL, then PAPER_DB_URL.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit number of stocks to process. 0 means all.")
    parser.add_argument("--skip-eps", action="store_true", help="Only import latest float shares from parquet.")
    parser.add_argument("--sleep", type=float, default=3.0, help="Seconds to sleep between 10jqka EPS requests.")
    parser.add_argument(
        "--shareholder-start-date",
        default="2024-01-01",
        help="Import Eastmoney shareholder research rows from this report date onward.",
    )
    parser.add_argument("--eps-workers", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout for 10jqka EPS requests.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per 10jqka EPS request.")
    parser.add_argument("--block-error-threshold", type=int, default=3, help="Stop after this many consecutive 403/429 responses.")
    parser.add_argument("--status-file", default="run/fei_stock_attributes_status.json", help="Status JSON path.")
    parser.add_argument("--checkpoint-file", default="run/fei_stock_attributes_checkpoint.json", help="Checkpoint JSON path.")
    parser.add_argument("--log-file", default=None, help="Optional log file path to tee stdout/stderr into.")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Ignore existing checkpoint and start EPS from the first stock.")
    return parser.parse_args()


def to_db_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "item"):
        return value.item()
    return value


def parse_date_arg(value: str, *, name: str) -> date:
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{name} must be a valid date")
    return pd.Timestamp(parsed).date()


def infer_exchange(code: Any) -> str:
    normalized = str(code or "").zfill(6)
    return "sh" if normalized.startswith(("5", "6", "9")) else "sz"


def eastmoney_secucode(code: str, exchange: str) -> str:
    normalized_code = str(code or "").zfill(6)
    normalized_exchange = str(exchange or "").strip().lower() or infer_exchange(normalized_code)
    suffix = "SH" if normalized_exchange == "sh" else "SZ"
    return f"{normalized_code}.{suffix}"


def split_industry(value: Any) -> tuple[str | None, str | None]:
    if pd.isna(value):
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    match = INDUSTRY_PATTERN.match(text)
    if not match:
        return None, text
    return match.group(1), match.group(2).strip() or None


SHORT_INDUSTRY_OVERRIDES = {
    "货币金融服务": "银行",
    "资本市场服务": "证券",
    "保险业": "保险",
    "其他金融业": "其他金融",
    "房地产业": "房地产",
    "软件和信息技术服务业": "软件信息",
    "互联网和相关服务": "互联网",
    "电信、广播电视和卫星传输服务": "电信广电",
    "计算机、通信和其他电子设备制造业": "电子设备",
    "铁路、船舶、航空航天和其他运输设备制造业": "运输设备",
    "电力、热力生产和供应业": "电力热力",
    "燃气生产和供应业": "燃气",
    "水的生产和供应业": "水务",
    "土木工程建筑业": "土木工程",
    "建筑装饰、装修和其他建筑业": "建筑装饰",
    "文教、工美、体育和娱乐用品制造业": "文体用品",
    "石油、煤炭及其他燃料加工业": "燃料加工",
    "化学原料和化学制品制造业": "化学制品",
    "黑色金属冶炼和压延加工业": "黑色金属",
    "有色金属冶炼和压延加工业": "有色金属",
    "农副食品加工业": "农副食品",
    "酒、饮料和精制茶制造业": "饮料茶酒",
    "纺织服装、服饰业": "服装服饰",
    "皮革、毛皮、羽毛及其制品和制鞋业": "皮革制鞋",
    "木材加工和木、竹、藤、棕、草制品业": "木材加工",
    "橡胶和塑料制品业": "橡胶塑料",
    "非金属矿物制品业": "非金属",
    "废弃资源综合利用业": "资源利用",
    "金属制品、机械和设备修理业": "设备修理",
    "生态保护和环境治理业": "环境治理",
    "公共设施管理业": "公共设施",
    "装卸搬运和仓储业": "仓储物流",
    "广播、电视、电影和录音制作业": "影视制作",
    "研究和试验发展": "研发",
    "专业技术服务业": "技术服务",
    "科技推广和应用服务业": "科技推广",
    "商务服务业": "商务服务",
}


def short_industry_name(industry_name: str | None) -> str | None:
    if not industry_name:
        return None
    name = industry_name.strip()
    if not name:
        return None
    if name in SHORT_INDUSTRY_OVERRIDES:
        return SHORT_INDUSTRY_OVERRIDES[name]
    for suffix in ("制造业", "服务业", "加工业", "采矿业", "建筑业", "管理业", "运输业", "供应业", "生产业", "业"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    replacements = [
        ("和其他", ""),
        ("及其他", ""),
        ("生产和供应", ""),
        ("冶炼和压延", ""),
        ("、", ""),
        ("，", ""),
        (",", ""),
    ]
    for old, new in replacements:
        name = name.replace(old, new)
    if len(name) <= 4:
        return name
    return name[:5] if len(name) <= 5 else name[:4]


def load_industry_attrs(stock_list_path: Path) -> dict[tuple[str, str], tuple[Any, Any, Any, Any]]:
    if not stock_list_path.exists():
        print(f"{stock_list_path} does not exist; industry attributes will be skipped.", file=sys.stderr)
        return {}
    try:
        df = pd.read_parquet(stock_list_path, columns=["code", "exchange", "industry", "industry_classification"])
    except Exception:
        df = pd.read_parquet(stock_list_path)
    required = {"code", "exchange", "industry"}
    if not required.issubset(df.columns):
        return {}
    if "industry_classification" not in df.columns:
        df["industry_classification"] = None

    attrs: dict[tuple[str, str], tuple[Any, Any, Any, Any]] = {}
    for row in df[["code", "exchange", "industry", "industry_classification"]].to_dict(orient="records"):
        code = str(row.get("code") or "").zfill(6)
        exchange = str(row.get("exchange") or "").strip().lower() or infer_exchange(code)
        industry_code, industry_name = split_industry(row.get("industry"))
        attrs[(code, exchange)] = (
            industry_code,
            industry_name,
            short_industry_name(industry_name),
            to_db_value(row.get("industry_classification")),
        )
    return attrs


def latest_float_shares(path: Path) -> tuple[str, str, Any, Any, Any] | None:
    try:
        df = pd.read_parquet(path, columns=["date", "code", "exchange", "float_shares"])
    except Exception:
        try:
            df = pd.read_parquet(path)
        except Exception as exc:
            print(f"Skipping {path}: {exc}", file=sys.stderr)
            return None

    if "date" not in df.columns or "float_shares" not in df.columns:
        return None
    if "code" not in df.columns:
        df["code"] = path.stem
    if "exchange" not in df.columns:
        df["exchange"] = None

    df = df[["date", "code", "exchange", "float_shares"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["float_shares"] = pd.to_numeric(df["float_shares"], errors="coerce")
    df = df.dropna(subset=["date", "code", "float_shares"]).sort_values("date")
    if df.empty:
        return None

    row = df.iloc[-1]
    code = str(row["code"]).zfill(6)
    exchange = str(row["exchange"] or "").strip().lower() or infer_exchange(code)
    float_shares = to_db_value(row["float_shares"])
    float_shares_yi = float(float_shares) / 100000000 if float_shares is not None else None
    return code, exchange, float_shares, float_shares_yi, to_db_value(row["date"])


def fetch_eps(code: str, *, timeout: float, retries: int) -> EpsFetchResult:
    url = f"https://stockpage.10jqka.com.cn/{code}/"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(max(retries, 0) + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="ignore")
            match = EPS_PATTERN.search(html)
            if not match:
                return EpsFetchResult(eps=None, error="EPS pattern not found")
            return EpsFetchResult(eps=float(match.group(1)))
        except HTTPError as exc:
            if exc.code in {403, 429}:
                return EpsFetchResult(eps=None, blocked=True, error=f"HTTP {exc.code}")
            if attempt >= retries:
                print(f"EPS fetch failed for {code}: HTTP {exc.code}", file=sys.stderr)
                return EpsFetchResult(eps=None, error=f"HTTP {exc.code}")
            time.sleep(0.5 * (attempt + 1))
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt >= retries:
                print(f"EPS fetch failed for {code}: {exc}", file=sys.stderr)
                return EpsFetchResult(eps=None, error=str(exc))
            time.sleep(0.5 * (attempt + 1))
    return EpsFetchResult(eps=None, error="unknown EPS fetch failure")


def clean_sina_cell(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def extract_sina_left_column(table_html: str, *, skip_rows: int = 2) -> list[str]:
    values: list[str] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL)
    for row_index, row in enumerate(rows, start=1):
        if row_index <= skip_rows or re.search("备注", row):
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if not cells:
            continue
        value = clean_sina_cell(cells[0])
        if value:
            values.append(value)
    return values


def parse_sina_concept_html(raw_html: str) -> SinaConceptResult:
    tables = re.findall(
        r"<table[^>]*class=[\"']?comInfo1[\"']?[^>]*>.*?</table>",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    industry: list[str] = []
    concepts: list[str] = []
    for table_html in tables:
        if re.search("所属行业板块", table_html):
            industry = extract_sina_left_column(table_html, skip_rows=2)
        elif re.search("所属概念板块", table_html):
            concepts = extract_sina_left_column(table_html, skip_rows=2)
    if not tables:
        return SinaConceptResult(industry=[], concepts=[], blocked=True, error="Sina concept tables not found")
    if not industry and not concepts:
        return SinaConceptResult(industry=[], concepts=[], blocked=True, error="Sina concept parse returned no values")
    return SinaConceptResult(industry=industry, concepts=concepts)


def fetch_sina_concepts(code: str, *, timeout: float, retries: int) -> SinaConceptResult:
    url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpOtherInfo/stockid/{code}/menu_num/2.phtml"
    request = Request(
        url,
        headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    for attempt in range(max(retries, 0) + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
            if not body:
                return SinaConceptResult(industry=[], concepts=[], blocked=True, error="Sina response was empty")
            raw_html = body.decode("gb18030", errors="ignore")
            return parse_sina_concept_html(raw_html)
        except HTTPError as exc:
            if exc.code in {403, 429}:
                return SinaConceptResult(industry=[], concepts=[], blocked=True, error=f"HTTP {exc.code}")
            if attempt >= retries:
                print(f"Sina fetch failed for {code}: HTTP {exc.code}", file=sys.stderr)
                return SinaConceptResult(industry=[], concepts=[], error=f"HTTP {exc.code}")
            time.sleep(0.5 * (attempt + 1))
        except (URLError, TimeoutError, OSError, UnicodeDecodeError) as exc:
            if attempt >= retries:
                print(f"Sina fetch failed for {code}: {exc}", file=sys.stderr)
                return SinaConceptResult(industry=[], concepts=[], error=str(exc))
            time.sleep(0.5 * (attempt + 1))
    return SinaConceptResult(industry=[], concepts=[], error="unknown Sina fetch failure")


def parse_shareholder_research_rows(
    payload_rows: list[dict[str, Any]],
    *,
    code: str,
    exchange: str,
    secucode: str,
    start_date: date,
) -> list[ShareholderResearchRow]:
    rows: list[ShareholderResearchRow] = []
    for item in payload_rows:
        parsed_date = pd.to_datetime(item.get("END_DATE"), errors="coerce")
        if pd.isna(parsed_date):
            continue
        report_date = pd.Timestamp(parsed_date).date()
        if report_date < start_date:
            continue
        rows.append(
            ShareholderResearchRow(
                report_date=report_date,
                code=code,
                exchange=exchange,
                secucode=secucode,
                holder_total_num=to_db_value(item.get("HOLDER_TOTAL_NUM")),
                total_num_ratio=to_db_value(item.get("TOTAL_NUM_RATIO")),
                avg_free_shares=to_db_value(item.get("AVG_FREE_SHARES")),
                avg_freeshares_ratio=to_db_value(item.get("AVG_FREESHARES_RATIO")),
                hold_focus=str(item.get("HOLD_FOCUS")).strip() if item.get("HOLD_FOCUS") not in (None, "") else None,
            )
        )
    return rows


def fetch_shareholder_research(
    code: str,
    exchange: str,
    *,
    start_date: date,
    timeout: float,
    retries: int,
) -> ShareholderResearchFetchResult:
    secucode = eastmoney_secucode(code, exchange)
    params = {
        "reportName": "RPT_F10_EH_HOLDERNUM",
        "columns": (
            "SECUCODE,SECURITY_CODE,END_DATE,HOLDER_TOTAL_NUM,TOTAL_NUM_RATIO,"
            "AVG_FREE_SHARES,AVG_FREESHARES_RATIO,HOLD_FOCUS"
        ),
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": "1",
        "pageSize": "100",
        "sortTypes": "-1",
        "sortColumns": "END_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    url = f"{EASTMONEY_SHAREHOLDER_URL}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Referer": "https://emweb.securities.eastmoney.com/",
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    for attempt in range(max(retries, 0) + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            result = payload.get("result") if isinstance(payload, dict) else None
            data = result.get("data") if isinstance(result, dict) else None
            if isinstance(data, list):
                return ShareholderResearchFetchResult(
                    rows=parse_shareholder_research_rows(
                        data,
                        code=code,
                        exchange=exchange,
                        secucode=secucode,
                        start_date=start_date,
                    )
                )
            if isinstance(payload, dict) and payload.get("code") == 9201:
                return ShareholderResearchFetchResult(rows=[])
            message = payload.get("message") if isinstance(payload, dict) else None
            return ShareholderResearchFetchResult(rows=[], error=str(message or "unexpected Eastmoney payload"))
        except HTTPError as exc:
            if exc.code in {403, 429}:
                return ShareholderResearchFetchResult(rows=[], blocked=True, error=f"HTTP {exc.code}")
            if attempt >= retries:
                print(f"Eastmoney shareholder fetch failed for {code}: HTTP {exc.code}", file=sys.stderr)
                return ShareholderResearchFetchResult(rows=[], error=f"HTTP {exc.code}")
            time.sleep(0.5 * (attempt + 1))
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            if attempt >= retries:
                print(f"Eastmoney shareholder fetch failed for {code}: {exc}", file=sys.stderr)
                return ShareholderResearchFetchResult(rows=[], error=str(exc))
            time.sleep(0.5 * (attempt + 1))
    return ShareholderResearchFetchResult(rows=[], error="unknown Eastmoney shareholder fetch failure")


def upsert_shareholder_research(conn: Any, rows: list[ShareholderResearchRow]) -> int:
    if not rows:
        return 0
    params = [
        (
            row.report_date,
            row.code,
            row.exchange,
            row.secucode,
            row.holder_total_num,
            row.total_num_ratio,
            row.avg_free_shares,
            row.avg_freeshares_ratio,
            row.hold_focus,
            EASTMONEY_SHAREHOLDER_SOURCE,
        )
        for row in rows
    ]
    try:
        with conn.cursor() as cur:
            cur.executemany(SHAREHOLDER_RESEARCH_UPSERT_SQL, params)
            updated_rows = max(cur.rowcount or 0, 0)
        conn.commit()
        return updated_rows
    except Exception:
        conn.rollback()
        raise


def load_attribute_rows(
    valuation_dir: Path,
    *,
    limit: int,
    industry_attrs: dict[tuple[str, str], tuple[Any, Any, Any, Any]],
    status_file: Path | None = None,
) -> list[tuple[str, str, Any, Any, Any, Any, Any, Any, Any]]:
    share_rows: list[tuple[str, str, Any, Any, Any, Any, Any, Any, Any]] = []
    paths = sorted(valuation_dir.glob("*.parquet"))
    if limit > 0:
        paths = paths[:limit]

    for index, path in enumerate(paths, start=1):
        latest = latest_float_shares(path)
        if latest is None:
            continue
        code, exchange, float_shares, float_shares_yi, share_snapshot_date = latest
        industry_code, industry_name, industry_short_name, industry_classification = industry_attrs.get(
            (code, exchange),
            (None, None, None, None),
        )
        share_rows.append((
            code,
            exchange,
            float_shares,
            float_shares_yi,
            share_snapshot_date,
            industry_code,
            industry_name,
            industry_short_name,
            industry_classification,
        ))
        if index % 250 == 0:
            print(f"Loaded shares from {index}/{len(paths)} files, {len(share_rows)} rows.", flush=True)
            if status_file is not None:
                write_json_atomic(status_file, {
                    "status": "running",
                    "stage": "loading_float_shares",
                    "updated_at": now_iso(),
                    "loaded_share_rows": len(share_rows),
                    "scanned_files": index,
                    "total_files": len(paths),
                })
    return share_rows


def load_stock_master_refs(conn: Any, fallback_rows: list[tuple[str, str, Any, Any, Any, Any, Any, Any, Any]]) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select code, exchange
            from stock_master
            where coalesce(is_active, true)
            order by code asc, exchange asc
            """
        )
        refs = [(str(row[0]).zfill(6), str(row[1]).strip().lower() or infer_exchange(row[0])) for row in cur.fetchall()]
    if refs:
        return refs
    return [(row[0], row[1]) for row in fallback_rows]


def checkpoint_start_index(path: Path, *, reset: bool, total_codes: int) -> int:
    if reset:
        return 0
    checkpoint = read_json(path)
    if checkpoint.get("complete"):
        return 0
    try:
        next_index = int(checkpoint.get("next_index") or 0)
    except (TypeError, ValueError):
        return 0
    return min(max(next_index, 0), total_codes)


def write_status(
    path: Path,
    *,
    status: str,
    stage: str,
    total_codes: int,
    next_index: int,
    share_updated_count: int,
    eps_updated_count: int,
    failed_count: int,
    skipped_count: int,
    sina_industry_updated_count: int = 0,
    keyword_updated_count: int = 0,
    keyword_map_updated_count: int = 0,
    keyword_failed_count: int = 0,
    shareholder_research_updated_count: int = 0,
    last_code: str | None = None,
    last_error: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    done_count = min(max(next_index, 0), total_codes)
    write_json_atomic(path, {
        "status": status,
        "stage": stage,
        "updated_at": now_iso(),
        "started_at": started_at,
        "completed_at": completed_at,
        "total_codes": total_codes,
        "next_index": next_index,
        "done_count": done_count,
        "remaining_count": max(total_codes - done_count, 0),
        "progress_pct": round((done_count / total_codes) * 100, 2) if total_codes else None,
        "share_updated_count": share_updated_count,
        "eps_updated_count": eps_updated_count,
        "sina_industry_updated_count": sina_industry_updated_count,
        "keyword_updated_count": keyword_updated_count,
        "keyword_map_updated_count": keyword_map_updated_count,
        "keyword_failed_count": keyword_failed_count,
        "shareholder_research_updated_count": shareholder_research_updated_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "last_code": last_code,
        "last_error": last_error,
    })


def write_checkpoint(
    path: Path,
    *,
    next_index: int,
    total_codes: int,
    last_code: str | None,
    complete: bool = False,
) -> None:
    write_json_atomic(path, {
        "updated_at": now_iso(),
        "next_index": next_index,
        "total_codes": total_codes,
        "last_code": last_code,
        "complete": complete,
    })


def sync_sina_concepts(
    conn: Any,
    *,
    code: str,
    exchange: str,
    result: SinaConceptResult,
) -> tuple[int, int, int]:
    industry_updated = 0
    keyword_updated = 0
    keyword_map_updated = 0
    industry_name = result.industry[0] if result.industry else None
    try:
        with conn.cursor() as cur:
            if industry_name:
                cur.execute(SINA_INDUSTRY_UPDATE_SQL, [industry_name, code, exchange])
                industry_updated = max(cur.rowcount or 0, 0)
            for concept in result.concepts:
                cur.execute(KEYWORD_UPSERT_SQL, [concept])
                keyword_updated += 1
            cur.execute(DELETE_STOCK_KEYWORD_MAP_SQL, [code, exchange])
            for place_num, concept in enumerate(result.concepts, start=1):
                cur.execute(KEYWORD_MAP_UPSERT_SQL, [code, exchange, concept, place_num])
                keyword_map_updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return industry_updated, keyword_updated, keyword_map_updated


def main() -> int:
    args = parse_args()
    setup_log_file(Path(args.log_file) if args.log_file else None)
    install_signal_handlers()

    if not args.database_url:
        print("APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.", file=sys.stderr)
        return 2
    if psycopg is None:
        print("psycopg is not installed in this Python environment.", file=sys.stderr)
        return 2
    if args.limit < 0:
        print("--limit must be >= 0.", file=sys.stderr)
        return 2
    if args.sleep < 0:
        print("--sleep must be >= 0.", file=sys.stderr)
        return 2
    if args.block_error_threshold < 1:
        print("--block-error-threshold must be >= 1.", file=sys.stderr)
        return 2
    try:
        shareholder_start_date = parse_date_arg(args.shareholder_start_date, name="--shareholder-start-date")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    valuation_dir = Path(args.valuation_dir)
    stock_list_path = Path(args.stock_list)
    schema_sql_path = Path(args.schema_sql)
    status_file = Path(args.status_file)
    checkpoint_file = Path(args.checkpoint_file)
    if not valuation_dir.exists():
        print(f"{valuation_dir} does not exist.", file=sys.stderr)
        return 2
    if not schema_sql_path.exists():
        print(f"{schema_sql_path} does not exist.", file=sys.stderr)
        return 2

    started_at = now_iso()
    write_status(
        status_file,
        status="running",
        stage="starting",
        total_codes=0,
        next_index=0,
        share_updated_count=0,
        eps_updated_count=0,
        failed_count=0,
        skipped_count=0,
        started_at=started_at,
    )

    industry_attrs = load_industry_attrs(stock_list_path)
    print(f"Loaded local industry attributes for {len(industry_attrs)} stocks.", flush=True)

    share_rows = load_attribute_rows(
        valuation_dir,
        limit=args.limit,
        industry_attrs=industry_attrs,
        status_file=status_file,
    )
    schema_sql = schema_sql_path.read_text(encoding="utf-8")
    stock_refs: list[tuple[str, str]] = []

    with psycopg.connect(args.database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
                if not args.skip_eps:
                    cur.execute(DELETE_OLD_SHAREHOLDER_RESEARCH_SQL, [shareholder_start_date])
                cur.executemany(
                    SHARE_UPDATE_SQL,
                    [
                        (
                            float_shares,
                            float_shares_yi,
                            share_snapshot_date,
                            industry_code,
                            industry_name,
                            industry_short_name,
                            industry_classification,
                            code,
                            exchange,
                        )
                        for (
                            code,
                            exchange,
                            float_shares,
                            float_shares_yi,
                            share_snapshot_date,
                            industry_code,
                            industry_name,
                            industry_short_name,
                            industry_classification,
                        ) in share_rows
                    ],
                )
                share_updated = cur.rowcount
            conn.commit()
            stock_refs = load_stock_master_refs(conn, share_rows)
        except Exception:
            conn.rollback()
            raise

    share_count = sum(1 for row in share_rows if row[2] is not None)
    total_codes = len(stock_refs)
    industry_count = sum(1 for row in share_rows if row[6] is not None)
    print(
        f"Updated stock_master local attributes: rows={len(share_rows)}, shares={share_count}, "
        f"industries={industry_count}, db_updated={share_updated}, stock_refs={total_codes}.",
        flush=True,
    )

    if args.skip_eps:
        write_checkpoint(checkpoint_file, next_index=total_codes, total_codes=total_codes, last_code=None, complete=True)
        write_status(
            status_file,
            status="success",
            stage="complete",
            total_codes=total_codes,
            next_index=total_codes,
            share_updated_count=share_updated,
            eps_updated_count=0,
            failed_count=0,
            skipped_count=0,
            started_at=started_at,
            completed_at=now_iso(),
        )
        print(f"Updated stock_master attributes: rows={len(share_rows)}, shares={share_count}, industries={industry_count}, eps=0, db_updated={share_updated}.")
        return 0

    start_index = checkpoint_start_index(checkpoint_file, reset=args.reset_checkpoint, total_codes=total_codes)
    print(
        f"Starting EPS, Sina, and Eastmoney shareholder fetch at "
        f"index {start_index + 1 if total_codes else 0}/{total_codes}; sleep={args.sleep}s.",
        flush=True,
    )

    eps_updated_count = 0
    sina_industry_updated_count = 0
    keyword_updated_count = 0
    keyword_map_updated_count = 0
    keyword_failed_count = 0
    shareholder_research_updated_count = 0
    failed_count = 0
    skipped_count = 0
    consecutive_eps_block_errors = 0
    consecutive_sina_block_errors = 0
    consecutive_shareholder_block_errors = 0
    last_code: str | None = None
    last_error: str | None = None

    with psycopg.connect(args.database_url) as conn:
        for index in range(start_index, total_codes):
            if STOP_REQUESTED:
                write_checkpoint(checkpoint_file, next_index=index, total_codes=total_codes, last_code=last_code, complete=False)
                write_status(
                    status_file,
                    status="stopped",
                    stage="stock_attributes",
                    total_codes=total_codes,
                    next_index=index,
                    share_updated_count=share_updated,
                    eps_updated_count=eps_updated_count,
                    sina_industry_updated_count=sina_industry_updated_count,
                    keyword_updated_count=keyword_updated_count,
                    keyword_map_updated_count=keyword_map_updated_count,
                    keyword_failed_count=keyword_failed_count,
                    shareholder_research_updated_count=shareholder_research_updated_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    last_code=last_code,
                    last_error="Stop requested",
                    started_at=started_at,
                    completed_at=now_iso(),
                )
                print("Stopped before next EPS/Sina request.", flush=True)
                return 130

            code, exchange = stock_refs[index]
            last_code = code
            print(f"Fetching EPS, Sina, and Eastmoney data {index + 1}/{total_codes}: {code}/{exchange}", flush=True)
            result = fetch_eps(code, timeout=args.timeout, retries=args.retries)

            if result.blocked:
                consecutive_eps_block_errors += 1
                failed_count += 1
                last_error = result.error or "blocked"
                print(f"Blocked response for {code}: {last_error} ({consecutive_eps_block_errors}/{args.block_error_threshold})", file=sys.stderr, flush=True)
                if consecutive_eps_block_errors >= args.block_error_threshold:
                    write_checkpoint(checkpoint_file, next_index=index, total_codes=total_codes, last_code=code, complete=False)
                    write_status(
                        status_file,
                        status="blocked",
                        stage="eps",
                        total_codes=total_codes,
                        next_index=index,
                        share_updated_count=share_updated,
                        eps_updated_count=eps_updated_count,
                        sina_industry_updated_count=sina_industry_updated_count,
                        keyword_updated_count=keyword_updated_count,
                        keyword_map_updated_count=keyword_map_updated_count,
                        keyword_failed_count=keyword_failed_count,
                        shareholder_research_updated_count=shareholder_research_updated_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        last_code=code,
                        last_error=last_error,
                        started_at=started_at,
                        completed_at=now_iso(),
                    )
                    print("Stopping because consecutive blocked responses reached threshold.", file=sys.stderr, flush=True)
                    return 3
            else:
                consecutive_eps_block_errors = 0
                if result.eps is None:
                    skipped_count += 1
                    last_error = result.error
                    print(f"EPS unavailable for {code}; keeping existing value. Reason: {result.error}", flush=True)
                else:
                    try:
                        with conn.cursor() as cur:
                            cur.execute(EPS_UPDATE_SQL, [result.eps, code, exchange])
                            updated_rows = cur.rowcount
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                    if updated_rows and updated_rows > 0:
                        eps_updated_count += 1
                        last_error = None
                        print(f"Updated EPS for {code}/{exchange}: {result.eps}", flush=True)
                    else:
                        skipped_count += 1
                        last_error = "stock_master row not found"
                        print(f"EPS fetched for {code}/{exchange}, but stock_master row was not found.", flush=True)

            sina_result = fetch_sina_concepts(code, timeout=args.timeout, retries=args.retries)
            if sina_result.blocked:
                consecutive_sina_block_errors += 1
                keyword_failed_count += 1
                failed_count += 1
                last_error = sina_result.error or "Sina blocked"
                print(
                    f"Blocked Sina response for {code}: {last_error} ({consecutive_sina_block_errors}/{args.block_error_threshold})",
                    file=sys.stderr,
                    flush=True,
                )
                if consecutive_sina_block_errors >= args.block_error_threshold:
                    write_checkpoint(checkpoint_file, next_index=index, total_codes=total_codes, last_code=code, complete=False)
                    write_status(
                        status_file,
                        status="blocked",
                        stage="sina_keywords",
                        total_codes=total_codes,
                        next_index=index,
                        share_updated_count=share_updated,
                        eps_updated_count=eps_updated_count,
                        sina_industry_updated_count=sina_industry_updated_count,
                        keyword_updated_count=keyword_updated_count,
                        keyword_map_updated_count=keyword_map_updated_count,
                        keyword_failed_count=keyword_failed_count,
                        shareholder_research_updated_count=shareholder_research_updated_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        last_code=code,
                        last_error=last_error,
                        started_at=started_at,
                        completed_at=now_iso(),
                    )
                    print("Stopping because consecutive Sina blocked responses reached threshold.", file=sys.stderr, flush=True)
                    return 3
            elif sina_result.error:
                consecutive_sina_block_errors = 0
                keyword_failed_count += 1
                skipped_count += 1
                last_error = sina_result.error
                print(f"Sina data unavailable for {code}; keeping existing keywords. Reason: {sina_result.error}", flush=True)
            else:
                consecutive_sina_block_errors = 0
                industry_delta, keyword_delta, keyword_map_delta = sync_sina_concepts(
                    conn,
                    code=code,
                    exchange=exchange,
                    result=sina_result,
                )
                sina_industry_updated_count += industry_delta
                keyword_updated_count += keyword_delta
                keyword_map_updated_count += keyword_map_delta
                last_error = None
                print(
                    f"Updated Sina data for {code}/{exchange}: "
                    f"industry={sina_result.industry[0] if sina_result.industry else '-'}, "
                    f"concepts={len(sina_result.concepts)}",
                    flush=True,
                )

            shareholder_result = fetch_shareholder_research(
                code,
                exchange,
                start_date=shareholder_start_date,
                timeout=args.timeout,
                retries=args.retries,
            )
            if shareholder_result.blocked:
                consecutive_shareholder_block_errors += 1
                failed_count += 1
                last_error = shareholder_result.error or "Eastmoney blocked"
                print(
                    f"Blocked Eastmoney shareholder response for {code}: "
                    f"{last_error} ({consecutive_shareholder_block_errors}/{args.block_error_threshold})",
                    file=sys.stderr,
                    flush=True,
                )
                if consecutive_shareholder_block_errors >= args.block_error_threshold:
                    write_checkpoint(checkpoint_file, next_index=index, total_codes=total_codes, last_code=code, complete=False)
                    write_status(
                        status_file,
                        status="blocked",
                        stage="eastmoney_shareholder_research",
                        total_codes=total_codes,
                        next_index=index,
                        share_updated_count=share_updated,
                        eps_updated_count=eps_updated_count,
                        sina_industry_updated_count=sina_industry_updated_count,
                        keyword_updated_count=keyword_updated_count,
                        keyword_map_updated_count=keyword_map_updated_count,
                        keyword_failed_count=keyword_failed_count,
                        shareholder_research_updated_count=shareholder_research_updated_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        last_code=code,
                        last_error=last_error,
                        started_at=started_at,
                        completed_at=now_iso(),
                    )
                    print(
                        "Stopping because consecutive Eastmoney blocked responses reached threshold.",
                        file=sys.stderr,
                        flush=True,
                    )
                    return 3
            elif shareholder_result.error:
                consecutive_shareholder_block_errors = 0
                skipped_count += 1
                last_error = shareholder_result.error
                print(
                    f"Eastmoney shareholder data unavailable for {code}; keeping existing rows. "
                    f"Reason: {shareholder_result.error}",
                    flush=True,
                )
            else:
                consecutive_shareholder_block_errors = 0
                updated_rows = upsert_shareholder_research(conn, shareholder_result.rows)
                shareholder_research_updated_count += updated_rows
                last_error = None
                print(
                    f"Updated Eastmoney shareholder research for {code}/{exchange}: "
                    f"rows={updated_rows}, since={shareholder_start_date.isoformat()}",
                    flush=True,
                )

            next_index = index + 1
            write_checkpoint(checkpoint_file, next_index=next_index, total_codes=total_codes, last_code=code, complete=False)
            write_status(
                status_file,
                status="running",
                stage="stock_attributes",
                total_codes=total_codes,
                next_index=next_index,
                share_updated_count=share_updated,
                eps_updated_count=eps_updated_count,
                sina_industry_updated_count=sina_industry_updated_count,
                keyword_updated_count=keyword_updated_count,
                keyword_map_updated_count=keyword_map_updated_count,
                keyword_failed_count=keyword_failed_count,
                shareholder_research_updated_count=shareholder_research_updated_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                last_code=code,
                last_error=last_error,
                started_at=started_at,
            )

            if args.sleep > 0 and next_index < total_codes:
                time.sleep(args.sleep)

    write_checkpoint(checkpoint_file, next_index=total_codes, total_codes=total_codes, last_code=last_code, complete=True)
    write_status(
        status_file,
        status="success",
        stage="complete",
        total_codes=total_codes,
        next_index=total_codes,
        share_updated_count=share_updated,
        eps_updated_count=eps_updated_count,
        sina_industry_updated_count=sina_industry_updated_count,
        keyword_updated_count=keyword_updated_count,
        keyword_map_updated_count=keyword_map_updated_count,
        keyword_failed_count=keyword_failed_count,
        shareholder_research_updated_count=shareholder_research_updated_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        last_code=last_code,
        last_error=last_error,
        started_at=started_at,
        completed_at=now_iso(),
    )
    print(
        "Updated stock_master attributes: "
        f"rows={len(share_rows)}, shares={share_count}, industries={industry_count}, eps={eps_updated_count}, "
        f"sina_industries={sina_industry_updated_count}, keywords={keyword_updated_count}, "
        f"keyword_maps={keyword_map_updated_count}, shareholder_research={shareholder_research_updated_count}, "
        f"skipped={skipped_count}, failed={failed_count}, "
        f"keyword_failed={keyword_failed_count}, db_updated={share_updated + eps_updated_count + sina_industry_updated_count + keyword_map_updated_count}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
