#!/usr/bin/env python3
"""
매일 실행되는 금리 수집 메인 스크립트.

실행 흐름:
1. 오늘(KST) 기준 국내/해외 대상일 계산
2. 국내 소스(BOK, CD, CP, 회사채(AA-)+국고채권) 수집 (KOFIA 3종은 공휴일 등으로 데이터가
   없으면 자동으로 하루씩 더 앞으로 이동하며 재시도)
3. 해외 소스(SOFR) 수집 ("대상일 이하 최신값" 방식으로 자체 처리)
4. data/history.json 에 "국내 대상일(domestic_target)" 기준으로 레코드 upsert.
   실행일(오늘) 자신이 아니라 실제로 조회한 데이터의 기준일을 키로 쓴다 - 이렇게 해야
   나중에 파일을 열어봤을 때 "2026-09-04" 밑에 실제 9/4일자 값이 들어있게 된다.
   (실행일을 키로 쓰면 "2026-09-07" 밑에 사실은 9/4일자 값이 들어있는 식으로 라벨과
   내용이 하루 이상 어긋나는 문제가 있었다.)
5. 주말(토/일) 백필: 오늘이 월요일이면 직전 토/일에도 오늘 수집한 값을 채움
   (토/일/월요일은 "직전 영업일" 계산이 동일하게 수렴하므로 재조회 없이 재사용 가능)
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
from sources import bok, kofia, sofr  # noqa: E402
from storage import load_history, record_run, save_history, upsert_day  # noqa: E402
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

    # 4) 회사채(AA-, 1/2/3년) + 국고채권(3년) - 한 번의 조회 결과에서 함께 얻는다
    try:
        found_date, bond_val = find_available(kofia.fetch_bond_quotes, domestic_target)
        if bond_val is not None:
            values["corp_aa_1y"] = bond_val.corp_aa_1y
            values["corp_aa_2y"] = bond_val.corp_aa_2y
            values["corp_aa_3y"] = bond_val.corp_aa_3y
            status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = "ok"
            effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = fmt_iso(found_date)

            if bond_val.treasury_3y is not None:
                values["treasury_3y"] = bond_val.treasury_3y
                status["treasury_3y"] = "ok"
                effective["treasury_3y"] = fmt_iso(found_date)
            else:
                values["treasury_3y"] = None
                status["treasury_3y"] = "no_data"
                effective["treasury_3y"] = None
                gha_warning("국고채권(3년): 조회 결과에서 해당 행을 찾지 못했습니다")
        else:
            values["corp_aa_1y"] = values["corp_aa_2y"] = values["corp_aa_3y"] = values["treasury_3y"] = None
            status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = status["treasury_3y"] = "no_data"
            effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = effective["treasury_3y"] = None
            gha_warning("회사채(AA-)/국고채권: 최근 10영업일 내 데이터를 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001
        values["corp_aa_1y"] = values["corp_aa_2y"] = values["corp_aa_3y"] = values["treasury_3y"] = None
        status["corp_aa_1y"] = status["corp_aa_2y"] = status["corp_aa_3y"] = status["treasury_3y"] = "blocked"
        effective["corp_aa_1y"] = effective["corp_aa_2y"] = effective["corp_aa_3y"] = effective["treasury_3y"] = None
        gha_warning(f"회사채(AA-)/국고채권 수집 실패: {exc}")
        traceback.print_exc()

    return values, status, effective


def fetch_foreign(foreign_target: date):
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

    return values, status, effective


def collect_for_target(domestic_target: date, foreign_target: date, bok_rows: Optional[list] = None):
    """domestic_target/foreign_target을 직접 지정해서 금리를 수집한다 (values, status,
    effective_date 튜플). backfill.py처럼 "실행일"이라는 개념 없이 특정 기준일 하나를
    바로 채우고 싶을 때 쓴다."""
    d_values, d_status, d_effective = fetch_domestic(domestic_target, bok_rows=bok_rows)
    f_values, f_status, f_effective = fetch_foreign(foreign_target)
    values = {**d_values, **f_values}
    status = {**d_status, **f_status}
    effective = {**d_effective, **f_effective}
    return values, status, effective


def collect_day(run_date: date, bok_rows: Optional[list] = None):
    """run_date에 실행했다고 가정할 때의 국내/해외 대상일을 계산해서 수집한다."""
    domestic_target, foreign_target = compute_targets(run_date)
    return collect_for_target(domestic_target, foreign_target, bok_rows=bok_rows)


def backfill_weekend(
    data: dict,
    domestic_target: date,
    values: dict[str, Optional[float]],
    status: dict[str, str],
    effective: dict[str, Optional[str]],
) -> None:
    """domestic_target이 금요일이면, 그 다음 토/일에도 같은 값을 채워 넣는다.

    국내 대상일 계산상 토요일/일요일도 그 직전 금요일과 완전히 같은 기준일로
    수렴한다 ("주말에는 새 시세가 없으므로 지난 금요일 값이 곧 주말 값이다").
    그래서 별도 조회 없이 금요일 레코드를 그대로 재사용하면 된다.
    """
    if domestic_target.weekday() != 4:  # 4 = Friday
        return
    saturday = domestic_target + timedelta(days=1)
    sunday = domestic_target + timedelta(days=2)
    upsert_day(data, fmt_iso(saturday), values, status, effective, backfilled=True)
    upsert_day(data, fmt_iso(sunday), values, status, effective, backfilled=True)


def main() -> int:
    run_date = date.today()  # GitHub Actions에서 TZ=Asia/Seoul로 실행 (workflow에서 설정)
    domestic_target, foreign_target = compute_targets(run_date)

    gha_notice(f"실행일(KST)={fmt_iso(run_date)} 국내대상일={fmt_iso(domestic_target)} 해외대상일={fmt_iso(foreign_target)}")

    values, status, effective = collect_day(run_date)

    data = load_history(HISTORY_PATH)
    upsert_day(data, fmt_iso(domestic_target), values, status, effective, backfilled=False)
    backfill_weekend(data, domestic_target, values, status, effective)
    record_run(data)
    save_history(HISTORY_PATH, data)
    export_history_to_xlsx(data, XLSX_PATH)

    failed = [m for m, s in status.items() if s != "ok"]
    if failed:
        gha_warning(f"실패/누락된 항목: {', '.join(failed)}")

    print("완료:", values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
