"""
SOFR (Secured Overnight Financing Rate) - 뉴욕 연방준비은행 공식 API

https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=...&endDate=...
- 인증/차단 없는 완전 무료 공개 API.
- 대상일 X의 SOFR는 "다음 미국 영업일 아침"에야 공시된다. 그래서 대상일 값이 없는 데는
  두 가지 전혀 다른 이유가 있다.
    (a) 대상일이 미국 휴일/주말이라 애초에 공시되지 않는 날 -> 직전 공시일 값을 쓰는 게 맞다.
    (b) 대상일 값이 아직 발표 전 -> 직전 공시일 값을 쓰면 안 된다 (다른 날 값이 대상일
        값인 것처럼 저장되므로). 값을 비워두고("pending") 나중에 발표되면 채운다.
  resolve_sofr()가 이 둘을 구분한다. 대상일보다 나중 날짜의 값이 이미 공시돼 있으면
  대상일은 (a)가 확실하고, 아니면 미국 휴일 달력(is_us_business_day)으로 판단한다.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

import requests

BASE_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

LOOKBACK_DAYS = 10


def fetch_sofr_series(start: date, end: date, timeout: int = 15) -> dict[date, float]:
    """start~end(포함) 범위에서 실제로 공시된 {기준일: SOFR(%)}를 돌려준다.
    end는 미래 날짜여도 된다 (공시된 날짜까지만 돌아온다)."""
    params = {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    series: dict[date, float] = {}
    for row in resp.json().get("refRates") or []:
        eff = row.get("effectiveDate")
        rate = row.get("percentRate")
        if eff and rate is not None:
            series[date.fromisoformat(eff)] = float(rate)
    return series


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    first += timedelta(days=(weekday - first.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date, saturday_to_friday: bool = False) -> date:
    """일요일 휴일은 월요일에 쉰다. 토요일 휴일은 독립기념일/크리스마스만 금요일에 쉰다
    (2026-07-03은 미공시, 2023-11-10(재향군인의 날이 토요일)은 정상 공시 - 실제 이력 확인)."""
    if d.weekday() == 5 and saturday_to_friday:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def _us_holidays(year: int) -> frozenset[date]:
    """뉴욕 연은이 SOFR를 공시하지 않는 평일 (미국 연방 공휴일 + 성금요일).
    2026년 실제 공시 이력과 대조해 확인했다 (MLK, 대통령의 날, 성금요일, 메모리얼데이,
    6/19, 7/3, 노동절). 달력이 틀려도 resolve_sofr가 "나중 날짜 값이 이미 공시됨"으로
    보정하므로, 틀린 경우에도 값이 영구히 비는 일은 없고 하루 늦게 채워질 뿐이다."""
    may_31 = date(year, 5, 31)
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # MLK (1월 셋째 월요일)
        _nth_weekday(year, 2, 0, 3),  # 대통령의 날 (2월 셋째 월요일)
        _easter(year) - timedelta(days=2),  # 성금요일
        may_31 - timedelta(days=may_31.weekday()),  # 메모리얼데이 (5월 마지막 월요일)
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4), saturday_to_friday=True),
        _nth_weekday(year, 9, 0, 1),  # 노동절 (9월 첫째 월요일)
        _nth_weekday(year, 10, 0, 2),  # 컬럼버스데이 (10월 둘째 월요일)
        _observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),  # 추수감사절 (11월 넷째 목요일)
        _observed(date(year, 12, 25), saturday_to_friday=True),
    }
    return frozenset(holidays)


def is_us_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _us_holidays(d.year)


def _has_us_business_day(after: date, upto: date) -> bool:
    """(after, upto] 구간에 미국 영업일이 하나라도 있는가."""
    cur = after + timedelta(days=1)
    while cur <= upto:
        if is_us_business_day(cur):
            return True
        cur += timedelta(days=1)
    return False


def resolve_sofr(series: dict[date, float], target: date) -> tuple[Optional[float], str, Optional[date]]:
    """target(해외 대상일)의 SOFR를 (값, status, 실제 기준일)로 돌려준다.

    status: "ok" - 값이 있음 (target 당일 값이거나, target이 미공시일이라 직전 공시일 값)
            "pending" - target 값이 아직 발표 전 (값 None)
            "no_data" - 조회 결과가 비어 있거나 target 이전 값이 없음 (값 None)
    돌려주는 기준일은 실제로 그 값이 속한 날짜다 (target이 아닐 수 있다).
    """
    if target in series:
        return series[target], "ok", target
    earlier = [d for d in series if d < target]
    if not earlier:
        return None, "no_data", None
    latest = max(earlier)
    published_after = any(d > target for d in series)
    if not published_after and _has_us_business_day(latest, target):
        return None, "pending", None
    return series[latest], "ok", latest


if __name__ == "__main__":
    today = date.today()
    series = fetch_sofr_series(today - timedelta(days=LOOKBACK_DAYS), today)
    print(resolve_sofr(series, today))
