import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ui import scaling
from app.ui.scaling import (
    DEFAULT_ROUNDING_POLICY,
    DEFAULT_SEEDED_UI_SCALE,
    FONT_FAMILY_CANDIDATES,
    apply_scaling_env,
    consume_debug_flag,
    effective_scale_factor,
    parse_positive_float,
    resolve_font_family,
    resolve_scale_factor,
    scaling_summary,
    seed_default_scale,
    should_seed_default_scale,
    window_width_scale,
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


class TestResolveFontFamily(unittest.TestCase):
    def test_picks_first_installed_candidate(self):
        families = ["Liberation Sans", "DejaVu Sans", "Ubuntu Mono"]
        self.assertEqual(resolve_font_family(families), "DejaVu Sans")

    def test_prefers_segoe_when_installed(self):
        families = ["DejaVu Sans", "Segoe UI", "Noto Sans"]
        self.assertEqual(resolve_font_family(families), "Segoe UI")

    def test_case_insensitive(self):
        self.assertEqual(resolve_font_family(["dejavu sans"]), "DejaVu Sans")

    def test_none_when_no_candidate_installed(self):
        self.assertIsNone(resolve_font_family(["Liberation Mono"]))

    def test_empty_list(self):
        self.assertIsNone(resolve_font_family([]))

    def test_candidate_order_respected(self):
        families = list(FONT_FAMILY_CANDIDATES)
        self.assertEqual(resolve_font_family(families), FONT_FAMILY_CANDIDATES[0])


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
        # Pin a pre-seeding Python version so these assertions stay valid on
        # any interpreter; the seeding behavior itself has dedicated tests.
        self._version_patcher = mock.patch.object(
            scaling.sys, "version_info", (3, 12, 0)
        )
        self._version_patcher.start()

    def tearDown(self):
        self._version_patcher.stop()
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

    def test_config_ui_scale_is_applied(self):
        self._write_config({"ui_scale": 1.5})
        scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, 1.5)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1.5")

    def test_env_scale_wins_over_config_ui_scale(self):
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

    def test_config_file_not_written_on_pre_seed_python(self):
        self._write_config({"selected_range": "1Y"})
        apply_scaling_env(self.config_path)
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("ui_scale", data)
        self.assertEqual(data["selected_range"], "1Y")


class TestSeedDefaultScale(unittest.TestCase):
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

    def test_should_seed_version_matrix(self):
        self.assertTrue(should_seed_default_scale((3, 13)))
        self.assertTrue(should_seed_default_scale((3, 14, 4)))
        self.assertFalse(should_seed_default_scale((3, 12, 6)))
        self.assertFalse(should_seed_default_scale((3, 8, 10)))
        self.assertFalse(should_seed_default_scale(None))
        self.assertFalse(should_seed_default_scale("3.14"))

    def test_seeds_missing_file(self):
        self.assertTrue(
            seed_default_scale(self.config_path, version_info=(3, 14, 0))
        )
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui_scale"], DEFAULT_SEEDED_UI_SCALE)

    def test_seeds_preserving_existing_keys(self):
        self._write_config({"selected_range": "6M", "tickers": [{"symbol": "AAPL"}]})
        self.assertTrue(
            seed_default_scale(self.config_path, version_info=(3, 14, 0))
        )
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui_scale"], DEFAULT_SEEDED_UI_SCALE)
        self.assertEqual(data["selected_range"], "6M")
        self.assertEqual(data["tickers"], [{"symbol": "AAPL"}])

    def test_never_overwrites_existing_value(self):
        self._write_config({"ui_scale": 2.0})
        self.assertFalse(
            seed_default_scale(self.config_path, version_info=(3, 14, 0))
        )
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui_scale"], 2.0)

    def test_skips_on_python_312(self):
        self.assertFalse(
            seed_default_scale(self.config_path, version_info=(3, 12, 6))
        )
        self.assertFalse(self.config_path.exists())

    def test_skips_on_python_38(self):
        self.assertFalse(
            seed_default_scale(self.config_path, version_info=(3, 8, 10))
        )
        self.assertFalse(self.config_path.exists())

    def test_skips_corrupt_file_untouched(self):
        corrupt = "{not json"
        self.config_path.write_text(corrupt, encoding="utf-8")
        with self.assertLogs("app.ui.scaling", level="WARNING"):
            self.assertFalse(
                seed_default_scale(self.config_path, version_info=(3, 14, 0))
            )
        self.assertEqual(
            self.config_path.read_text(encoding="utf-8"), corrupt
        )

    def test_none_path(self):
        self.assertFalse(seed_default_scale(None, version_info=(3, 14, 0)))

    def test_apply_seeds_then_resolves(self):
        self._write_config({"selected_range": "1Y"})
        with mock.patch.object(scaling.sys, "version_info", (3, 14, 0)):
            scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, DEFAULT_SEEDED_UI_SCALE)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1.5")
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui_scale"], DEFAULT_SEEDED_UI_SCALE)
        self.assertEqual(data["selected_range"], "1Y")

    def test_env_still_wins_over_seeded_config(self):
        self._write_config({"selected_range": "1Y"})
        os.environ["TICKERMON_SCALE"] = "2"
        with mock.patch.object(scaling.sys, "version_info", (3, 14, 0)):
            scale = apply_scaling_env(self.config_path)
        self.assertEqual(scale, 2.0)
        self.assertEqual(os.environ["QT_SCALE_FACTOR"], "2")
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["ui_scale"], DEFAULT_SEEDED_UI_SCALE)


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


class TestEffectiveScaleFactor(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("QT_SCALE_FACTOR")
        os.environ.pop("QT_SCALE_FACTOR", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("QT_SCALE_FACTOR", None)
        else:
            os.environ["QT_SCALE_FACTOR"] = self._saved

    def test_defaults_to_one_when_unset(self):
        self.assertEqual(effective_scale_factor(), 1.0)

    def test_reads_active_qt_scale_factor(self):
        os.environ["QT_SCALE_FACTOR"] = "1.5"
        self.assertEqual(effective_scale_factor(), 1.5)

    def test_invalid_value_falls_back_to_one(self):
        os.environ["QT_SCALE_FACTOR"] = "not-a-number"
        self.assertEqual(effective_scale_factor(), 1.0)

    def test_non_positive_falls_back_to_one(self):
        os.environ["QT_SCALE_FACTOR"] = "0"
        self.assertEqual(effective_scale_factor(), 1.0)


class TestWindowWidthScale(unittest.TestCase):
    def test_identity_when_no_scale(self):
        self.assertEqual(window_width_scale(1.0), 1.0)

    def test_half_delta_at_1_5(self):
        self.assertEqual(window_width_scale(1.5), 1.25)

    def test_reduced_vs_full_factor(self):
        self.assertLess(window_width_scale(1.5), 1.5)
        self.assertLess(window_width_scale(2.0), 2.0)

    def test_below_one_clamps_to_identity(self):
        self.assertEqual(window_width_scale(0.5), 1.0)

    def test_reads_active_env_when_omitted(self):
        saved = os.environ.get("QT_SCALE_FACTOR")
        os.environ["QT_SCALE_FACTOR"] = "1.5"
        try:
            self.assertEqual(window_width_scale(), 1.25)
        finally:
            if saved is None:
                os.environ.pop("QT_SCALE_FACTOR", None)
            else:
                os.environ["QT_SCALE_FACTOR"] = saved


class _StubGeometry:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class _StubScreen:
    def name(self):
        return "Stub Screen"

    def geometry(self):
        return _StubGeometry(2560, 1440)

    def devicePixelRatio(self):
        return 1.5

    def logicalDotsPerInch(self):
        return 96.0

    def physicalDotsPerInch(self):
        return 106.0


class _StubFont:
    def family(self):
        return "Segoe UI"

    def pointSizeF(self):
        return 9.0


class _StubApp:
    def __init__(self, screen):
        self._screen = screen

    def primaryScreen(self):
        return self._screen

    def font(self):
        return _StubFont()


class TestLogStartupMetrics(unittest.TestCase):
    def test_logs_screen_metrics_line(self):
        with self.assertLogs("app.ui.scaling", level="INFO") as logs:
            from app.ui.scaling import log_startup_metrics

            log_startup_metrics(_StubApp(_StubScreen()))
        line = logs.output[0]
        self.assertIn("Screen metrics:", line)
        self.assertIn("screen=Stub Screen", line)
        self.assertIn("screen geometry=2560x1440", line)
        self.assertIn("devicePixelRatio=1.5", line)
        self.assertIn("logicalDotsPerInch=96.0", line)
        self.assertIn("physicalDotsPerInch=106.0", line)
        self.assertIn("font=Segoe UI@9pt", line)
        self.assertIn("scaling=", line)
        self.assertIn("qt_scale=", line)

    def test_falls_back_without_primary_screen(self):
        with self.assertLogs("app.ui.scaling", level="INFO") as logs:
            from app.ui.scaling import log_startup_metrics

            log_startup_metrics(_StubApp(None))
        self.assertIn("no primary screen available", logs.output[0])


if __name__ == "__main__":
    unittest.main()
