import unittest

from app.models.ticker import TickerSummary
from app.ui.ticker_list import (
    SORT_BY_DATE,
    SORT_BY_DATE_ASC,
    SORT_BY_DATE_DESC,
    SORT_BY_NAME,
    SORT_BY_PERF,
    SORT_BY_PERF_ASC,
    SORT_BY_PERF_DESC,
    SORT_BY_PRICE,
    SORT_BY_PRICE_ASC,
    SORT_BY_PRICE_DESC,
    SORT_BY_TICKER,
    SORT_CRITERIA,
    sort_ticker_summaries,
)


def make(symbol: str, added_at=None, company_name=None, price=None, pct_change=None) -> TickerSummary:
    return TickerSummary(
        symbol=symbol,
        company_name=company_name if company_name is not None else symbol,
        added_at=added_at,
        current_price=price,
        pct_change=pct_change,
    )


class TestTickerListSorting(unittest.TestCase):
    def test_sort_criteria_constants(self):
        self.assertEqual(
            SORT_CRITERIA,
            (SORT_BY_TICKER, SORT_BY_DATE, SORT_BY_NAME, SORT_BY_PRICE, SORT_BY_PERF),
        )

    def test_sort_by_ticker_ascending(self):
        summaries = [make("TSLA"), make("AAPL"), make("MSFT")]
        ordered = sort_ticker_summaries(summaries, SORT_BY_TICKER, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT", "TSLA"])

    def test_sort_by_ticker_descending(self):
        summaries = [make("TSLA"), make("AAPL"), make("MSFT")]
        ordered = sort_ticker_summaries(summaries, SORT_BY_TICKER, ascending=False)
        self.assertEqual([s.symbol for s in ordered], ["TSLA", "MSFT", "AAPL"])

    def test_sort_by_date_ascending(self):
        summaries = [
            make("TSLA", "2026-01-05 10:00:00"),
            make("AAPL", "2024-03-11 09:30:00"),
            make("MSFT", "2025-07-01 16:45:00"),
        ]
        ordered = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT", "TSLA"])

    def test_sort_by_date_descending(self):
        summaries = [
            make("TSLA", "2026-01-05 10:00:00"),
            make("AAPL", "2024-03-11 09:30:00"),
            make("MSFT", "2025-07-01 16:45:00"),
        ]
        ordered = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=False)
        self.assertEqual([s.symbol for s in ordered], ["TSLA", "MSFT", "AAPL"])

    def test_date_sort_keeps_symbol_order_for_equal_dates(self):
        summaries = [make("MSFT", "2025-01-01 00:00:00"), make("AAPL", "2025-01-01 00:00:00")]
        ascending = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=True)
        descending = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=False)
        self.assertEqual([s.symbol for s in ascending], ["AAPL", "MSFT"])
        self.assertEqual([s.symbol for s in descending], ["AAPL", "MSFT"])

    def test_missing_dates_sort_first_when_ascending(self):
        summaries = [make("AAPL"), make("TSLA", "2024-01-01 00:00:00")]
        ordered = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "TSLA"])

        reverse = sort_ticker_summaries(summaries, SORT_BY_DATE, ascending=False)
        self.assertEqual([s.symbol for s in reverse], ["TSLA", "AAPL"])

    def test_sort_by_company_name_ascending(self):
        summaries = [
            make("TSLA", company_name="Tesla"),
            make("AAPL", company_name="Apple"),
            make("MSFT", company_name="Microsoft"),
        ]
        ordered = sort_ticker_summaries(summaries, SORT_BY_NAME, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT", "TSLA"])

    def test_sort_by_company_name_descending(self):
        summaries = [
            make("TSLA", company_name="Tesla"),
            make("AAPL", company_name="Apple"),
            make("MSFT", company_name="Microsoft"),
        ]
        ordered = sort_ticker_summaries(summaries, SORT_BY_NAME, ascending=False)
        self.assertEqual([s.symbol for s in ordered], ["TSLA", "MSFT", "AAPL"])

    def test_sort_by_company_name_is_case_insensitive(self):
        summaries = [make("B", company_name="apple"), make("A", company_name="Banana")]
        ordered = sort_ticker_summaries(summaries, SORT_BY_NAME, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["B", "A"])

        reverse = sort_ticker_summaries(summaries, SORT_BY_NAME, ascending=False)
        self.assertEqual([s.symbol for s in reverse], ["A", "B"])

    def test_sort_by_price_ascending(self):
        summaries = [make("TSLA", price=250.0), make("AAPL", price=10.0), make("MSFT", price=100.0)]
        ordered = sort_ticker_summaries(summaries, SORT_BY_PRICE, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT", "TSLA"])

    def test_sort_by_price_descending(self):
        summaries = [make("TSLA", price=250.0), make("AAPL", price=10.0), make("MSFT", price=100.0)]
        ordered = sort_ticker_summaries(summaries, SORT_BY_PRICE, ascending=False)
        self.assertEqual([s.symbol for s in ordered], ["TSLA", "MSFT", "AAPL"])

    def test_missing_prices_sort_last_for_both_directions(self):
        summaries = [make("AAPL"), make("TSLA", price=250.0), make("MSFT", price=100.0)]
        ascending = sort_ticker_summaries(summaries, SORT_BY_PRICE, ascending=True)
        descending = sort_ticker_summaries(summaries, SORT_BY_PRICE, ascending=False)
        self.assertEqual([s.symbol for s in ascending], ["MSFT", "TSLA", "AAPL"])
        self.assertEqual([s.symbol for s in descending], ["TSLA", "MSFT", "AAPL"])

    def test_sort_by_daily_performance_ascending(self):
        summaries = [make("TSLA", pct_change=1.5), make("AAPL", pct_change=-3.0), make("MSFT", pct_change=0.2)]
        ordered = sort_ticker_summaries(summaries, SORT_BY_PERF, ascending=True)
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT", "TSLA"])

    def test_sort_by_daily_performance_descending(self):
        summaries = [make("TSLA", pct_change=1.5), make("AAPL", pct_change=-3.0), make("MSFT", pct_change=0.2)]
        ordered = sort_ticker_summaries(summaries, SORT_BY_PERF, ascending=False)
        self.assertEqual([s.symbol for s in ordered], ["TSLA", "MSFT", "AAPL"])

    def test_missing_performance_sorts_last_for_both_directions(self):
        summaries = [make("AAPL"), make("TSLA", pct_change=1.5), make("MSFT", pct_change=-2.0)]
        ascending = sort_ticker_summaries(summaries, SORT_BY_PERF, ascending=True)
        descending = sort_ticker_summaries(summaries, SORT_BY_PERF, ascending=False)
        self.assertEqual([s.symbol for s in ascending], ["MSFT", "TSLA", "AAPL"])
        self.assertEqual([s.symbol for s in descending], ["TSLA", "MSFT", "AAPL"])

    def test_equal_values_keep_symbol_order(self):
        summaries = [make("MSFT", price=100.0, pct_change=1.0), make("AAPL", price=100.0, pct_change=1.0)]
        by_price = sort_ticker_summaries(summaries, SORT_BY_PRICE, ascending=False)
        by_perf = sort_ticker_summaries(summaries, SORT_BY_PERF, ascending=False)
        self.assertEqual([s.symbol for s in by_price], ["AAPL", "MSFT"])
        self.assertEqual([s.symbol for s in by_perf], ["AAPL", "MSFT"])

    def test_legacy_mode_strings_compatibility(self):
        summaries = [make("TSLA", price=250.0), make("AAPL", price=10.0), make("MSFT", price=100.0)]
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(summaries, SORT_BY_PRICE_ASC)],
            ["AAPL", "MSFT", "TSLA"],
        )
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(summaries, SORT_BY_PRICE_DESC)],
            ["TSLA", "MSFT", "AAPL"],
        )

        date_summaries = [
            make("TSLA", "2026-01-05 10:00:00"),
            make("AAPL", "2024-03-11 09:30:00"),
        ]
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(date_summaries, SORT_BY_DATE_ASC)],
            ["AAPL", "TSLA"],
        )
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(date_summaries, SORT_BY_DATE_DESC)],
            ["TSLA", "AAPL"],
        )

        perf_summaries = [make("TSLA", pct_change=1.5), make("AAPL", pct_change=-3.0)]
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(perf_summaries, SORT_BY_PERF_ASC)],
            ["AAPL", "TSLA"],
        )
        self.assertEqual(
            [s.symbol for s in sort_ticker_summaries(perf_summaries, SORT_BY_PERF_DESC)],
            ["TSLA", "AAPL"],
        )

    def test_unknown_mode_falls_back_to_ticker_sort(self):
        summaries = [make("MSFT"), make("AAPL")]
        ordered = sort_ticker_summaries(summaries, "not-a-mode")
        self.assertEqual([s.symbol for s in ordered], ["AAPL", "MSFT"])

    def test_sorting_does_not_mutate_input(self):
        summaries = [make("MSFT"), make("AAPL")]
        sort_ticker_summaries(summaries, SORT_BY_TICKER, ascending=True)
        self.assertEqual([s.symbol for s in summaries], ["MSFT", "AAPL"])


if __name__ == "__main__":
    unittest.main()
