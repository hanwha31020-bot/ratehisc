"""
한국은행 기준금리 스크래퍼

https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643
페이지는 순수 서버사이드 렌더링 HTML이라 requests + BeautifulSoup 만으로 처리 가능.
<caption>한국은행 기준금리 추이</caption> 표에서 가장 최근(맨 위) 행의 금리를 가져온다.
(기준금리는 금통위가 있을 때만 바뀌므로, 매일 조회해도 최신값은 항상 표의 첫 데이터 행이다.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

URL = "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bok.or.kr/",
}


@dataclass
class BokBaseRate:
    effective_date: date
    rate: float


def _parse_table(html: str) -> Optional[BokBaseRate]:
    soup = BeautifulSoup(html, "html.parser")

    target_table = None
    for table in soup.find_all("table"):
        caption = table.find("caption")
        if caption and "기준금리 추이" in caption.get_text():
            target_table = table
            break
    if target_table is None:
        # caption을 못 찾으면, "변경일자"/"기준금리" 헤더를 가진 표를 fallback으로 탐색
        for table in soup.find_all("table"):
            header_text = table.get_text()
            if "변경일자" in header_text and "기준금리" in header_text:
                target_table = table
                break
    if target_table is None:
        return None

    rows = target_table.find_all("tr")
    last_year = None
    for tr in rows:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c != ""]
        if not cells:
            continue
        # 데이터 행 후보: 연도(4자리 숫자) / "08월 27일" 형태 / 금리(숫자) 조합
        year_val = None
        md_val = None
        rate_val = None
        for c in cells:
            if re.fullmatch(r"(19|20)\d{2}", c):
                year_val = int(c)
            elif re.fullmatch(r"\d{1,2}월\s*\d{1,2}일", c):
                md_val = c
            elif re.fullmatch(r"\d+(\.\d+)?", c):
                rate_val = float(c)

        if md_val is None or rate_val is None:
            continue
        if year_val is not None:
            last_year = year_val
        if last_year is None:
            continue

        m = re.match(r"(\d{1,2})월\s*(\d{1,2})일", md_val)
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        try:
            eff_date = date(last_year, month, day)
        except ValueError:
            continue

        # 표는 최신순으로 정렬되어 있으므로 첫 번째로 파싱에 성공한 행이 최신값이다.
        return BokBaseRate(effective_date=eff_date, rate=rate_val)

    return None


def fetch_latest_base_rate(session: Optional[requests.Session] = None, timeout: int = 15) -> Optional[BokBaseRate]:
    sess = session or requests
    resp = sess.get(URL, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return _parse_table(resp.text)


if __name__ == "__main__":
    result = fetch_latest_base_rate()
    print(result)
