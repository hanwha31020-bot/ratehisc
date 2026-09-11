"""
네트워크 없이 돌아가는 단위 테스트 모음.
실행: (저장소 루트에서) python -m unittest discover -s scripts/tests -v
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from date_utils import (
    business_days_range_ending,
    compute_targets,
    previous_business_day,
    find_available,
)
from sources.kofia import parse_cd_response, parse_cp_response, parse_bond_response
from sources import bok
from storage import upsert_day
from fetch_rates import backfill_weekend

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "sources" / "tests"


class DateLogicTests(unittest.TestCase):
    def test_previous_business_day_skips_weekend(self):
        self.assertEqual(previous_business_day(date(2026, 9, 7)), date(2026, 9, 4))  # Mon -> Fri

    def test_compute_targets_examples_from_user(self):
        # 실행일 9/4(금) -> 국내 9/3(목), 해외 9/2(수)
        d, f = compute_targets(date(2026, 9, 4))
        self.assertEqual(d, date(2026, 9, 3))
        self.assertEqual(f, date(2026, 9, 2))
        # 실행일 9/7(월) -> 국내 9/4(금), 해외 9/3(목)
        d, f = compute_targets(date(2026, 9, 7))
        self.assertEqual(d, date(2026, 9, 4))
        self.assertEqual(f, date(2026, 9, 3))

    def test_find_available_skips_holiday(self):
        # 9/4에 데이터가 없다고 가정하면(공휴일), 9/3으로 자동으로 넘어가야 한다.
        data = {date(2026, 9, 3): 1.23}

        def fetch(d):
            return data.get(d)

        found_date, val = find_available(fetch, date(2026, 9, 4))
        self.assertEqual(found_date, date(2026, 9, 3))
        self.assertEqual(val, 1.23)

    def test_business_days_range_ending(self):
        # 2026-09-04(금)부터 과거로 평일 5개 = 8/31(월)~9/4(금), 오래된 순.
        days = business_days_range_ending(date(2026, 9, 4), 5)
        self.assertEqual(
            days,
            [
                date(2026, 8, 31),
                date(2026, 9, 1),
                date(2026, 9, 2),
                date(2026, 9, 3),
                date(2026, 9, 4),
            ],
        )


class BokParsingTests(unittest.TestCase):
    def test_parse_all_rows_and_base_rate_on(self):
        html = (FIXTURE_DIR / "fixture_bok.html").read_text(encoding="utf-8")
        rows = bok._parse_all_rows(html)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].effective_date, date(2026, 8, 27))
        self.assertEqual(rows[0].rate, 3.00)

        # 8/27 변경 "직전" 날짜를 조회하면 그 이전 금리(7/16, 2.75)가 나와야 한다.
        result = bok.base_rate_on(rows, date(2026, 8, 26))
        self.assertEqual(result.rate, 2.75)
        self.assertEqual(result.effective_date, date(2026, 7, 16))

        # 변경일 당일부터는 새 금리가 적용된다.
        result = bok.base_rate_on(rows, date(2026, 8, 27))
        self.assertEqual(result.rate, 3.00)

        # 표에 있는 가장 오래된 변경일보다 더 과거를 조회하면 None.
        self.assertIsNone(bok.base_rate_on(rows, date(2020, 1, 1)))


class KofiaParsingTests(unittest.TestCase):
    def test_parse_cd(self):
        xml_text = (FIXTURE_DIR / "fixture_cd.xml").read_text(encoding="utf-8")
        self.assertEqual(parse_cd_response(xml_text), 3.12)

    def test_parse_cp(self):
        xml_text = (FIXTURE_DIR / "fixture_cp.xml").read_text(encoding="utf-8")
        result = parse_cp_response(xml_text)
        self.assertEqual(result.one_month, 3.16)
        self.assertEqual(result.three_month, 3.24)

    def test_parse_bond(self):
        xml_text = (FIXTURE_DIR / "fixture_bond.xml").read_text(encoding="utf-8")
        result = parse_bond_response(xml_text)
        self.assertEqual(result.corp_aa_1y, 4.048)
        self.assertEqual(result.corp_aa_2y, 4.411)
        self.assertEqual(result.corp_aa_3y, 4.558)
        # 국채/국고채권/양곡,외평,재정 행의 3년(val8)도 같은 응답에서 함께 나와야 한다.
        self.assertEqual(result.treasury_3y, 3.885)


class BackfillTests(unittest.TestCase):
    def test_weekend_backfill_merges_fridays_domestic_with_mondays_sofr(self):
        # SOFR는 뉴욕 연은이 대상일의 다음 영업일에야 공시된다. 금요일 레코드가
        # 만들어지는 시점(그 전 월요일 실행)엔 금요일자 SOFR가 아직 발표 전이라
        # 목요일자 값이 대신 들어가 있고, 그 다음 월요일이 되어서야 진짜 금요일자
        # SOFR를 알 수 있다. 그래서 주말은 "금요일의 국내값 + 월요일의 SOFR"를
        # 섞어서 채워야 한다 - 어느 한쪽을 통째로 복사하면 안 된다.
        data = {"metrics": [], "days": {}}
        friday_values = {"bok_base": 3.0, "cd91": 2.93, "sofr": 3.64}  # sofr: 아직 목요일자
        friday_status = {"bok_base": "ok", "cd91": "ok", "sofr": "ok"}
        friday_effective = {"bok_base": "2026-08-27", "cd91": "2026-09-04", "sofr": "2026-09-03"}
        upsert_day(data, "2026-09-04", friday_values, friday_status, friday_effective)  # Friday

        monday_values = {"bok_base": 3.0, "cd91": 2.95, "sofr": 3.65}  # cd91: 월요일 자체 종가
        monday_status = {"bok_base": "ok", "cd91": "ok", "sofr": "ok"}
        monday_effective = {"bok_base": "2026-08-27", "cd91": "2026-09-07", "sofr": "2026-09-04"}
        upsert_day(data, "2026-09-07", monday_values, monday_status, monday_effective)  # Monday
        backfill_weekend(data, date(2026, 9, 7), monday_values, monday_status, monday_effective)

        for weekend_date in ("2026-09-05", "2026-09-06"):
            self.assertIn(weekend_date, data["days"])
            rec = data["days"][weekend_date]
            self.assertTrue(rec["backfilled"])
            # 국내는 금요일 값 그대로
            self.assertEqual(rec["values"]["cd91"], 2.93)
            self.assertEqual(rec["effective_date"]["cd91"], "2026-09-04")
            # 해외(SOFR)는 월요일 레코드 값으로 대체
            self.assertEqual(rec["values"]["sofr"], 3.65)
            self.assertEqual(rec["effective_date"]["sofr"], "2026-09-04")

    def test_weekend_backfill_falls_back_to_monday_values_when_friday_missing(self):
        # 금요일 레코드가 아직 없는 드문 경우엔 월요일 값을 통째로 쓴다.
        data = {"metrics": [], "days": {}}
        monday_values = {"bok_base": 3.0, "sofr": 3.65}
        monday_status = {"bok_base": "ok", "sofr": "ok"}
        monday_effective = {"bok_base": "2026-08-27", "sofr": "2026-09-04"}
        upsert_day(data, "2026-09-07", monday_values, monday_status, monday_effective)
        backfill_weekend(data, date(2026, 9, 7), monday_values, monday_status, monday_effective)
        self.assertEqual(data["days"]["2026-09-05"]["values"], monday_values)
        self.assertEqual(data["days"]["2026-09-06"]["values"], monday_values)

    def test_weekend_backfill_noop_on_non_monday(self):
        data = {"metrics": [], "days": {}}
        values = {"bok_base": 3.0}
        upsert_day(data, "2026-09-04", values, {"bok_base": "ok"}, {"bok_base": "2026-08-27"})
        backfill_weekend(data, date(2026, 9, 4), values, {"bok_base": "ok"}, {"bok_base": "2026-08-27"})  # Friday
        self.assertEqual(len(data["days"]), 1)


if __name__ == "__main__":
    unittest.main()
