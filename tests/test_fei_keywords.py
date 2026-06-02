from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.fei_keywords import FeiKeywordError, normalize_keyword_ids


def test_normalize_keyword_ids_accepts_empty_and_ordered_ids() -> None:
    assert normalize_keyword_ids([]) == []
    assert normalize_keyword_ids([71, 72, 75]) == [71, 72, 75]


@pytest.mark.parametrize("payload", [None, "71", {"keyword_ids": [71]}, [0], [-1], [True], [1.2], ["1"]])
def test_normalize_keyword_ids_rejects_invalid_payloads(payload: object) -> None:
    with pytest.raises(FeiKeywordError, match="invalid_keyword_ids"):
        normalize_keyword_ids(payload)


def test_normalize_keyword_ids_rejects_duplicate_ids() -> None:
    with pytest.raises(FeiKeywordError, match="duplicate_keyword_id"):
        normalize_keyword_ids([71, 72, 71])
