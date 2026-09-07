#!/usr/bin/env python3
"""
과거 영업일치 금리를 한 번에 채워 넣는 백필 스크립트.

fetch_rates.py(매일 실행)는 "오늘자"만 채우므로, 처음 시작할 때 과거 이력이
비어 있으면 이 스크립트로 한 번에 채워 넣는다. 오늘자는 건드리지 않는다
(직전 영업일까지만 채운다).

사용법 (저장소 루트에서):
    python scripts/backfill.py            # 최근 22영업일(약 한 달)
    python scripts/backfill.py --days 10  # 최근 10영업일만

BOK(기준금리)와 미국 2년 국채(investing.com)는 날짜별 조회 API가 아니라
"이력 페이지 하나를 통째로 받아서 그 안에서 원하는 날짜를 찾는" 방식이므로,
날짜마다 반복 요청하면 비효율적이고 특히 investing.com은 Cloudflare 차단
위험이 커진다. 그래서 이 두 소스는 스크립트 시작 시 한 번만 받아서 재사용한다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from date_utils import business_days_range_ending, fmt_iso, previous_business_day  # noqa: E402
from export_xlsx import export_history_to_xlsx  # noqa: E402
from fetch_rates import (  # noqa: E402
    HISTORY_PATH,
    XLSX_PATH,
    backfill_weekend,
    collect_day,
    gha_notice,
    gha_warning,
)
from sources import bok, ust2y  # noqa: E402
from storage import load_history, save_history, upsert_day  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="과거 영업일 금리 일괄 백필")
    parser.add_argument("--days", type=int, default=22, help="채워 넣을 영업일 수 (기본 22 = 약 한 달)")
    args = parser.parse_args()

    end = previous_business_day(date.today())  # 오늘자는 fetch_rates.py 몫이라 제외
    days = business_days_range_ending(end, args.days)

    gha_notice("BOK 기준금리 이력 / 미국 2년 국채 이력을 한 번만 미리 받아둡니다.")
    try:
        bok_rows = bok.fetch_all_base_rates()
    except Exception as exc:  # noqa: BLE001
        gha_warning(f"BOK 기준금리 이력 조회 실패, 해당 항목은 이번 백필에서 비워둡니다: {exc}")
        bok_rows = []

    try:
        ust2y_rows = ust2y.fetch_historical_rows()
    except Exception as exc:  # noqa: BLE001
        gha_warning(f"미국 2년 국채 이력 조회 실패, 해당 항목은 이번 백필에서 비워둡니다: {exc}")
        ust2y_rows = []

    data = load_history(HISTORY_PATH)
    for d in days:
        gha_notice(f"백필 진행: {fmt_iso(d)}")
        values, status, effective = collect_day(d, bok_rows=bok_rows, ust2y_rows=ust2y_rows)
        upsert_day(data, fmt_iso(d), values, status, effective, backfilled=False)
        backfill_weekend(data, d)
        failed = [m for m, s in status.items() if s != "ok"]
        if failed:
            gha_warning(f"{fmt_iso(d)} 실패/누락 항목: {', '.join(failed)}")

    save_history(HISTORY_PATH, data)
    export_history_to_xlsx(data, XLSX_PATH)
    gha_notice(f"백필 완료: {fmt_iso(days[0])} ~ {fmt_iso(days[-1])} ({len(days)}영업일)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
