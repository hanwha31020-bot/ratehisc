"""
날짜/영업일 계산 유틸리티

규칙 (사용자와 합의된 내용):
- domestic_target = 실행일 기준 "전영업일" (토/일 스킵)
- foreign_target   = domestic_target 기준 "전영업일" (국내보다 한 영업일 더 이전)
  예) 실행일 9/4(금) -> 국내 9/3(목), 해외 9/2(수)
      실행일 9/7(월) -> 국내 9/4(금), 해외 9/3(목)
- 공휴일 등으로 특정 날짜에 데이터가 없으면, 하루씩 더 앞으로 이동하며 재시도한다.
  (별도의 공휴일 캘린더를 유지하지 않고, "데이터가 있는 가장 최근 영업일"을 찾는 방식)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Iterator, Optional, Tuple, TypeVar
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

T = TypeVar("T")


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=토요일, 6=일요일


def previous_business_day(d: date) -> date:
    """d의 하루 전 날짜에서 시작해, 토/일이면 계속 앞으로 이동한 첫 평일을 반환한다."""
    cur = d - timedelta(days=1)
    while is_weekend(cur):
        cur -= timedelta(days=1)
    return cur


def business_days_backwards(start: date) -> Iterator[date]:
    """start부터 시작해 과거 방향으로 평일만 순서대로 내어주는 제너레이터.
    (start 자신이 주말이면 첫 평일로 보정 후 시작)
    """
    cur = start
    while is_weekend(cur):
        cur -= timedelta(days=1)
    while True:
        yield cur
        cur -= timedelta(days=1)
        while is_weekend(cur):
            cur -= timedelta(days=1)


def find_available(
    fetch_fn: Callable[[date], Optional[T]],
    start: date,
    max_tries: int = 10,
) -> Tuple[Optional[date], Optional[T]]:
    """start부터 과거로 평일을 순회하며 fetch_fn(d)가 None이 아닌 값을 반환하는
    첫 날짜/값을 찾는다. (공휴일 등으로 데이터가 없는 날짜를 자동으로 건너뜀)
    max_tries 안에 못 찾으면 (None, None) 반환.
    """
    tried = 0
    for d in business_days_backwards(start):
        result = fetch_fn(d)
        if result is not None:
            return d, result
        tried += 1
        if tried >= max_tries:
            break
    return None, None


def business_days_range_ending(end: date, count: int) -> list[date]:
    """end(포함, 평일이어야 함)부터 과거로 평일만 count개를 모아, 오래된 날짜부터 순서대로 반환한다."""
    days: list[date] = []
    cur = end
    while len(days) < count:
        if not is_weekend(cur):
            days.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(days))


def compute_targets(run_date: date) -> Tuple[date, date]:
    """실행일 기준 (국내 대상일, 해외 대상일)을 계산한다."""
    domestic_target = previous_business_day(run_date)
    foreign_target = previous_business_day(domestic_target)
    return domestic_target, foreign_target


def fmt_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def fmt_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")
