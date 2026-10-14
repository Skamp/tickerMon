"""Currency symbol lookup and price formatting helpers."""

from typing import Dict, Optional

CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "JPY": "¥",
    "GBP": "£",
    "CNY": "¥",
    "HKD": "HK$",
    "SGD": "S$",
    "TWD": "NT$",
    "CAD": "C$",
    "AUD": "A$",
    "NZD": "NZ$",
    "INR": "₹",
    "KRW": "₩",
    "BRL": "R$",
    "MXN": "MX$",
    "ZAR": "R",
    "TRY": "₺",
    "RUB": "₽",
    "PLN": "zł",
    "CZK": "Kč",
    "HUF": "Ft",
    "ILS": "₪",
    "THB": "฿",
    "MYR": "RM",
    "IDR": "Rp",
    "PHP": "₱",
    "VND": "₫",
    "NGN": "₦",
    "UAH": "₴",
    "KZT": "₸",
    "CLP": "CLP$",
    "ARS": "AR$",
    "COP": "COP$",
    "PEN": "S/",
    "SEK": "kr ",
    "NOK": "kr ",
    "DKK": "kr ",
    "ISK": "kr ",
}

ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND", "CLP", "ISK"}


def get_currency_symbol(currency_code: Optional[str]) -> str:
    """Returns the display symbol for an ISO 4217 code, defaulting to USD."""
    code = (currency_code or "USD").upper().strip()
    return CURRENCY_SYMBOLS.get(code, f"{code} ")


def format_price(
    value: Optional[float],
    currency_code: Optional[str] = None,
    decimals: Optional[int] = None,
) -> str:
    """Formats a price with its currency symbol; shows '--' for None."""
    if value is None:
        return "--"
    code = (currency_code or "USD").upper().strip()
    if decimals is None:
        decimals = 0 if code in ZERO_DECIMAL_CURRENCIES else 2
    symbol = get_currency_symbol(code)
    return f"{symbol}{value:,.{decimals}f}"
