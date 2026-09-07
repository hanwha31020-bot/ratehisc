"""
SOFR (Secured Overnight Financing Rate) - 뉴욕 연방준비은행 공식 API

https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=...&endDate=...
- 인증/차단 없는 완전 무료 공개 API.
- 특정 날짜에 데이터가 없으면(주말/미국 공휴일) 그냥 결과에서 빠지므로,
  대상일 이전 10일 범위로 조회해서 "대상일 이하 날짜 중 가장 최근 값"을 사용하면
  별도의 미국 공휴일 캘린더 없이 자동으로 처리된다.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import requests

BASE_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def fetch_sofr_on_or_before(target: date, lookback_days: int = 10, timeout: int = 15) -> Optional[float]:
    start = target - timedelta(days=lookback_days)
    params = {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": target.strftime("%Y-%m-%d"),
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    rates = data.get("refRates") or []
    if not rates:
        return None
    # 날짜 내림차순으로 오는 것을 확인했지만, 안전하게 직접 정렬해서 가장 최근 값을 사용한다.
    rates_sorted = sorted(rates, key=lambda r: r.get("effectiveDate", ""), reverse=True)
    best = rates_sorted[0]
    rate = best.get("percentRate")
    return float(rate) if rate is not None else None


if __name__ == "__main__":
    print(fetch_sofr_on_or_before(date.today()))
