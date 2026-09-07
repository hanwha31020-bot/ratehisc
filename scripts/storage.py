"""
수집 결과 저장/이력 관리

data/history.json 구조:
{
  "metrics": ["bok_base","cd91","cp1m","cp3m","corp_aa_1y","corp_aa_2y","corp_aa_3y","sofr","ust2y"],
  "days": {
    "2026-09-07": {
        "values": {"bok_base": 3.00, "cd91": 3.12, ..., "ust2y": 4.379},
        "status":  {"bok_base": "ok", ..., "ust2y": "blocked"},
        "effective_date": {"bok_base": "2026-08-27", "cd91": "2026-09-04", ...},
        "backfilled": false
    },
    "2026-09-06": {..., "backfilled": true},
    ...
  }
}

- "backfilled": true 인 날짜는 주말(토/일)이라 실제로 수집을 돌리지 않고,
  직전 금요일의 값을 그대로 복사해 넣은 날짜임을 표시한다.
- status 값: "ok"(정상수집), "blocked"(접속차단 등 실패, 값은 null), "no_data"(대상일 데이터 없음)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

METRICS = [
    "bok_base",
    "cd91",
    "cp1m",
    "cp3m",
    "corp_aa_1y",
    "corp_aa_2y",
    "corp_aa_3y",
    "sofr",
    "ust2y",
]

METRIC_LABELS = {
    "bok_base": "한국은행 기준금리",
    "cd91": "CD(3개월)",
    "cp1m": "A1CP(1개월)",
    "cp3m": "A1CP(3개월)",
    "corp_aa_1y": "회사채(AA-,1년)",
    "corp_aa_2y": "회사채(AA-,2년)",
    "corp_aa_3y": "회사채(AA-,3년)",
    "sofr": "SOFR",
    "ust2y": "미국 2년 국채",
}


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"metrics": METRICS, "days": {}}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("metrics", METRICS)
    data.setdefault("days", {})
    return data


def save_history(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def upsert_day(
    data: dict[str, Any],
    iso_date: str,
    values: dict[str, Optional[float]],
    status: dict[str, str],
    effective_date: dict[str, Optional[str]],
    backfilled: bool = False,
) -> None:
    data["days"][iso_date] = {
        "values": values,
        "status": status,
        "effective_date": effective_date,
        "backfilled": backfilled,
    }


def copy_day_as_backfill(data: dict[str, Any], src_iso_date: str, dst_iso_date: str) -> bool:
    """src_iso_date의 값을 그대로 dst_iso_date에 복사(주말 백필용). 성공하면 True."""
    src = data["days"].get(src_iso_date)
    if src is None:
        return False
    data["days"][dst_iso_date] = {
        "values": dict(src["values"]),
        "status": dict(src["status"]),
        "effective_date": dict(src["effective_date"]),
        "backfilled": True,
    }
    return True
