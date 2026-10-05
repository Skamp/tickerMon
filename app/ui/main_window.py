import logging
from typing import Optional, List

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QSplitter,
    QStatusBar,
    QButtonGroup,
    QComboBox,
    QMessageBox,
    QSpinBox,
    QSizePolicy,
)

from app.models.time_range import TimeRange
from app.models.ticker import TickerConfig, TickerSummary
from app.services.ticker_service import TickerService
from app.services.market_data_service import MarketDataService, count_trend_buckets
from app.services.sync_service import SyncService
from app.services.noise_reduction import NoiseReductionAlgorithm, reduce_noise
from app.services.swing_detection import (
    SwingAlgorithm,
    SwingRangeMode,
    SWING_ALGORITHM_DESCRIPTIONS,
    describe_swing_range,
    format_swing_params,
)
from app.ui.ticker_list import TickerListWidget
from app.ui.chart_widget import StockChartWidget
from app.ui.ticker_dialog import TickerAdminDialog
from app.ui.filter_settings_dialog import FilterSettingsDialog
from app.ui.swing_settings_dialog import SwingSettingsDialog
from app.ui.trend_filter_bar import TrendFilterBar
from app.ui.update_dialog import UpdateProgressDialog
from app.workers.update_worker import UpdateWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        ticker_service: TickerService,
        market_data_service: MarketDataService,
        sync_service: SyncService,
    ):
        super().__init__()
        self.ticker_service = ticker_service
        self.market_data_service = market_data_service
        self.sync_service = sync_service

        self.setWindowTitle("tickerMon - Stock Market Terminal")
        self.resize(1340, 780)
        self.setMinimumSize(1024, 600)

        self._active_range = TimeRange.ONE_YEAR
        self._active_noise_algo = NoiseReductionAlgorithm.NONE
        self._active_swing_algo = SwingAlgorithm.RANGE
        self._current_summary: Optional[TickerSummary] = None
        self._period_start_price: Optional[float] = None
        self._update_worker: Optional[UpdateWorker] = None
        self._chart_timestamps: List[float] = []
        self._chart_prices: List[float] = []

        self._swing_range_timer = QTimer(self)
        self._swing_range_timer.setSingleShot(True)
        self._swing_range_timer.setInterval(400)
        self._swing_range_timer.timeout.connect(self._refresh_ticker_list)

        # Build UI layout
        self._init_ui()
        self._setup_shortcuts()

        # Load initial state
        self._load_initial_state()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ---------------------------------------------------------------------
        # Top Header / Toolbar Layout
        # ---------------------------------------------------------------------
        toolbar_frame = QFrame(self)
        toolbar_frame.setObjectName("headerFrame")
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(12)

        # Update Data Button
        self.btn_update = QPushButton("Update Data", toolbar_frame)
        self.btn_update.setObjectName("updateButton")
        self.btn_update.setToolTip("Sync latest price data from Yahoo Finance (Ctrl+U)")
        self.btn_update.clicked.connect(self._on_update_clicked)
        toolbar_layout.addWidget(self.btn_update)

        toolbar_layout.addSpacing(15)

        # Noise Reduction + Swing Detection ComboBoxes (Left of Time Ranges)
        combo_style = """
            QComboBox {
                background-color: #252836;
                color: #e1e3ea;
                border: 1px solid #323647;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: 600;
                min-width: 190px;
            }
            QComboBox:hover {
                border-color: #454b61;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1c24;
                color: #e1e3ea;
                selection-background-color: #2962ff;
            }
        """

        self.filter_stack_widget = QWidget(toolbar_frame)
        self.filter_stack_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        filter_stack = QVBoxLayout(self.filter_stack_widget)
        filter_stack.setContentsMargins(0, 0, 0, 0)
        filter_stack.setSpacing(4)

        noise_row = QHBoxLayout()
        noise_row.setSpacing(8)

        noise_label = QLabel("Filter:", toolbar_frame)
        noise_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        noise_row.addWidget(noise_label)

        self.combo_noise = QComboBox(toolbar_frame)
        self.combo_noise.setToolTip("Apply noise reduction algorithm overlay to price graph")
        self.combo_noise.setStyleSheet(combo_style)

        self._rebuild_noise_combo()
        self.combo_noise.currentIndexChanged.connect(self._on_noise_algorithm_changed)
        noise_row.addWidget(self.combo_noise)

        self.btn_filter_settings = QPushButton("Filters…", toolbar_frame)
        self.btn_filter_settings.setToolTip("Choose which filters appear in the Filter list")
        self.btn_filter_settings.clicked.connect(self._on_open_filter_settings)
        noise_row.addWidget(self.btn_filter_settings)
        filter_stack.addLayout(noise_row)

        swing_row = QHBoxLayout()
        swing_row.setSpacing(8)

        swing_label = QLabel("Swing:", toolbar_frame)
        swing_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        swing_row.addWidget(swing_label)

        self.combo_swing = QComboBox(toolbar_frame)
        self.combo_swing.setToolTip("Algorithm used to detect the swing bucket")
        self.combo_swing.setStyleSheet(combo_style)

        self._rebuild_swing_combo()
        self.combo_swing.currentIndexChanged.connect(self._on_swing_algorithm_changed)
        swing_row.addWidget(self.combo_swing)

        self.btn_swing_settings = QPushButton("Swing…", toolbar_frame)
        self.btn_swing_settings.setToolTip("Enable swing algorithms and configure their parameters")
        self.btn_swing_settings.clicked.connect(self._on_open_swing_settings)
        swing_row.addWidget(self.btn_swing_settings)

        filter_stack.addLayout(swing_row)

        swing_range_row = QHBoxLayout()
        swing_range_row.setSpacing(8)

        duration_label = QLabel("Duration:", toolbar_frame)
        duration_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        swing_range_row.addWidget(duration_label)

        row_label_width = max(
            noise_label.sizeHint().width(),
            swing_label.sizeHint().width(),
            duration_label.sizeHint().width(),
        )
        noise_label.setFixedWidth(row_label_width)
        swing_label.setFixedWidth(row_label_width)
        duration_label.setFixedWidth(row_label_width)

        self.combo_swing_range_mode = QComboBox(toolbar_frame)
        for swing_range_mode in SwingRangeMode:
            self.combo_swing_range_mode.addItem(swing_range_mode.value, userData=swing_range_mode.value)
        self.combo_swing_range_mode.setStyleSheet(combo_style)
        self.combo_swing_range_mode.setToolTip(
            "Minimum duration: keep swings taking at least X\n"
            "Maximum duration: keep swings completing within X\n"
            "Lookback window: only detect swings in the last X\n"
            "Duration window: keep swings between X and Y"
        )
        swing_range_row.addWidget(self.combo_swing_range_mode)

        self.spin_swing_range = QSpinBox(toolbar_frame)
        self.spin_swing_range.setRange(0, 520)
        self.spin_swing_range.setFixedWidth(66)
        self.spin_swing_range.setSpecialValueText("Off")
        self.spin_swing_range.setToolTip(
            "Detect only swings inside this time range (weeks).\n"
            "0 = Off (no range filter)."
        )
        swing_range_row.addWidget(self.spin_swing_range)

        self.lbl_swing_range_dash = QLabel("-", toolbar_frame)
        self.lbl_swing_range_dash.setStyleSheet("color: #8b90a0;")
        swing_range_row.addWidget(self.lbl_swing_range_dash)

        self.spin_swing_range_max = QSpinBox(toolbar_frame)
        self.spin_swing_range_max.setRange(1, 520)
        self.spin_swing_range_max.setFixedWidth(66)
        self.spin_swing_range_max.setToolTip("Upper bound of the swing duration window.")
        swing_range_row.addWidget(self.spin_swing_range_max)

        self.lbl_swing_range_unit = QLabel("weeks", toolbar_frame)
        self.lbl_swing_range_unit.setStyleSheet("color: #8b90a0;")
        swing_range_row.addWidget(self.lbl_swing_range_unit)

        filter_stack.addLayout(swing_range_row)

        self.filter_stack_widget.setMinimumWidth(
            max(
                noise_row.sizeHint().width(),
                swing_row.sizeHint().width(),
                swing_range_row.sizeHint().width(),
            )
        )

        self._load_swing_range_settings()

        self.spin_swing_range.valueChanged.connect(self._on_swing_range_changed)
        self.spin_swing_range_max.valueChanged.connect(self._on_swing_range_changed)
        self.combo_swing_range_mode.currentIndexChanged.connect(self._on_swing_range_changed)

        toolbar_layout.addWidget(self.filter_stack_widget)

        toolbar_layout.addSpacing(15)

        # Time Range Button Group
        range_label = QLabel("Range:", toolbar_frame)
        range_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        toolbar_layout.addWidget(range_label)

        self.range_button_group = QButtonGroup(self)
        self.range_button_group.setExclusive(True)

        for tr in [TimeRange.ONE_WEEK, TimeRange.ONE_MONTH, TimeRange.SIX_MONTHS, TimeRange.ONE_YEAR]:
            btn = QPushButton(tr.value, toolbar_frame)
            btn.setCheckable(True)
            btn.setProperty("time_range", tr)
            if tr == TimeRange.ONE_YEAR:
                btn.setChecked(True)
            btn.clicked.connect(self._on_range_changed)
            self.range_button_group.addButton(btn)
            toolbar_layout.addWidget(btn)

        toolbar_layout.addStretch()

        # Manage Tickers Button
        self.btn_admin = QPushButton("Manage Tickers", toolbar_frame)
        self.btn_admin.setToolTip("Add, remove, or reorder tickers (Ctrl+T)")
        self.btn_admin.clicked.connect(self._on_open_admin)
        toolbar_layout.addWidget(self.btn_admin)

        # Reset View Button
        self.btn_reset_view = QPushButton("Reset Zoom", toolbar_frame)
        self.btn_reset_view.setToolTip("Reset chart zoom and pan")
        self.btn_reset_view.clicked.connect(self._on_reset_view)
        toolbar_layout.addWidget(self.btn_reset_view)

        main_layout.addWidget(toolbar_frame)

        # ---------------------------------------------------------------------
        # Main Content Splitter (Left Sidebar + Right Chart Area)
        # ---------------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal, self)

        # Left Sidebar (Ticker List)
        sidebar_frame = QFrame(splitter)
        sidebar_frame.setObjectName("sidebarFrame")
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(6)

        self.trend_filter_bar = TrendFilterBar(sidebar_frame)
        self.trend_filter_bar.filter_changed.connect(self._on_trend_filter_changed)
        self.trend_filter_bar.set_swing_algorithm(self._active_swing_algo.value)
        sidebar_layout.addWidget(self.trend_filter_bar)

        sidebar_header = QLabel("MARKET WATCH", sidebar_frame)
        sidebar_header.setStyleSheet("font-size: 11px; font-weight: bold; color: #8b90a0; letter-spacing: 1px;")
        sidebar_layout.addWidget(sidebar_header)

        self.ticker_list = TickerListWidget(sidebar_frame)
        self.ticker_list.ticker_selected.connect(self._on_ticker_selected)
        sidebar_layout.addWidget(self.ticker_list)

        splitter.addWidget(sidebar_frame)

        # Right Main Panel (Summary Card Header + PyQtGraph Chart)
        right_panel = QFrame(splitter)
        right_panel.setObjectName("cardFrame")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(10)

        # Summary Header Card
        self.header_card = QHBoxLayout()

        # Left Column: Symbol & Company Name
        title_box = QVBoxLayout()
        self.lbl_symbol = QLabel("--", right_panel)
        self.lbl_symbol.setObjectName("titleLabel")
        self.lbl_company = QLabel("--", right_panel)
        self.lbl_company.setObjectName("subtitleLabel")
        title_box.addWidget(self.lbl_symbol)
        title_box.addWidget(self.lbl_company)
        self.header_card.addLayout(title_box)

        self.header_card.addStretch()

        # Middle Column: Price & Change
        price_box = QVBoxLayout()
        price_box.setAlignment(Qt.AlignRight)
        self.lbl_price = QLabel("--", right_panel)
        self.lbl_price.setObjectName("priceLabel")
        self.lbl_change = QLabel("--", right_panel)
        self.lbl_change.setObjectName("changeNeutral")
        price_box.addWidget(self.lbl_price)
        price_box.addWidget(self.lbl_change)
        self.header_card.addLayout(price_box)

        self.header_card.addSpacing(30)

        # Right Column: High/Low Metrics & Sync Info
        info_box = QVBoxLayout()
        info_box.setAlignment(Qt.AlignRight)
        self.lbl_high_low = QLabel("High: -- | Low: --", right_panel)
        self.lbl_high_low.setStyleSheet("color: #8b90a0; font-size: 12px; font-weight: bold;")
        self.lbl_info_range = QLabel("Range: 1 Year", right_panel)
        self.lbl_info_range.setStyleSheet("color: #8b90a0; font-size: 11px;")
        self.lbl_last_sync = QLabel("Last Sync: Never", right_panel)
        self.lbl_last_sync.setStyleSheet("color: #8b90a0; font-size: 11px;")
        info_box.addWidget(self.lbl_high_low)
        info_box.addWidget(self.lbl_info_range)
        info_box.addWidget(self.lbl_last_sync)
        self.header_card.addLayout(info_box)

        right_layout.addLayout(self.header_card)

        # Horizontal Divider Line
        line = QFrame(right_panel)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #282b36;")
        right_layout.addWidget(line)

        # Chart Widget
        self.chart_widget = StockChartWidget(right_panel)
        self.chart_widget.hover_changed.connect(self._on_chart_hover_changed)
        self.chart_widget.hover_left.connect(self._on_chart_hover_left)
        right_layout.addWidget(self.chart_widget)

        splitter.addWidget(right_panel)

        # Splitter sizing ratio
        splitter.setSizes([260, 1080])
        splitter.setCollapsible(0, False)

        main_layout.addWidget(splitter)

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Select a ticker to view chart.")

    def _setup_shortcuts(self) -> None:
        """Configures global application keyboard shortcuts."""
        QShortcut(QKeySequence(Qt.Key_R), self, self._on_refresh_chart)
        QShortcut(QKeySequence("Ctrl+U"), self, self._on_update_clicked)
        QShortcut(QKeySequence("Ctrl+T"), self, self._on_open_admin)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence(Qt.Key_Home), self, self.ticker_list.select_first)
        QShortcut(QKeySequence(Qt.Key_End), self, self.ticker_list.select_last)

    def _load_initial_state(self) -> None:
        target_ticker = self.ticker_service.selected_ticker
        target_range_str = self.ticker_service.selected_range

        self._active_range = TimeRange.from_str(target_range_str)
        for btn in self.range_button_group.buttons():
            if btn.property("time_range") == self._active_range:
                btn.setChecked(True)
                break

        self._refresh_ticker_list(select_symbol=target_ticker)

    def _refresh_ticker_list(self, select_symbol: Optional[str] = None) -> None:
        """Reloads sidebar summaries and trend bucket counts for the active time range."""
        enabled_configs = self.ticker_service.get_enabled_tickers()
        summaries = self.market_data_service.get_all_summaries(enabled_configs)
        trends = self.market_data_service.get_trend_buckets(enabled_configs, self._active_range)
        swing_symbols = self.market_data_service.get_swing_symbols(
            enabled_configs,
            self._active_range,
            self._active_swing_algo,
            params=self.ticker_service.get_swing_params(self._active_swing_algo),
            range_settings=self.ticker_service.get_swing_range_settings(),
        )
        self.trend_filter_bar.set_counts(count_trend_buckets(trends), len(swing_symbols))
        self.ticker_list.update_summaries(
            summaries,
            select_symbol=select_symbol,
            trends=trends,
            swing_symbols=swing_symbols,
        )

    def _on_trend_filter_changed(self) -> None:
        self.ticker_list.set_trend_filter(
            self.trend_filter_bar.active_trends(),
            include_swing=self.trend_filter_bar.swing_active(),
        )

    def _on_ticker_selected(self, symbol: str) -> None:
        """Fast offline chart update when selected ticker changes."""
        enabled_configs = self.ticker_service.get_enabled_tickers()
        config = next((c for c in enabled_configs if c.symbol == symbol), None)
        if not config:
            return

        self.ticker_service.set_preferences(symbol, self._active_range.value)

        summary = self.market_data_service.get_ticker_summary(config)
        self._current_summary = summary
        self.lbl_symbol.setText(summary.symbol)
        self.lbl_company.setText(summary.company_name)

        self._restore_summary_display()

        # Update PyQtGraph Chart (Offline SQLite Query)
        timestamps, prices, date_labels = self.market_data_service.get_chart_data(symbol, self._active_range)
        self._chart_timestamps = timestamps
        self._chart_prices = prices

        if not timestamps or not prices:
            self._period_start_price = None
            self.lbl_high_low.setText("High: -- | Low: --")
            self.chart_widget.clear_overlay()
            self.chart_widget.clear_swing_overlay()
            self.chart_widget.show_empty_state(
                True,
                f"No local market data available for '{symbol}'.\nPress 'Update Data' (Ctrl+U) to download prices from Yahoo Finance."
            )
            self.status_bar.showMessage(f"No local data stored for {symbol}.")
        else:
            self._period_start_price = prices[0]
            hi_val, lo_val = max(prices), min(prices)
            self.lbl_high_low.setText(f"High: ${hi_val:,.2f} | Low: ${lo_val:,.2f}")

            # Performance color based on period open vs latest close
            p_start = prices[0]
            p_end = prices[-1]
            color = "#00e676" if p_end >= p_start else "#ff5252"

            if len(prices) > 1 and p_start > 0:
                period_change = p_end - p_start
                period_pct = (period_change / p_start) * 100.0
                chg_str = f"{period_change:+.2f} ({period_pct:+.2f}%) [{self._active_range.value}]"
                if period_pct > 0:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changePositive")
                elif period_pct < 0:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changeNegative")
                else:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changeNeutral")
                self.lbl_change.setStyle(self.lbl_change.style())

            self.chart_widget.set_data(timestamps, prices, date_labels, line_color=color)

            # Apply active noise reduction algorithm overlay
            self._apply_active_noise_reduction(timestamps, prices)

            # Draw detected swing pivots and parameter details
            self._update_swing_overlay()

            self.status_bar.showMessage(f"Loaded {len(prices)} historical points for {symbol} ({self._active_range.display_name}).")

    def _apply_active_noise_reduction(self, timestamps: List[float], prices: List[float]) -> None:
        """Applies selected noise reduction algorithm and overlays secondary curve."""
        if self._active_noise_algo == NoiseReductionAlgorithm.NONE or not timestamps:
            self.chart_widget.clear_overlay()
            return

        red_x, red_y = reduce_noise(self._active_noise_algo, timestamps, prices)
        self.chart_widget.set_overlay_data(red_x, red_y)

    def _update_swing_overlay(self) -> None:
        """Draws the pivots detected by the active swing algorithm on the chart."""
        if not self._chart_timestamps or not self._chart_prices:
            self.chart_widget.clear_swing_overlay()
            return

        algorithm = self._active_swing_algo
        params = self.ticker_service.get_swing_params(algorithm)
        range_settings = self.ticker_service.get_swing_range_settings()
        symbol = self.ticker_list.get_selected_symbol() or ""
        pivots, legs = self.market_data_service.detect_swing_overlay(
            symbol,
            self._active_range,
            self._chart_prices,
            self._chart_timestamps,
            algorithm,
            params,
            range_settings,
        )
        title = f"Swing: {algorithm.value} ({len(pivots)} pivots)"
        details = (
            f"{format_swing_params(algorithm, params)}\n"
            f"Swing range: {describe_swing_range(range_settings)}"
        )
        self.chart_widget.set_swing_overlay(
            self._chart_timestamps, self._chart_prices, pivots, title, details, legs
        )

    def _load_swing_range_settings(self) -> None:
        settings = self.ticker_service.get_swing_range_settings()
        widgets = (
            self.spin_swing_range,
            self.spin_swing_range_max,
            self.combo_swing_range_mode,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.spin_swing_range.setValue(settings["value"])
        self.spin_swing_range_max.setValue(max(settings["value_max"], 1))
        index = self.combo_swing_range_mode.findData(settings["mode"])
        self.combo_swing_range_mode.setCurrentIndex(index if index >= 0 else 0)
        self._update_swing_range_visibility(settings["mode"])
        for widget in widgets:
            widget.blockSignals(False)

    def _update_swing_range_visibility(self, mode_value: str) -> None:
        is_window = mode_value == SwingRangeMode.DURATION_WINDOW.value
        self.lbl_swing_range_dash.setVisible(is_window)
        self.spin_swing_range_max.setVisible(is_window)

    def _on_swing_range_changed(self, *args) -> None:
        mode = self.combo_swing_range_mode.currentData() or SwingRangeMode.MIN_DURATION.value
        settings = {
            "mode": mode,
            "value": self.spin_swing_range.value(),
            "value_max": (
                self.spin_swing_range_max.value()
                if mode == SwingRangeMode.DURATION_WINDOW.value
                else 0
            ),
            "unit": "weeks",
        }
        self.ticker_service.set_swing_range_settings(settings)
        normalized = self.ticker_service.get_swing_range_settings()

        if normalized["mode"] == SwingRangeMode.DURATION_WINDOW.value:
            self.spin_swing_range_max.blockSignals(True)
            self.spin_swing_range_max.setValue(max(normalized["value_max"], 1))
            self.spin_swing_range_max.blockSignals(False)
        self._update_swing_range_visibility(normalized["mode"])

        self._update_swing_overlay()
        self._swing_range_timer.start()
        self.status_bar.showMessage(
            f"Swing range updated ({describe_swing_range(normalized)})."
        )

    def _rebuild_noise_combo(self) -> None:
        """Repopulates the filter combo with only the enabled algorithms."""
        current = self._active_noise_algo
        enabled = set(self.ticker_service.get_enabled_filters())

        self.combo_noise.blockSignals(True)
        self.combo_noise.clear()
        for algorithm in NoiseReductionAlgorithm:
            if algorithm == NoiseReductionAlgorithm.NONE or algorithm.value in enabled:
                self.combo_noise.addItem(algorithm.value, userData=algorithm)

        index = self.combo_noise.findData(current)
        if index < 0:
            index = self.combo_noise.findData(NoiseReductionAlgorithm.NONE)
            self._active_noise_algo = NoiseReductionAlgorithm.NONE
        self.combo_noise.setCurrentIndex(index)
        self.combo_noise.blockSignals(False)

    def _on_noise_algorithm_changed(self, index: int) -> None:
        algo = self.combo_noise.itemData(index)
        if algo:
            self._active_noise_algo = algo
            selected_symbol = self.ticker_list.get_selected_symbol()
            if selected_symbol:
                self._on_ticker_selected(selected_symbol)

    def _rebuild_swing_combo(self) -> None:
        """Repopulates the swing combo with only the enabled swing detection algorithms."""
        current = self._active_swing_algo
        enabled = set(self.ticker_service.get_enabled_swing_algorithms())

        self.combo_swing.blockSignals(True)
        self.combo_swing.clear()
        for algorithm in SwingAlgorithm:
            if algorithm.value in enabled:
                self.combo_swing.addItem(algorithm.value, userData=algorithm)

        index = self.combo_swing.findData(current)
        if index < 0:
            fallback = self.combo_swing.itemData(0)
            self._active_swing_algo = fallback if fallback else SwingAlgorithm.RANGE
            index = 0
        self.combo_swing.setCurrentIndex(index)
        self._update_swing_tooltip()
        self.combo_swing.blockSignals(False)

    def _on_swing_algorithm_changed(self, index: int) -> None:
        algorithm = self.combo_swing.itemData(index)
        if not algorithm:
            return
        self._active_swing_algo = algorithm
        self._update_swing_tooltip()
        self.trend_filter_bar.set_swing_algorithm(algorithm.value)
        self._refresh_ticker_list()
        self._update_swing_overlay()
        self.status_bar.showMessage(f"Swing bucketing updated using {algorithm.value}.")

    def _update_swing_tooltip(self) -> None:
        description = SWING_ALGORITHM_DESCRIPTIONS.get(self._active_swing_algo, "")
        name = self._active_swing_algo.value
        self.combo_swing.setToolTip(f"{name}\n{description}" if description else name)

    def _restore_summary_display(self) -> None:
        """Restores header card price/change text back to standard values."""
        summary = self._current_summary
        if not summary:
            return

        if summary.current_price is not None:
            self.lbl_price.setText(f"${summary.current_price:,.2f}")
            if summary.price_change is not None and summary.pct_change is not None:
                chg_str = f"{summary.price_change:+.2f} ({summary.pct_change:+.2f}%)"
                if summary.pct_change > 0:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changePositive")
                elif summary.pct_change < 0:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changeNegative")
                else:
                    self.lbl_change.setText(chg_str)
                    self.lbl_change.setObjectName("changeNeutral")
                self.lbl_change.setStyle(self.lbl_change.style())
        else:
            self.lbl_price.setText("--")
            self.lbl_change.setText("No data")
            self.lbl_change.setObjectName("changeNeutral")
            self.lbl_change.setStyle(self.lbl_change.style())

        self.lbl_info_range.setText(f"Range: {self._active_range.display_name}")
        self.lbl_last_sync.setText(f"Last Sync: {summary.last_updated or 'Never'}")

    def _on_chart_hover_changed(self, dt_str: str, price: float) -> None:
        """Dynamically updates header card to display exact hovered date & price."""
        self.lbl_price.setText(f"${price:,.2f}")
        self.lbl_last_sync.setText(f"Date: {dt_str}")

        if self._period_start_price and self._period_start_price > 0:
            diff = price - self._period_start_price
            pct = (diff / self._period_start_price) * 100.0
            chg_str = f"{diff:+.2f} ({pct:+.2f}%)"
            if pct > 0:
                self.lbl_change.setText(chg_str)
                self.lbl_change.setObjectName("changePositive")
            elif pct < 0:
                self.lbl_change.setText(chg_str)
                self.lbl_change.setObjectName("changeNegative")
            else:
                self.lbl_change.setText(chg_str)
                self.lbl_change.setObjectName("changeNeutral")
            self.lbl_change.setStyle(self.lbl_change.style())

    def _on_chart_hover_left(self) -> None:
        """Resets header card back to standard values when cursor leaves chart."""
        self._restore_summary_display()

    def _on_range_changed(self) -> None:
        btn = self.range_button_group.checkedButton()
        if not btn:
            return
        self._active_range = btn.property("time_range")
        self._refresh_ticker_list()
        selected_symbol = self.ticker_list.get_selected_symbol()
        if selected_symbol:
            self._on_ticker_selected(selected_symbol)

    def _on_refresh_chart(self) -> None:
        selected_symbol = self.ticker_list.get_selected_symbol()
        if selected_symbol:
            self._on_ticker_selected(selected_symbol)

    def _on_reset_view(self) -> None:
        self.chart_widget.reset_view()

    def _on_open_admin(self) -> None:
        dlg = TickerAdminDialog(self.ticker_service, self)
        if dlg.exec() == TickerAdminDialog.Accepted:
            self._load_initial_state()
            selected_symbol = self.ticker_list.get_selected_symbol()
            if selected_symbol:
                self._on_ticker_selected(selected_symbol)

    def _on_open_filter_settings(self) -> None:
        dlg = FilterSettingsDialog(self.ticker_service, self)
        if dlg.exec() == FilterSettingsDialog.Accepted:
            self._rebuild_noise_combo()
            selected_symbol = self.ticker_list.get_selected_symbol()
            if selected_symbol:
                self._on_ticker_selected(selected_symbol)

    def _on_open_swing_settings(self) -> None:
        dlg = SwingSettingsDialog(self.ticker_service, self)
        if dlg.exec() == SwingSettingsDialog.Accepted:
            self._rebuild_swing_combo()
            self.trend_filter_bar.set_swing_algorithm(self._active_swing_algo.value)
            self._refresh_ticker_list()
            self._update_swing_overlay()
            self.status_bar.showMessage(
                f"Swing settings saved. Bucketing updated using {self._active_swing_algo.value}."
            )

    def _on_update_clicked(self) -> None:
        enabled_configs = self.ticker_service.get_enabled_tickers()
        if not enabled_configs:
            QMessageBox.information(self, "No Enabled Tickers", "Please enable or add at least one ticker in Manage Tickers.")
            return

        progress_dlg = UpdateProgressDialog(enabled_configs, self)

        self._update_worker = UpdateWorker(self.sync_service, enabled_configs)
        self._update_worker.ticker_started.connect(progress_dlg.on_ticker_started)
        self._update_worker.ticker_finished.connect(progress_dlg.on_ticker_finished)
        self._update_worker.overall_completed.connect(progress_dlg.on_overall_completed)
        self._update_worker.overall_completed.connect(self._on_update_finished)

        self._update_worker.start()
        progress_dlg.exec()

    def _on_update_finished(self, success_count: int, fail_count: int) -> None:
        self.status_bar.showMessage(f"Update completed: {success_count} successful, {fail_count} failed.")
        curr_sym = self.ticker_list.get_selected_symbol()
        self._refresh_ticker_list(select_symbol=curr_sym)
        if curr_sym:
            self._on_ticker_selected(curr_sym)
