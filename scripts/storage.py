"""
수집 결과 저장/이력 관리

data/history.json 구조:
{
  "metrics": ["bok_base","cd91","cp1m","cp3m","corp_aa_1y","corp_aa_2y","corp_aa_3y","treasury_3y","sofr"],
  "days": {
    "2026-09-07": {
        "values": {"bok_base": 3.00, "cd91": 3.12, ..., "sofr": 3.66},
        "status":  {"bok_base": "ok", ..., "sofr": "ok"},
        "effective_date": {"bok_base": "2026-08-27", "cd91": "2026-09-04", ...},
        "backfilled": false
    },
    "2026-09-06": {..., "backfilled": true},
    ...
  }
}

- "backfilled": true 인 날짜는 주말(토/일)이라 그 자체로는 거래일이 아니지만,
  "직전 영업일" 계산상 다음 월요일과 완전히 동일한 대상일로 수렴하므로 그 월요일
  수집 결과를 그대로 재사용해 채운 날짜임을 표시한다.
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
    "treasury_3y",
    "sofr",
]

METRIC_LABELS = {
    "bok_base": "한국은행 기준금리",
    "cd91": "CD(3개월)",
    "cp1m": "A1CP(1개월)",
    "cp3m": "A1CP(3개월)",
    "corp_aa_1y": "회사채(AA-,1년)",
    "corp_aa_2y": "회사채(AA-,2년)",
    "corp_aa_3y": "회사채(AA-,3년)",
    "treasury_3y": "국고채권(3년)",
    "sofr": "SOFR",
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
