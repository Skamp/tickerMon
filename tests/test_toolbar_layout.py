import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from app.ui.styles import DARK_THEME_QSS
from app.ui.scaling import apply_scaling_env, setup_display_scaling

_ROOT = Path(__file__).resolve().parents[1]
_APP = None


def _qapp() -> QApplication:
    global _APP
    if _APP is None:
        apply_scaling_env(None)
        _APP = QApplication([])
        _APP.setStyleSheet(DARK_THEME_QSS)
        setup_display_scaling(_APP)
    return _APP


def _overlap_count(widget: QWidget) -> int:
    """Counts pairs of visible leaf widgets with overlapping global rects."""
    leaves = []
    stack = [widget]
    while stack:
        current = stack.pop()
        children = current.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        stack.extend(children)
        if not children and current.isVisible() and current.width() > 0 and current.height() > 0:
            leaves.append(current)

    def global_rect(w: QWidget):
        top_left = w.mapToGlobal(w.rect().topLeft())
        return (
            top_left.x(),
            top_left.y(),
            top_left.x() + w.width(),
            top_left.y() + w.height(),
        )

    count = 0
    for i in range(len(leaves)):
        ra = global_rect(leaves[i])
        for j in range(i + 1, len(leaves)):
            rb = global_rect(leaves[j])
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                count += 1
    return count


class TestToolbarLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qapp()
        cls.temp_dir = tempfile.mkdtemp()
        config_dst = Path(cls.temp_dir) / "tickers.json"
        shutil.copy(_ROOT / "config" / "tickers.json", config_dst)
        db_src = _ROOT / "data" / "market_data.db"
        if db_src.exists():
            shutil.copy(db_src, Path(cls.temp_dir) / "market_data.db")

        from app.config.config_manager import ConfigManager
        from app.database.database import Database
        from app.database.repositories import ForecastRepository, MarketDataRepository
        from app.services.yahoo_service import YahooService
        from app.services.market_data_service import MarketDataService
        from app.services.ticker_service import TickerService
        from app.services.sync_service import SyncService
        from app.services.earnings_service import EarningsService
        from app.services.forecast_service import ForecastService
        from app.ui.main_window import MainWindow

        db_path = Path(cls.temp_dir) / "market_data.db"
        repo = MarketDataRepository(Database(db_path))
        market = MarketDataService(repo)
        ticker_service = TickerService(ConfigManager(config_dst))
        cls.window = MainWindow(
            ticker_service=ticker_service,
            market_data_service=market,
            sync_service=SyncService(YahooService(), repo),
            earnings_service=EarningsService(YahooService(), repo),
            forecast_service=ForecastService(
                market, ticker_service, ForecastRepository(Database(db_path)), price_repo=repo
            ),
        )
        cls.window.resize(1480, 780)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_no_overlaps_at_default_and_min_sizes(self):
        for width, height in ((1480, 780), (1240, 600)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertEqual(
                _overlap_count(self.window._toolbar_frame),
                0,
                "toolbar overlaps at %dx%d (stacked=%s)"
                % (width, height, self.window._toolbar_stacked),
            )

    def test_stacks_when_narrow_unstacks_when_wide(self):
        self.window.resize(1240, 600)
        self.app.processEvents()
        self.assertTrue(self.window._toolbar_stacked)

        frame = self.window._toolbar_frame
        margins = frame.contentsMargins()
        needed = sum(
            section.sizeHint().width()
            for section in (
                self.window._toolbar_section_updates,
                self.window._toolbar_section_filter,
                self.window._toolbar_section_range,
                self.window._toolbar_section_actions,
            )
        ) + self.window._toolbar_row_a.spacing() * 3
        self.window.resize(needed + margins.left() + margins.right() + 80, 780)
        self.app.processEvents()
        self.assertFalse(self.window._toolbar_stacked)
        self.assertEqual(_overlap_count(self.window._toolbar_frame), 0)
        self.window.resize(1480, 780)
        self.app.processEvents()

    def test_toolbar_sections_present(self):
        for section in (
            self.window._toolbar_section_updates,
            self.window._toolbar_section_filter,
            self.window._toolbar_section_range,
            self.window._toolbar_section_actions,
        ):
            self.assertIsNotNone(section)

    def test_scaled_window_is_wide_enough_for_single_row_toolbar(self):
        import os
        from app.ui.main_window import (
            DEFAULT_WINDOW_WIDTH,
            MIN_WINDOW_WIDTH,
        )
        from app.ui.scaling import effective_scale_factor

        saved = os.environ.get("QT_SCALE_FACTOR")
        os.environ["QT_SCALE_FACTOR"] = "1.5"
        try:
            scale = effective_scale_factor()
            self.assertEqual(scale, 1.5)
            scaled_default = int(DEFAULT_WINDOW_WIDTH * scale)
            scaled_min = int(MIN_WINDOW_WIDTH * scale)
            self.assertEqual(scaled_default, 2220)
            self.assertEqual(scaled_min, 1860)

            self.window.resize(scaled_default, 780)
            self.app.processEvents()
            frame = self.window._toolbar_frame
            margins = frame.contentsMargins()
            needed = sum(
                section.sizeHint().width()
                for section in (
                    self.window._toolbar_section_updates,
                    self.window._toolbar_section_filter,
                    self.window._toolbar_section_range,
                    self.window._toolbar_section_actions,
                )
            ) + self.window._toolbar_row_a.spacing() * 3
            available = frame.width() - margins.left() - margins.right()
            self.assertGreaterEqual(
                available,
                needed,
                "scaled default width %d still stacks the toolbar (needed %d)"
                % (scaled_default, needed),
            )
            self.assertFalse(self.window._toolbar_stacked)
        finally:
            if saved is None:
                os.environ.pop("QT_SCALE_FACTOR", None)
            else:
                os.environ["QT_SCALE_FACTOR"] = saved
            self.window.resize(1480, 780)
            self.app.processEvents()

    def test_structure_labels_toggle_redraws_when_cleared(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        chk = self.window.chk_structure_labels
        chart = self.window.chart_widget

        chk.setChecked(False)
        self.app.processEvents()
        self.assertFalse(chart.has_structure_labels())

        QTest.mouseClick(chk, Qt.LeftButton, Qt.NoModifier, chk.rect().center())
        self.app.processEvents()
        self.assertTrue(chk.isChecked())
        self.assertTrue(chart.has_structure_labels())
        self.assertTrue(all(item.isVisible() for item in chart._structure_items))

        QTest.mouseClick(chk, Qt.LeftButton, Qt.NoModifier, chk.rect().center())
        self.app.processEvents()
        self.assertFalse(chk.isChecked())
        self.assertFalse(any(item.isVisible() for item in chart._structure_items))

        QTest.mouseClick(chk, Qt.LeftButton, Qt.NoModifier, chk.rect().center())
        self.app.processEvents()
        self.assertTrue(chk.isChecked())
        self.assertTrue(all(item.isVisible() for item in chart._structure_items))


if __name__ == "__main__":
    unittest.main()
