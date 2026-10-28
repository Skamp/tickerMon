import json
import os
import tempfile
import unittest
from pathlib import Path

from app.ui.scaling import (
    DEFAULT_ROUNDING_POLICY,
    apply_scaling_env,
    consume_debug_flag,
    parse_positive_float,
    resolve_scale_factor,
    scaling_summary,
)

_MANAGED_ENV_VARS = (
    "TICKERMON_SCALE",
    "QT_SCALE_FACTOR",
    "QT_SCALE_FACTOR_ROUNDING_POLICY",
)


class TestParsePositiveFloat(unittest.TestCase):
    def test_valid_values(self):
        self.assertEqual(parse_positive_float("1.25"), 1.25)
        self.assertEqual(parse_positive_float(2), 2.0)
        self.assertEqual(parse_positive_float("0.75"), 0.75)

    def test_invalid_values(self):
        self.assertIsNone(parse_positive_float(None))
        self.assertIsNone(parse_positive_float(True))
        self.assertIsNone(parse_positive_float("abc"))
        self.assertIsNone(parse_positive_float("-1"))
        self.assertIsNone(parse_positive_float(0))
        self.assertIsNone(parse_positive_float("nan"))
        self.assertIsNone(parse_positive_float("inf"))
        self.assertIsNone(parse_positive_float([1]))


class TestResolveScaleFactor(unittest.TestCase):
    def test_env_wins_over_config(self):
        self.assertEqual(resolve_scale_factor("1.5", "2.0"), 1.5)

    def test_config_used_when_env_missing(self):
        self.assertEqual(resolve_scale_factor(None, "1.25"), 1.25)

    def test_falls_back_when_env_invalid(self):
        self.assertEqual(resolve_scale_factor("bad", "1.4"), 1.4)

    def test_none_when_nothing_valid(self):
        self.assertIsNone(resolve_scale_factor(None, None))
        self.assertIsNone(resolve_scale_factor("bad", "worse"))


class TestConsumeDebugFlag(unittest.TestCase):
    def test_removes_single_flag(self):
        argv = ["main.py", "--debug-dpi"]
        self.assertTrue(consume_debug_flag(argv))
        self.assertEqual(argv, ["main.py"])

    def test_removes_repeated_flags(self):
        argv = ["main.py", "--debug-dpi", "extra", "--debug-dpi"]
        self.assertTrue(consume_debug_flag(argv))
        self.assertEqual(argv, ["main.py", "extra"])

    def test_absent_flag(self):
        argv = ["main.py"]
        self.assertFalse(consume_debug_flag(argv))
        self.assertEqual(argv, ["main.py"])


class TestApplyScalingEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: os.environ.get(name) for name in _MANAGED_ENV_VARS
        }
        for name in _MANAGED_ENV_VARS:
            os.environ.pop(name, None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "tickers.json"

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def _write_config(self, data):
        self.config_path.write_text(json.dumps(data), encoding="utf-8")

    def test_rounding_policy_pinned(self):
        apply_scaling_env(self.config_path)
        self.assertEqual(
            os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"], DEFAULT_ROUNDING_POLICY
        )

    def test_rounding_policy_not_overwritten(self):
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "Round"
        apply_scaling_env(self.config_path)
        self.assertEqual(os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"], "Round")

    def test_env_scale_sets_qt_scale_factor(self):
        os.environ["TICKERMON_SCALE"] = "1.25"
        scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, 1.25)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1.25")

    def test_config_scale_used_when_env_absent(self):
        self._write_config({"ui_scale": 1.5})
        scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, 1.5)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1.5")

    def test_env_scale_overrides_config(self):
        self._write_config({"ui_scale": 1.5})
        os.environ["TICKERMON_SCALE"] = "2"
        scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, 2.0)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "2")

    def test_no_scale_leaves_qt_scale_factor_unset(self):
        scale = apply_scaling_env(self.config_path)
        self.assertIsNone(scale)
        self.assertNotIn("QT_SCALE_FACTOR", os.environ)

    def test_missing_config_file(self):
        scale = apply_scaling_env(Path(self.temp_dir.name) / "absent.json")
        self.assertIsNone(scale)

    def test_corrupt_config_file(self):
        self.config_path.write_text("{not json", encoding="utf-8")
        scale = apply_scaling_env(self.config_path)
        self.assertIsNone(scale)

    def test_config_without_key(self):
        self._write_config({"selected_range": "1Y"})
        scale = apply_scaling_env(self.config_path)
        self.assertIsNone(scale)


class TestScalingSummary(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: os.environ.get(name) for name in _MANAGED_ENV_VARS
        }
        for name in _MANAGED_ENV_VARS:
            os.environ.pop(name, None)

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_defaults_when_no_overrides(self):
        summary = scaling_summary()
        self.assertIn("Qt defaults", summary)

    def test_reports_active_values(self):
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
        os.environ["QT_SCALE_FACTOR"] = "1.25"
        summary = scaling_summary()
        self.assertIn("PassThrough", summary)
        self.assertIn("1.25", summary)


if __name__ == "__main__":
    unittest.main()
