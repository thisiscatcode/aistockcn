#!/usr/bin/env python3
"""Import quant_data/stock_list.parquet into the stock_master Postgres table."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import psycopg
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None


REQUIRED_COLUMNS = [
    "code",
    "exchange",
    "name",
    "industry",
    "industry_classification",
    "update_date",
    "trade_date",
    "universe",
    "is_active",
    "first_seen_date",
    "last_seen_date",
    "inactive_date",
]

DATE_COLUMNS = {
    "update_date",
    "trade_date",
    "first_seen_date",
    "last_seen_date",
    "inactive_date",
}

INDUSTRY_PATTERN = re.compile(r"^([A-Z]\d{2})(.+)$")

UPSERT_SQL = """
insert into stock_master (
  code,
  exchange,
  name,
  industry_code,
  industry_name,
  industry_short_name,
  industry_classification,
  update_date,
  trade_date,
  universe,
  is_active,
  first_seen_date,
  last_seen_date,
  inactive_date,
  imported_at
) values (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
)
on conflict (code, exchange) do update set
  name = excluded.name,
  industry_code = coalesce(excluded.industry_code, stock_master.industry_code),
  industry_name = coalesce(excluded.industry_name, stock_master.industry_name),
  industry_short_name = coalesce(excluded.industry_short_name, stock_master.industry_short_name),
  industry_classification = coalesce(excluded.industry_classification, stock_master.industry_classification),
  update_date = excluded.update_date,
  trade_date = excluded.trade_date,
  universe = excluded.universe,
  is_active = excluded.is_active,
  first_seen_date = excluded.first_seen_date,
  last_seen_date = excluded.last_seen_date,
  inactive_date = excluded.inactive_date,
  imported_at = now()
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import stock_list.parquet into Postgres stock_master.")
    parser.add_argument(
        "--stock-list",
        default="quant_data/stock_list.parquet",
        help="Path to stock_list.parquet.",
    )
    parser.add_argument(
        "--schema-sql",
        default="scripts/create_stock_master.sql",
        help="Path to the SQL file that creates stock_master.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("APP_DB_URL") or os.getenv("PAPER_DB_URL"),
        help="Postgres DSN. Defaults to APP_DB_URL, then PAPER_DB_URL.",
    )
    return parser.parse_args()


def to_db_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


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


def load_rows(stock_list_path: Path) -> list[tuple[Any, ...]]:
    if not stock_list_path.exists():
        raise FileNotFoundError(f"{stock_list_path} does not exist")

    df = pd.read_parquet(stock_list_path)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{stock_list_path} is missing required columns: {', '.join(missing)}")

    df = df[REQUIRED_COLUMNS].copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["exchange"] = df["exchange"].astype(str)
    for column in DATE_COLUMNS:
        df[column] = pd.to_datetime(df[column], errors="coerce")

    rows: list[tuple[Any, ...]] = []
    for record in df.to_dict(orient="records"):
        industry_code, industry_name = split_industry(record.get("industry"))
        industry_short_name = short_industry_name(industry_name)
        values: list[Any] = []
        for column in REQUIRED_COLUMNS:
            if column == "industry":
                values.extend([industry_code, industry_name, industry_short_name])
                continue
            values.append(to_db_value(record[column]))
        rows.append(tuple(values))
    return rows


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("APP_DB_URL or PAPER_DB_URL must be set, or pass --database-url.", file=sys.stderr)
        return 2
    if psycopg is None:
        print("psycopg is not installed in this Python environment.", file=sys.stderr)
        return 2

    stock_list_path = Path(args.stock_list)
    schema_sql_path = Path(args.schema_sql)
    if not schema_sql_path.exists():
        print(f"{schema_sql_path} does not exist.", file=sys.stderr)
        return 2

    rows = load_rows(stock_list_path)
    schema_sql = schema_sql_path.read_text(encoding="utf-8")

    with psycopg.connect(args.database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
                cur.executemany(UPSERT_SQL, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    print(f"Imported {len(rows)} rows from {stock_list_path} into stock_master.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
