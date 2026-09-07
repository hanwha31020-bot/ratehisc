"""
미국 2년 국채 수익률 - investing.com historical data 페이지에서 수집

https://kr.investing.com/rates-bonds/u.s.-2-year-bond-yield-historical-data
- Cloudflare 봇 차단이 걸려있는 사이트라 GitHub Actions 등 클라우드 서버에서
  직접 요청 시 가끔 차단(403/캡차)될 수 있음 (사용자와 합의: 실패 시 값은 공란 처리 + 알림만).
- 페이지의 __NEXT_DATA__ 스크립트 태그 안에 historicalDataStore.historicalData.data 로
  날짜별 종가(last_closeRaw)가 그대로 내려오므로, 별도 API 호출/브라우저 렌더링 없이
  이 JSON만 파싱하면 된다.
- "휴장일에도 값이 나오는" 문제 방지를 위해, 미국 재무부(treasury.gov) 공식 일별 데이터가
  존재하는 날짜인지 교차 검증한다 (재무부 값 자체를 사용하는 것이 아니라, "그 날짜가 실제
  미국 채권시장 개장일이었는지"만 확인하는 용도).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

PAGE_URL = "https://kr.investing.com/rates-bonds/u.s.-2-year-bond-yield-historical-data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://kr.investing.com/",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


class BlockedError(RuntimeError):
    """investing.com 접속이 차단(Cloudflare 등)된 것으로 판단될 때 발생."""


@dataclass
class HistoricalRow:
    d: date
    close: float


def _extract_rows(html: str) -> list[HistoricalRow]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise BlockedError("__NEXT_DATA__ 스크립트를 찾지 못했습니다 (Cloudflare 차단 의심)")
    try:
        payload = json.loads(m.group(1))
        raw_rows = payload["props"]["pageProps"]["state"]["historicalDataStore"]["historicalData"]["data"]
    except (KeyError, json.JSONDecodeError) as exc:
        raise BlockedError(f"historicalData 파싱 실패: {exc}") from exc

    rows: list[HistoricalRow] = []
    for r in raw_rows:
        ts = r.get("rowDateTimestamp")  # e.g. "2026-09-04T00:00:00Z"
        close_raw = r.get("last_closeRaw")
        if not ts or close_raw is None:
            continue
        try:
            row_date = date.fromisoformat(ts[:10])
            rows.append(HistoricalRow(d=row_date, close=float(close_raw)))
        except (ValueError, TypeError):
            continue
    return rows


def fetch_historical_rows(timeout: int = 20) -> list[HistoricalRow]:
    resp = requests.get(PAGE_URL, headers=HEADERS, timeout=timeout)
    if resp.status_code != 200:
        raise BlockedError(f"HTTP {resp.status_code}")
    resp.encoding = "utf-8"
    return _extract_rows(resp.text)


def _treasury_trading_dates(year: int, timeout: int = 15) -> set[date]:
    """미국 재무부 공식 CSV에서 해당 연도의 실제 거래일(공시일) 목록만 가져온다.
    (수치 자체는 쓰지 않고, "이 날짜가 실제 개장일이었는가" 교차검증 용도로만 사용)
    """
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
        f"&field_tdr_date_value={year}&page&_format=csv"
    )
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    dates = set()
    for line in resp.text.splitlines()[1:]:
        if not line.strip():
            continue
        date_str = line.split(",")[0].strip('"')
        try:
            m, d, y = date_str.split("/")
            dates.add(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return dates


def fetch_ust2y_on_or_before(
    target: date,
    rows: Optional[list[HistoricalRow]] = None,
    verify_with_treasury: bool = True,
) -> Optional[float]:
    """target 이하 날짜 중 가장 최근의 "진짜 개장일" 종가를 반환한다.
    investing.com 접속 자체가 막히면 BlockedError를 발생시킨다 (호출부에서 공란+알림 처리).

    rows를 넘기면 investing.com을 다시 조회하지 않고 그 목록을 사용한다.
    (백필처럼 여러 날짜를 연달아 조회할 때 Cloudflare 차단 위험을 줄이기 위함)
    """
    if rows is None:
        rows = fetch_historical_rows()
    rows_sorted = sorted(rows, key=lambda r: r.d, reverse=True)
    candidates = [r for r in rows_sorted if r.d <= target]
    if not candidates:
        return None

    if not verify_with_treasury:
        return candidates[0].close

    valid_years = {r.d.year for r in candidates[:5]}
    treasury_dates: set[date] = set()
    for y in valid_years:
        try:
            treasury_dates |= _treasury_trading_dates(y)
        except requests.RequestException:
            # 재무부 교차검증에 실패하면 검증 없이 investing.com 최신값을 그대로 사용
            return candidates[0].close

    for row in candidates:
        if row.d in treasury_dates:
            return row.close
    # 교차검증에 매칭되는 날짜가 없으면(드문 경우) 안전하게 첫 값을 사용
    return candidates[0].close


if __name__ == "__main__":
    print(fetch_ust2y_on_or_before(date.today()))
