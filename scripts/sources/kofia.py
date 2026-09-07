"""
KOFIA(금융투자협회 채권정보센터, kofiabond.or.kr) 시가평가수익률 스크래퍼

실제 데이터 조회는 WebSquare 뒷단의 단순 POST XML API로 이루어진다.
- 엔드포인트: https://kofiabond.or.kr/proframeWeb/XMLSERVICES/
- 헤드리스 브라우저 없이 requests만으로 재현 가능 (브라우저 네트워크 캡처로 확인됨)

기관코드(고정, "평가사 평균" 4개사 - 이지자산평가 제외):
  나이스피앤아이=A10002, 한국자산평가=A10003, KIS자산평가=A10004, 에프앤자산평가=A10005
평가사평균 그룹코드: A20000
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

ENDPOINT = "https://kofiabond.or.kr/proframeWeb/XMLSERVICES/"

HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://kofiabond.or.kr/websquare/websquare.html?w2xPath=/xml/main.xml",
    "Origin": "https://kofiabond.or.kr",
}

# 4개 평가사 고정 코드 (요청 바디에서 val1~val4 자리에 그대로 사용)
EVAL_COMPANIES = ["A10002", "A10003", "A10004", "A10005"]
AVG_GROUP_CODE = "A20000"


def _post(body: str, timeout: int = 15) -> str:
    resp = requests.post(ENDPOINT, headers=HEADERS, data=body.encode("utf-8"), timeout=timeout)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


# ---------------------------------------------------------------------------
# CD (91일물, "3월" 컬럼)
# ---------------------------------------------------------------------------

CD_BODY_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISCDSrtPrcSrchSO</pfmSvcName>
    <pfmFnName>listDay</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
    <BISComDspDatDTO>
    <val21>{yyyymmdd}</val21>
    <val22>{avg_code}</val22>
    <val1>{c1}</val1>
    <val2>{c2}</val2>
    <val3>{c3}</val3>
    <val4>{c4}</val4>
    <val5></val5>
</BISComDspDatDTO>
</message>
"""


def _build_common_body(template: str, yyyymmdd: str, extra: str = "") -> str:
    return template.format(
        yyyymmdd=yyyymmdd,
        avg_code=AVG_GROUP_CODE,
        c1=EVAL_COMPANIES[0],
        c2=EVAL_COMPANIES[1],
        c3=EVAL_COMPANIES[2],
        c4=EVAL_COMPANIES[3],
    )


def _parse_comdsp_rows(xml_text: str):
    root = ET.fromstring(xml_text)
    for dto in root.iter("BISComDspDatDTO"):
        row = {child.tag: (child.text or "").strip() for child in dto}
        yield row


def parse_cd_response(xml_text: str) -> Optional[float]:
    """AAA / 당일 / 4사 평균 행의 val7(3월)을 반환."""
    for row in _parse_comdsp_rows(xml_text):
        if row.get("val1") == "AAA" and row.get("val2") == "당일" and row.get("val3") == "4사 평균":
            val7 = row.get("val7")
            if val7:
                try:
                    return float(val7)
                except ValueError:
                    return None
    return None


def fetch_cd(d: date) -> Optional[float]:
    body = _build_common_body(CD_BODY_TEMPLATE, d.strftime("%Y%m%d"))
    text = _post(body)
    return parse_cd_response(text)


# ---------------------------------------------------------------------------
# CP / A1CP (1월, 3월 컬럼)
# ---------------------------------------------------------------------------

CP_BODY_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISCPSrtPrcSrchSO</pfmSvcName>
    <pfmFnName>listDay</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
    <BISComDspDatDTO>
    <val21>{yyyymmdd}</val21>
    <val22>{avg_code}</val22>
    <val23>T</val23>
    <val1>{c1}</val1>
    <val2>{c2}</val2>
    <val3>{c3}</val3>
    <val4>{c4}</val4>
    <val5></val5>
</BISComDspDatDTO>
</message>
"""


@dataclass
class CpRates:
    one_month: float
    three_month: float


def parse_cp_response(xml_text: str) -> Optional[CpRates]:
    """A1 / 당일 / 4사 평균 행의 val6(1월), val7(3월)을 반환."""
    for row in _parse_comdsp_rows(xml_text):
        if row.get("val1") == "A1" and row.get("val2") == "당일" and row.get("val3") == "4사 평균":
            v6, v7 = row.get("val6"), row.get("val7")
            if v6 and v7:
                try:
                    return CpRates(one_month=float(v6), three_month=float(v7))
                except ValueError:
                    return None
    return None


def fetch_cp(d: date) -> Optional[CpRates]:
    body = _build_common_body(CP_BODY_TEMPLATE, d.strftime("%Y%m%d"))
    text = _post(body)
    return parse_cp_response(text)


# ---------------------------------------------------------------------------
# 채권시가평가수익률 (회사채 I(공모사채) / 무보증 / AA-, 1/2/3년)
# ---------------------------------------------------------------------------

BOND_BODY_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISBndSrtPrcSrchSO</pfmSvcName>
    <pfmFnName>selectDay</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
<BISBndSrtPrcDayDTO><standardDt>{yyyymmdd}</standardDt><reportCompCd>{avg_code}</reportCompCd><applyGbCd>C00</applyGbCd><val1>{c1}</val1><val2>{c2}</val2><val3>{c3}</val3><val4>{c4}</val4><val5></val5></BISBndSrtPrcDayDTO></message>
"""


@dataclass
class CorpBondRates:
    y1: float
    y2: float
    y3: float


def parse_bond_response(xml_text: str) -> Optional[CorpBondRates]:
    """largeCategoryMrk=회사채 I(공모사채), typeNmMrk=무보증, creditRnkMrk=AA- 행의
    val4(1년), val6(2년), val8(3년)을 반환."""
    root = ET.fromstring(xml_text)
    for dto in root.iter("BISBndSrtPrcDayDTO"):
        row = {child.tag: (child.text or "").strip() for child in dto}
        if (
            row.get("largeCategoryMrk") == "회사채 I(공모사채)"
            and row.get("typeNmMrk") == "무보증"
            and row.get("creditRnkMrk") == "AA-"
        ):
            v4, v6, v8 = row.get("val4"), row.get("val6"), row.get("val8")
            if v4 and v6 and v8:
                try:
                    return CorpBondRates(y1=float(v4), y2=float(v6), y3=float(v8))
                except ValueError:
                    return None
    return None


def fetch_corp_bond(d: date) -> Optional[CorpBondRates]:
    body = _build_common_body(BOND_BODY_TEMPLATE, d.strftime("%Y%m%d"))
    text = _post(body)
    return parse_bond_response(text)


if __name__ == "__main__":
    today = date.today()
    print("CD:", fetch_cd(today))
    print("CP:", fetch_cp(today))
    print("Bond:", fetch_corp_bond(today))
