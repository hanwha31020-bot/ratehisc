"""
수집 결과 저장/이력 관리

data/history.json 구조:
{
  "metrics": ["bok_base","cd91","cp3m","cp1m","corp_aa_1y","corp_aa_2y","corp_aa_3y","treasury_3y","sofr"],
  "last_run_at": "2026-09-11 08:34 KST",
  "days": {
    "2026-09-04": {
        "values": {"bok_base": 3.00, "cd91": 3.12, ..., "sofr": 3.66},
        "status":  {"bok_base": "ok", ..., "sofr": "ok"},
        "effective_date": {"bok_base": "2026-08-27", "cd91": "2026-09-04", ...},
        "backfilled": false
    },
    "2026-09-05": {..., "backfilled": true},
    ...
  }
}

- "days"의 키는 "이 값이 실제로 유효한 기준일(국내 대상일)"이다. 수집을 실행한
  날짜(오늘)가 아니다 - 예를 들어 9/7(월)에 실행한 결과는 그 실행일이 아니라 실제
  조회 대상이었던 "2026-09-04"(금) 밑에 저장된다. 9/7 자신의 값은 그 다음 영업일
  실행에서 별도로 채워진다.
- "backfilled": true 인 날짜는 주말(토/일)이라 그 자체로는 거래일이 아니며, 직전
  금요일 레코드와 그 다음 월요일 레코드를 섞어서 채운 날짜임을 표시한다. 국내
  (KOFIA/BOK) 값은 금요일 레코드 것을 그대로 쓰고(주말엔 새 시세가 없으므로
  금요일 종가가 곧 주말 값), 해외(SOFR)만 월요일 레코드 것으로 대체한다 -
  뉴욕 연은은 대상일의 다음 영업일에야 값을 공시해서, 금요일 레코드가 만들어지는
  시점(그 전 월요일)엔 금요일자 SOFR가 아직 발표 전(목요일자가 대신 들어감)이고,
  그 다음 월요일이 되어서야 비로소 확정된 금요일자 SOFR를 얻을 수 있기 때문이다.
- status 값: "ok"(정상수집), "blocked"(접속차단 등 실패, 값은 null), "no_data"(대상일 데이터 없음)
- 같은 날짜에 여러 번 upsert_day가 호출돼도(예: 하루 여러 번 재시도), 항목별로
  이미 "ok"였던 값을 나중 시도의 실패값이 덮어쓰지 않는다 (upsert_day 참고).
- "last_run_at"은 "days" 내용에 실제로 변화가 있었던 마지막 실행 시각(KST)이다.
  하루에 여러 번(예: 예약 실행 재시도) 스크립트가 돌아도 값이 그대로면 이 필드는
  갱신하지 않는다 - 그래야 "오늘 최초로 성공한 시각"이 유지되고, 재시도마다
  이 필드만 바뀌어서 매번 불필요한 커밋이 쌓이는 일도 없다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

METRICS = [
    "bok_base",
    "cd91",
    "cp3m",
    "cp1m",
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


def snapshot_days(data: dict[str, Any]) -> str:
    """"days" 내용을 문자열로 직렬화한다. 실행 전/후 스냅샷을 비교해서 이번 실행이
    실제로 뭔가를 바꿨는지 판단하는 용도 (record_run을 호출할지 결정할 때 쓴다)."""
    return json.dumps(data.get("days", {}), sort_keys=True)


def record_run(data: dict[str, Any]) -> None:
    """지금 시각(KST, GitHub Actions에서 TZ=Asia/Seoul로 실행됨)을 last_run_at에 기록한다.
    "days"에 실제 변화가 있었을 때만 호출해야 한다 - 그래야 이 필드가 "오늘 최초
    성공 시각"으로 유지된다."""
    data["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M") + " KST"


def upsert_day(
    data: dict[str, Any],
    iso_date: str,
    values: dict[str, Optional[float]],
    status: dict[str, str],
    effective_date: dict[str, Optional[str]],
    backfilled: bool = False,
) -> None:
    """지정한 날짜의 레코드를 기록한다. 같은 날짜에 이미 "ok"로 성공해둔 항목이
    있는데 이번 호출에서 그 항목만 실패("ok"가 아님)로 왔다면, 그 항목은 기존 값을
    그대로 유지한다 - 하루에 여러 번 재시도할 때, 일시적 접속 차단 등으로 나중
    시도가 먼저 시도보다 더 나쁜 결과를 내더라도 이미 확보한 정상값을 덮어쓰지
    않기 위함이다."""
    existing = data["days"].get(iso_date)
    merged_values = dict(values)
    merged_status = dict(status)
    merged_effective = dict(effective_date)
    if existing:
        for metric, new_status in status.items():
            if new_status != "ok" and existing.get("status", {}).get(metric) == "ok":
                merged_values[metric] = existing["values"][metric]
                merged_status[metric] = existing["status"][metric]
                merged_effective[metric] = existing["effective_date"][metric]
    data["days"][iso_date] = {
        "values": merged_values,
        "status": merged_status,
        "effective_date": merged_effective,
        "backfilled": backfilled,
    }
