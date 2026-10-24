"""Earnings event model and tooltip formatting."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EarningsEvent:
    """A single earnings announcement for a ticker.

    ``event_date`` is stored as an exchange-local naive timestamp string
    ("YYYY-MM-DD HH:MM:SS") so it aligns with the price series convention
    (yfinance history timestamps, stored naive in SQLite and converted with
    ``datetime.timestamp()``, i.e. interpreted in system-local time).
    """

    symbol: str
    event_date: str
    eps_estimate: Optional[float] = None
    reported_eps: Optional[float] = None
    surprise_pct: Optional[float] = None
    is_estimated: bool = False
    quarter: Optional[str] = None
    timing: Optional[str] = None

    @property
    def epoch(self) -> float:
        """UNIX epoch seconds using the same convention as the price series."""
        try:
            if " " in self.event_date:
                dt = datetime.strptime(self.event_date, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(self.event_date[:10], "%Y-%m-%d")
            return dt.timestamp()
        except (TypeError, ValueError):
            return float("nan")

    @property
    def date_only(self) -> str:
        return self.event_date[:10]


def format_earnings_tooltip(event: EarningsEvent, company_name: Optional[str] = None) -> str:
    """Builds the hover tooltip for an earnings marker.

    Unavailable fields are omitted entirely — never shown as zero or
    fabricated values. Falls back to a ticker + date tooltip when only the
    event date is known.
    """
    title = company_name.strip() if company_name and company_name.strip() else event.symbol
    status = "Estimated" if event.is_estimated else "Confirmed"
    lines = [
        f"{title} — Earnings",
        f"Date: {event.date_only} ({status})",
    ]

    if event.quarter:
        lines.append(f"Period: {event.quarter}")
    if event.eps_estimate is not None:
        lines.append(f"EPS Estimate: {event.eps_estimate:,.2f}")
    if event.reported_eps is not None:
        lines.append(f"Reported EPS: {event.reported_eps:,.2f}")
    if event.surprise_pct is not None:
        lines.append(f"EPS Surprise: {event.surprise_pct:+.2f}%")
    if event.timing:
        lines.append(f"Timing: {event.timing}")

    return "\n".join(lines)
