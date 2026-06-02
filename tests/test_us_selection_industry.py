from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "update_us_selection_data.py"

spec = importlib.util.spec_from_file_location("update_us_selection_data", SCRIPT_PATH)
assert spec is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


def test_normalize_finnhub_industry_rejects_empty_values() -> None:
    assert module.normalize_finnhub_industry(None) is None
    assert module.normalize_finnhub_industry("") is None
    assert module.normalize_finnhub_industry("  ") is None
    assert module.normalize_finnhub_industry("N/A") is None
    assert module.normalize_finnhub_industry("n/a") is None


def test_translate_finnhub_industry_known_values() -> None:
    assert module.translate_finnhub_industry("Airlines") == ("航空公司", "航空")
    assert module.translate_finnhub_industry("Automobiles") == ("汽车制造", "汽车")
    assert module.translate_finnhub_industry("Financial Services") == ("金融服务", "金融")
    assert module.translate_finnhub_industry("Hotels, Restaurants & Leisure") == ("酒店餐饮休闲", "餐饮旅游")
    assert module.translate_finnhub_industry("Semiconductors") == ("半导体", "半导体")
    assert module.translate_finnhub_industry("Technology") == ("科技", "科技")


def test_translate_finnhub_industry_unknown_value() -> None:
    assert module.normalize_finnhub_industry("Space Exploration") == "Space Exploration"
    assert module.translate_finnhub_industry("Space Exploration") is None
