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
from sources.ust2y import _extract_rows, fetch_ust2y_on_or_before
from sources import ust2y as ust2y_mod
from sources import bok
from storage import upsert_day, copy_day_as_backfill
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
        self.assertEqual(result.y1, 4.048)
        self.assertEqual(result.y2, 4.411)
        self.assertEqual(result.y3, 4.558)


class Ust2yParsingTests(unittest.TestCase):
    def test_extract_rows(self):
        html = (FIXTURE_DIR / "fixture_investing.html").read_text(encoding="utf-8")
        rows = _extract_rows(html)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].d, date(2026, 9, 4))

    def test_on_or_before_with_holiday_contamination(self):
        html = (FIXTURE_DIR / "fixture_investing.html").read_text(encoding="utf-8")
        rows = _extract_rows(html)
        original_fetch = ust2y_mod.fetch_historical_rows
        original_treasury = ust2y_mod._treasury_trading_dates
        ust2y_mod.fetch_historical_rows = lambda timeout=20: rows
        ust2y_mod._treasury_trading_dates = lambda year, timeout=15: {
            date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
        }
        try:
            # 9/4는 "가짜 휴장일" 취급 -> 9/3으로 폴백해야 한다.
            result = fetch_ust2y_on_or_before(date(2026, 9, 4), verify_with_treasury=True)
            self.assertAlmostEqual(result, 4.33400011062622)
        finally:
            ust2y_mod.fetch_historical_rows = original_fetch
            ust2y_mod._treasury_trading_dates = original_treasury


class BackfillTests(unittest.TestCase):
    def test_weekend_backfill_from_friday(self):
        data = {"metrics": [], "days": {}}
        upsert_day(data, "2026-09-04", {"bok_base": 3.0}, {"bok_base": "ok"}, {"bok_base": "2026-08-27"})
        backfill_weekend(data, date(2026, 9, 7))  # Monday
        self.assertIn("2026-09-05", data["days"])
        self.assertIn("2026-09-06", data["days"])
        self.assertTrue(data["days"]["2026-09-05"]["backfilled"])
        self.assertEqual(data["days"]["2026-09-05"]["values"]["bok_base"], 3.0)

    def test_weekend_backfill_noop_on_non_monday(self):
        data = {"metrics": [], "days": {}}
        upsert_day(data, "2026-09-08", {"bok_base": 3.0}, {"bok_base": "ok"}, {"bok_base": "2026-09-07"})
        backfill_weekend(data, date(2026, 9, 8))  # Tuesday
        self.assertEqual(len(data["days"]), 1)


if __name__ == "__main__":
    unittest.main()
