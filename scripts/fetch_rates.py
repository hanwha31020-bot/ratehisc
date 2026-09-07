#!/usr/bin/env python3
"""
매일 실행되는 금리 수집 메인 스크립트.

실행 흐름:
1. 오늘(KST) 기준 국내/해외 대상일 계산
2. 4개 국내 소스(BOK, CD, CP, 채권) 수집 (KOFIA 3종은 공휴일 등으로 데이터가 없으면
   자동으로 하루씩 더 앞으로 이동하며 재시도)
3. 2개 해외 소스(SOFR, 미국2년) 수집 (각자 "대상일 이하 최신값" 방식으로 자체 처리)
4. data/history.json 에 오늘자 레코드 upsert
5. 주말(토/일) 백필: 오늘이 월요일이면 직전 토/일에 금요일자 값을 복사
6. data/history.json 저장 + data/history.xlsx 재생성
7. 실패한 항목이 있으면 GitHub Actions 경고 어노테이션 출력
"""
from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from date_utils import KST, compute_targets, fmt_iso, find_available  # noqa: E402
from sources import bok, kofia, sofr, ust2y  # noqa: E402
from storage import (  # noqa: E402
    load_history,
    save_history,
    upsert_day,
    copy_day_as_backfill,
)
from export_xlsx import export_history_to_xlsx  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = REPO_ROOT / "docs" / "data" / "history.json"
XLSX_PATH = REPO_ROOT / "docs" / "data" / "history.xlsx"


def gha_warning(message: str) -> None:
    print(f"::warning::{message}")


def gha_notice(message: str) -> None:
    print(f"::notice::{message}")


def fetch_domestic(domestic_target: date, bok_rows: Optional[list] = None):
    values: dict[str, Optional[float]] = {}
    status: dict[str, str] = {}
    effective: dict[str, Optional[str]] = {}

    # 1) 한국은행 기준금리 (domestic_target 시점에 실제로 적용 중이던 값을 찾는다.
    #    "최신값"을 그냥 쓰면 금통위 회의 이후로 백필할 때 과거 날짜에 오늘의 금리가
    #    잘못 채워지므로, 반드시 대상일 기준으로 조회해야 한다)
    try:
        bok_result = (
            bok.base_rate_on(bok_rows, domestic_target)
            if bok_rows is not None
            else bok.fetch_base_rate_on(domestic_target)
        )
        if bok_result is not None:
            values["bok_base"] = bok_result.rate
            status["bok_base"] = "ok"
            effective["bok_base"] = fmt_iso(bok_result.effective_date)
        else:
            values["bok_base"] = None
            status["bok_base"] = "no_data"
            effective["bok_base"] = None
            gha_warning("BOK 기준금리: 표를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["bok_base"] = None
        status["bok_base"] = "blocked"
        effective["bok_base"] = None
        gha_warning(f"BOK 기준금리 수집 실패: {exc}")
        traceback.print_exc()

    # 2) CD(3개월)
    try:
        found_date, cd_val = find_available(kofia.fetch_cd, domestic_target)
        values["cd91"] = cd_val
        status["cd91"] = "ok" if cd_val is not None else "no_data"
        effective["cd91"] = fmt_iso(found_date) if found_date else None
        if cd_val is None:
            gha_warning("CD(3개월): 최근 10영업일 내 데이터를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["cd91"] = None
        status["cd91"] = "blocked"
        effective["cd91"] = None
        gha_warning(f"CD(3개월) 수집 실패: {exc}")
        traceback.print_exc()

    # 3) A1CP(1개월/3개월)
    try:
        found_date, cp_val = find_available(kofia.fetch_cp, domestic_target)
        if cp_val is not None:
            values["cp1m"] = cp_val.one_month
            values["cp3m"] = cp_val.three_month
            status["cp1m"] = status["cp3m"] = "ok"
            effective["cp1m"] = effective["cp3m"] = fmt_iso(found_date)
        else:
            values["cp1m"] = values["cp3m"] = None
            status["cp1m"] = status["cp3m"] = "no_data"
            effective["cp1m"] = effective["cp3m"] = None
            gha_warning("A1CP: 최근 10영업일 내 데이터를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["cp1m"] = values["cp3m"] = None
        status["cp1m"] = status["cp3m"] = "blocked"
        effective["cp1m"] = effective["cp3m"] = None
        gha_warning(f"A1CP 수집 실패: {exc}")
        traceback.print_exc()

    # 4) 회사채(AA-, 1/2/3년)
    try:
        found_date, bond_val = find_available(kofia.fetch_corp_bond, domestic_target)
        if bond_val is not None:
            values["corp_aa_1y"] = bond_val.y1
            values["corp_aa_2y"] = bond_val.y2
            values["corp_aa_3y"] = bond_val.y3
            status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = "ok"
            effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = fmt_iso(found_date)
        else:
            values["corp_aa_1y"] = values["corp_aa_2y"] = values["corp_aa_3y"] = None
            status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = "no_data"
            effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = None
            gha_warning("회사채(AA-): 최근 10영업일 내 데이터를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["corp_aa_1y"] = values["corp_aa_2y"] = values["corp_aa_3y"] = None
        status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = "blocked"
        effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = None
        gha_warning(f"회사채(AA-) 수집 실패: {exc}")
        traceback.print_exc()

    return values, status, effective


def fetch_foreign(foreign_target: date, ust2y_rows: Optional[list] = None):
    values: dict[str, Optional[float]] = {}
    status: dict[str, str] = {}
    effective: dict[str, Optional[str]] = {}

    # 5) SOFR
    try:
        rate = sofr.fetch_sofr_on_or_before(foreign_target)
        values["sofr"] = rate
        status["sofr"] = "ok" if rate is not None else "no_data"
        effective["sofr"] = fmt_iso(foreign_target) if rate is not None else None
        if rate is None:
            gha_warning("SOFR: 최근 10일 내 데이터를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["sofr"] = None
        status["sofr"] = "blocked"
        effective["sofr"] = None
        gha_warning(f"SOFR 수집 실패: {exc}")
        traceback.print_exc()

    # 6) 미국 2년 국채 (investing.com - 차단 위험 있음. 실패시 공란+알림만)
    try:
        rate = ust2y.fetch_ust2y_on_or_before(foreign_target, rows=ust2y_rows)
        values["ust2y"] = rate
        status["ust2y"] = "ok" if rate is not None else "no_data"
        effective["ust2y"] = fmt_iso(foreign_target) if rate is not None else None
        if rate is None:
            gha_warning("미국 2년 국채: 데이터를 찾지 못했습니다")
    except ust2y.BlockedError as exc:
        values["ust2y"] = None
        status["ust2y"] = "blocked"
        effective["ust2y"] = None
        gha_warning(f"미국 2년 국채: investing.com 접속이 차단된 것으로 보입니다 ({exc}). 값은 공란 처리합니다.")
    except Exception as exc:  # noqa: BLE001
        values["ust2y"] = None
        status["ust2y"] = "blocked"
        effective["ust2y"] = None
        gha_warning(f"미국 2년 국채 수집 실패: {exc}")
        traceback.print_exc()

    return values, status, effective


def collect_day(run_date: date, bok_rows: Optional[list] = None, ust2y_rows: Optional[list] = None):
    """run_date 하루치 9개 금리를 수집한다 (values, status, effective_date 튜플).
    bok_rows/ust2y_rows를 넘기면 해당 소스는 재요청하지 않고 넘겨받은 목록에서 찾는다
    (backfill.py처럼 여러 날짜를 연달아 수집할 때 외부 사이트 요청 횟수를 줄이기 위함).
    """
    domestic_target, foreign_target = compute_targets(run_date)
    d_values, d_status, d_effective = fetch_domestic(domestic_target, bok_rows=bok_rows)
    f_values, f_status, f_effective = fetch_foreign(foreign_target, ust2y_rows=ust2y_rows)
    values = {**d_values, **f_values}
    status = {**d_status, **f_status}
    effective = {**d_effective, **f_effective}
    return values, status, effective


def backfill_weekend(data: dict, run_date: date) -> None:
    """run_date가 월요일이면, 직전 토/일을 직전 금요일 값으로 백필한다."""
    if run_date.weekday() != 0:  # 0 = Monday
        return
    friday = run_date - timedelta(days=3)
    saturday = run_date - timedelta(days=2)
    sunday = run_date - timedelta(days=1)
    friday_iso = fmt_iso(friday)
    if friday_iso not in data["days"]:
        return
    copy_day_as_backfill(data, friday_iso, fmt_iso(saturday))
    copy_day_as_backfill(data, friday_iso, fmt_iso(sunday))


def main() -> int:
    run_date = date.today()  # GitHub Actions에서 TZ=Asia/Seoul로 실행 (workflow에서 설정)
    domestic_target, foreign_target = compute_targets(run_date)

    gha_notice(f"실행일(KST)={fmt_iso(run_date)} 국내대상일={fmt_iso(domestic_target)} 해외대상일={fmt_iso(foreign_target)}")

    values, status, effective = collect_day(run_date)

    data = load_history(HISTORY_PATH)
    upsert_day(data, fmt_iso(run_date), values, status, effective, backfilled=False)
    backfill_weekend(data, run_date)
    save_history(HISTORY_PATH, data)
    export_history_to_xlsx(data, XLSX_PATH)

    failed = [m for m, s in status.items() if s != "ok"]
    if failed:
        gha_warning(f"실패/누락된 항목: {', '.join(failed)}")

    print("완료:", values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
