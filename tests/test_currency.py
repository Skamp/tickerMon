import unittest

from app.utils.currency import format_price, get_currency_symbol


class TestGetCurrencySymbol(unittest.TestCase):
    def test_usd(self):
        self.assertEqual(get_currency_symbol("USD"), "$")

    def test_jpy(self):
        self.assertEqual(get_currency_symbol("JPY"), "¥")

    def test_eur(self):
        self.assertEqual(get_currency_symbol("EUR"), "€")

    def test_lowercase_and_whitespace(self):
        self.assertEqual(get_currency_symbol("  jpy "), "¥")

    def test_none_defaults_to_usd(self):
        self.assertEqual(get_currency_symbol(None), "$")

    def test_unknown_code_falls_back_to_code_prefix(self):
        self.assertEqual(get_currency_symbol("XYZ"), "XYZ ")


class TestFormatPrice(unittest.TestCase):
    def test_usd_two_decimals(self):
        self.assertEqual(format_price(146.96, "USD"), "$146.96")

    def test_usd_thousands_separator(self):
        self.assertEqual(format_price(1234567.89, "USD"), "$1,234,567.89")

    def test_jpy_zero_decimals(self):
        self.assertEqual(format_price(8012.4, "JPY"), "¥8,012")

    def test_eur(self):
        self.assertEqual(format_price(42.5, "EUR"), "€42.50")

    def test_none_value_returns_placeholder(self):
        self.assertEqual(format_price(None, "USD"), "--")

    def test_none_currency_defaults_to_usd(self):
        self.assertEqual(format_price(10.0, None), "$10.00")

    def test_explicit_decimals_override(self):
        self.assertEqual(format_price(8012.4, "JPY", decimals=2), "¥8,012.40")


if __name__ == "__main__":
    unittest.main()
