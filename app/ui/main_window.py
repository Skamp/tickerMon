import logging
import math
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
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
    QCheckBox,
)

from app.models.time_range import TimeRange
from app.models.chart_type import ChartType
from app.models.forecast import (
    Forecast,
    ForecastHorizon,
    DirectionalBias,
    forecast_matches_filter,
    normalize_forecast_filter,
)
from app.models.ticker import TickerConfig, TickerSummary
from app.services.ticker_service import TickerService
from app.services.market_data_service import (
    MarketDataService,
    count_trend_buckets,
    PERFORMANCE_RANGES,
)
from app.services.sync_service import SyncService
from app.services.noise_reduction import NoiseReductionAlgorithm, reduce_noise
from app.services.technical_indicators import (
    ATR_PERIOD,
    compute_atr,
    compute_atr_bands,
    compute_ema,
)
from app.services.market_structure import classify_structure, compute_label_positions
from app.services.swing_levels import compute_swing_levels
from app.services.earnings_service import EarningsService
from app.services.forecast_service import ForecastService
from app.services.forecast_engine import ForecastError
from app.services.swing_detection import (
    SwingAlgorithm,
    SwingRangeMode,
    SWING_ALGORITHM_DESCRIPTIONS,
    SWING_THRESHOLD_PCT,
    describe_swing_range,
    format_swing_params,
)
from app.utils.currency import format_price
from app.ui.ticker_list import (
    TickerListWidget,
    SORT_BY_TICKER,
    SORT_BY_DATE,
    SORT_BY_NAME,
    SORT_BY_PRICE,
    SORT_BY_PERF,
)
from app.ui.chart_widget import StockChartWidget
from app.ui.ticker_dialog import TickerAdminDialog
from app.ui.filter_settings_dialog import FilterSettingsDialog
from app.ui.swing_settings_dialog import SwingSettingsDialog
from app.ui.forecast_history_dialog import ForecastHistoryDialog
from app.ui.trend_filter_bar import TrendFilterBar
from app.ui.update_dialog import UpdateProgressDialog
from app.workers.update_worker import UpdateWorker
from app.workers.earnings_worker import EarningsWorker

logger = logging.getLogger(__name__)

INDICATOR_WARMUP_BARS = 260


class MainWindow(QMainWindow):
    def __init__(
        self,
        ticker_service: TickerService,
        market_data_service: MarketDataService,
        sync_service: SyncService,
        earnings_service: EarningsService,
        forecast_service: ForecastService,
    ):
        super().__init__()
        self.ticker_service = ticker_service
        self.market_data_service = market_data_service
        self.sync_service = sync_service
        self.earnings_service = earnings_service
        self.forecast_service = forecast_service

        self.setWindowTitle("tickerMon - Stock Market Terminal")
        self.resize(1480, 780)
        self.setMinimumSize(1240, 600)

        self._active_range = TimeRange.ONE_YEAR
        self._active_chart_type = ChartType.LINE
        self._active_noise_algo = NoiseReductionAlgorithm.NONE
        self._active_swing_algo = SwingAlgorithm.RANGE
        self._forecast_horizon = ForecastHorizon.OFF
        self._active_forecast: Optional[Forecast] = None
        self._displaying_saved_forecast = False
        self._forecast_filter = "off"
        self._current_summary: Optional[TickerSummary] = None
        self._period_start_price: Optional[float] = None
        self._update_worker: Optional[UpdateWorker] = None
        self._earnings_worker: Optional[EarningsWorker] = None
        self._earnings_events: List = []
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
        toolbar_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self._toolbar_frame = toolbar_frame
        toolbar_layout = QVBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)

        self._toolbar_row_a = QHBoxLayout()
        self._toolbar_row_a.setSpacing(12)
        self._toolbar_row_b = QHBoxLayout()
        self._toolbar_row_b.setSpacing(12)
        toolbar_layout.addLayout(self._toolbar_row_a)
        toolbar_layout.addLayout(self._toolbar_row_b)
        self._toolbar_stacked = False

        # S1: Update buttons (stacked: all tickers over new tickers)
        self._toolbar_section_updates = QWidget(toolbar_frame)
        self._toolbar_section_updates.setObjectName("toolbarSection")
        updates_layout = QVBoxLayout(self._toolbar_section_updates)
        updates_layout.setContentsMargins(0, 0, 0, 0)
        updates_layout.setSpacing(4)

        self.btn_update = QPushButton("Update all tickers", self._toolbar_section_updates)
        self.btn_update.setObjectName("updateButton")
        self.btn_update.setToolTip("Sync latest price data from Yahoo Finance (Ctrl+U)")
        self.btn_update.clicked.connect(self._on_update_clicked)
        updates_layout.addWidget(self.btn_update)

        self.btn_update_new = QPushButton("Update new tickers", self._toolbar_section_updates)
        self.btn_update_new.setObjectName("updateButton")
        self.btn_update_new.setToolTip("Download data only for tickers with no stored prices")
        self.btn_update_new.clicked.connect(self._on_update_new_clicked)
        updates_layout.addWidget(self.btn_update_new)

        self._toolbar_row_a.addWidget(self._toolbar_section_updates)

        # S2: Filter / Swing / Duration controls in a shared grid
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

        self._toolbar_section_filter = QWidget(toolbar_frame)
        self._toolbar_section_filter.setObjectName("toolbarSection")
        self._toolbar_section_filter.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        filter_grid = QGridLayout(self._toolbar_section_filter)
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(8)
        filter_grid.setVerticalSpacing(4)
        vcenter = Qt.AlignmentFlag.AlignVCenter

        noise_label = QLabel("Filter:", self._toolbar_section_filter)
        noise_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        filter_grid.addWidget(noise_label, 0, 0, alignment=vcenter)

        self.combo_noise = QComboBox(self._toolbar_section_filter)
        self.combo_noise.setToolTip("Apply noise reduction algorithm overlay to price graph")
        self.combo_noise.setStyleSheet(combo_style)

        self._rebuild_noise_combo()
        self.combo_noise.currentIndexChanged.connect(self._on_noise_algorithm_changed)
        filter_grid.addWidget(self.combo_noise, 0, 1, alignment=vcenter)

        self.btn_filter_settings = QPushButton("Filters…", self._toolbar_section_filter)
        self.btn_filter_settings.setToolTip("Choose which filters appear in the Filter list")
        self.btn_filter_settings.clicked.connect(self._on_open_filter_settings)
        filter_grid.addWidget(self.btn_filter_settings, 0, 2, alignment=vcenter)

        swing_label = QLabel("Swing:", self._toolbar_section_filter)
        swing_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        filter_grid.addWidget(swing_label, 1, 0, alignment=vcenter)

        self.combo_swing = QComboBox(self._toolbar_section_filter)
        self.combo_swing.setToolTip("Algorithm used to detect the swing bucket")
        self.combo_swing.setStyleSheet(combo_style)

        self._rebuild_swing_combo()
        self.combo_swing.currentIndexChanged.connect(self._on_swing_algorithm_changed)
        filter_grid.addWidget(self.combo_swing, 1, 1, alignment=vcenter)

        swing_trailing = QHBoxLayout()
        swing_trailing.setSpacing(8)
        self.btn_swing_settings = QPushButton("Swing…", self._toolbar_section_filter)
        self.btn_swing_settings.setToolTip("Enable swing algorithms and configure their parameters")
        self.btn_swing_settings.clicked.connect(self._on_open_swing_settings)
        swing_trailing.addWidget(self.btn_swing_settings)

        self.chk_structure_labels = QCheckBox("Structure labels", self._toolbar_section_filter)
        self.chk_structure_labels.setToolTip(
            "Show market structure labels (HH / HL / LH / LL / M)\non confirmed swing pivots."
        )
        self.chk_structure_labels.setChecked(True)
        self.chk_structure_labels.toggled.connect(self._on_structure_labels_toggled)
        swing_trailing.addWidget(self.chk_structure_labels)
        filter_grid.addLayout(swing_trailing, 1, 2, alignment=vcenter)

        duration_label = QLabel("Duration:", self._toolbar_section_filter)
        duration_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        filter_grid.addWidget(duration_label, 2, 0, alignment=vcenter)

        self.combo_swing_range_mode = QComboBox(self._toolbar_section_filter)
        for swing_range_mode in SwingRangeMode:
            self.combo_swing_range_mode.addItem(swing_range_mode.value, userData=swing_range_mode.value)
        self.combo_swing_range_mode.setStyleSheet(combo_style)
        self.combo_swing_range_mode.setToolTip(
            "Minimum duration: keep swings taking at least X\n"
            "Maximum duration: keep swings completing within X\n"
            "Lookback window: only detect swings in the last X\n"
            "Duration window: keep swings between X and Y"
        )
        filter_grid.addWidget(self.combo_swing_range_mode, 2, 1, alignment=vcenter)

        duration_trailing = QHBoxLayout()
        duration_trailing.setSpacing(8)
        self.spin_swing_range = QSpinBox(self._toolbar_section_filter)
        self.spin_swing_range.setRange(0, 520)
        self.spin_swing_range.setMinimumWidth(66)
        self.spin_swing_range.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.spin_swing_range.setSpecialValueText("Off")
        self.spin_swing_range.setToolTip(
            "Detect only swings inside this time range (weeks).\n"
            "0 = Off (no range filter)."
        )
        duration_trailing.addWidget(self.spin_swing_range)

        self.lbl_swing_range_dash = QLabel("-", self._toolbar_section_filter)
        self.lbl_swing_range_dash.setStyleSheet("color: #8b90a0;")
        duration_trailing.addWidget(self.lbl_swing_range_dash)

        self.spin_swing_range_max = QSpinBox(self._toolbar_section_filter)
        self.spin_swing_range_max.setRange(1, 520)
        self.spin_swing_range_max.setMinimumWidth(66)
        self.spin_swing_range_max.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.spin_swing_range_max.setToolTip("Upper bound of the swing duration window.")
        duration_trailing.addWidget(self.spin_swing_range_max)

        self.lbl_swing_range_unit = QLabel("weeks", self._toolbar_section_filter)
        self.lbl_swing_range_unit.setStyleSheet("color: #8b90a0;")
        duration_trailing.addWidget(self.lbl_swing_range_unit)
        filter_grid.addLayout(duration_trailing, 2, 2, alignment=vcenter)

        self._load_swing_range_settings()

        self.spin_swing_range.valueChanged.connect(self._on_swing_range_changed)
        self.spin_swing_range_max.valueChanged.connect(self._on_swing_range_changed)
        self.combo_swing_range_mode.currentIndexChanged.connect(self._on_swing_range_changed)

        self._toolbar_row_a.addWidget(self._toolbar_section_filter)

        # S3: Range / Forecast / Chart-type controls in a shared grid
        self._toolbar_section_range = QWidget(toolbar_frame)
        self._toolbar_section_range.setObjectName("toolbarSection")
        self._toolbar_section_range.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        range_grid = QGridLayout(self._toolbar_section_range)
        range_grid.setContentsMargins(0, 0, 0, 0)
        range_grid.setHorizontalSpacing(8)
        range_grid.setVerticalSpacing(4)

        range_label = QLabel("Range:", self._toolbar_section_range)
        range_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        range_grid.addWidget(range_label, 0, 0, alignment=vcenter)

        range_row = QHBoxLayout()
        range_row.setSpacing(12)

        self.range_button_group = QButtonGroup(self)
        self.range_button_group.setExclusive(True)

        for tr in [
            TimeRange.ONE_WEEK,
            TimeRange.TWO_WEEKS,
            TimeRange.THREE_WEEKS,
            TimeRange.ONE_MONTH,
            TimeRange.SIX_MONTHS,
            TimeRange.ONE_YEAR,
            TimeRange.FIVE_YEARS,
        ]:
            btn = QPushButton(tr.value, self._toolbar_section_range)
            btn.setCheckable(True)
            btn.setProperty("time_range", tr)
            if tr == TimeRange.ONE_YEAR:
                btn.setChecked(True)
            btn.clicked.connect(self._on_range_changed)
            self.range_button_group.addButton(btn)
            range_row.addWidget(btn)

        range_grid.addLayout(range_row, 0, 1, alignment=vcenter)

        forecast_label = QLabel("Forecast:", self._toolbar_section_range)
        forecast_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        range_grid.addWidget(forecast_label, 1, 0, alignment=vcenter)

        forecast_row = QHBoxLayout()
        forecast_row.setSpacing(8)

        self.combo_forecast = QComboBox(self._toolbar_section_range)
        self.combo_forecast.setToolTip(
            "Show a price projection for the selected horizon.\n"
            "Forecasts are estimates generated from local data — not advice."
        )
        for horizon in ForecastHorizon:
            self.combo_forecast.addItem(horizon.value, userData=horizon)
        self.combo_forecast.setStyleSheet("""
            QComboBox {
                background-color: #252836;
                color: #e1e3ea;
                border: 1px solid #323647;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: 600;
                min-width: 96px;
            }
            QComboBox:hover {
                border-color: #454b61;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1c24;
                color: #e1e3ea;
                selection-background-color: #2962ff;
            }
        """)
        self.combo_forecast.currentIndexChanged.connect(self._on_forecast_horizon_changed)
        forecast_row.addWidget(self.combo_forecast)

        self.btn_forecast_generate = QPushButton("Generate", self._toolbar_section_range)
        self.btn_forecast_generate.setToolTip(
            "Generate a forecast for the selected ticker using the current\n"
            "filter and swing configuration (does not save it)."
        )
        self.btn_forecast_generate.clicked.connect(self._on_generate_forecast_clicked)
        forecast_row.addWidget(self.btn_forecast_generate)

        self.btn_forecast_save = QPushButton("Save", self._toolbar_section_range)
        self.btn_forecast_save.setToolTip("Persist the current forecast to the local database")
        self.btn_forecast_save.clicked.connect(self._on_save_forecast_clicked)
        forecast_row.addWidget(self.btn_forecast_save)

        self.btn_forecast_history = QPushButton("History…", self._toolbar_section_range)
        self.btn_forecast_history.setToolTip("Browse, evaluate and delete saved forecasts")
        self.btn_forecast_history.clicked.connect(self._on_open_forecast_history)
        forecast_row.addWidget(self.btn_forecast_history)

        self.btn_forecast_generate.setEnabled(False)
        self.btn_forecast_save.setEnabled(False)

        range_grid.addLayout(forecast_row, 1, 1, alignment=vcenter)

        # Price Chart Type Selector (Line / Candle / Baseline)
        chart_label = QLabel("Chart type:", self._toolbar_section_range)
        chart_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        range_grid.addWidget(chart_label, 2, 0, alignment=vcenter)

        self.combo_chart_type = QComboBox(self._toolbar_section_range)
        self.combo_chart_type.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_chart_type.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        for chart_type in ChartType:
            self.combo_chart_type.addItem(chart_type.value, userData=chart_type)
        self.combo_chart_type.setStyleSheet("""
            QComboBox {
                background-color: #252836;
                color: #e1e3ea;
                border: 1px solid #323647;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: 600;
                min-width: 84px;
            }
            QComboBox:hover {
                border-color: #454b61;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1c24;
                color: #e1e3ea;
                selection-background-color: #2962ff;
            }
        """)
        self.combo_chart_type.setToolTip(
            "Price chart rendering style.\n"
            "Line: close price line (default).\n"
            "Candle: OHLC candlesticks.\n"
            "Baseline: close relative to the first price in the range."
        )
        self.combo_chart_type.currentIndexChanged.connect(self._on_chart_type_changed)
        range_grid.addWidget(self.combo_chart_type, 2, 1, alignment=vcenter)

        self._toolbar_row_a.addWidget(self._toolbar_section_range)

        self._toolbar_row_a.addStretch()

        # S4: trailing actions
        self._toolbar_section_actions = QWidget(toolbar_frame)
        self._toolbar_section_actions.setObjectName("toolbarSection")
        self._toolbar_section_actions.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        actions_layout = QHBoxLayout(self._toolbar_section_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)

        self.btn_admin = QPushButton("Manage Tickers", self._toolbar_section_actions)
        self.btn_admin.setToolTip("Add, remove, or reorder tickers (Ctrl+T)")
        self.btn_admin.clicked.connect(self._on_open_admin)
        actions_layout.addWidget(self.btn_admin)

        self.btn_reset_view = QPushButton("Reset Zoom", self._toolbar_section_actions)
        self.btn_reset_view.setToolTip("Reset chart zoom and pan")
        self.btn_reset_view.clicked.connect(self._on_reset_view)
        actions_layout.addWidget(self.btn_reset_view)

        self._toolbar_row_a.addWidget(self._toolbar_section_actions)

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
        sidebar_header.setStyleSheet("font-size: 8.25pt; font-weight: bold; color: #8b90a0; letter-spacing: 1px;")
        sidebar_layout.addWidget(sidebar_header)

        sort_row = QHBoxLayout()
        sort_row.setSpacing(6)

        sort_label = QLabel("Sort:", sidebar_frame)
        sort_label.setStyleSheet("color: #8b90a0; font-weight: bold;")
        sort_row.addWidget(sort_label)

        self.combo_sort = QComboBox(sidebar_frame)
        self.combo_sort.setStyleSheet("""
            QComboBox {
                background-color: #252836;
                color: #e1e3ea;
                border: 1px solid #323647;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 600;
            }
            QComboBox:hover {
                border-color: #454b61;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1c24;
                color: #e1e3ea;
                selection-background-color: #2962ff;
            }
        """)
        self.combo_sort.addItem("Sort by ticker", userData=SORT_BY_TICKER)
        self.combo_sort.addItem("Sort by date", userData=SORT_BY_DATE)
        self.combo_sort.addItem("Sort by company name", userData=SORT_BY_NAME)
        self.combo_sort.addItem("Sort by price", userData=SORT_BY_PRICE)
        self.combo_sort.addItem("Sort by daily performance", userData=SORT_BY_PERF)
        self.combo_sort.setToolTip(
            "Sort criterion for the market watch list.\n"
            "Date = the day the ticker was added to the tool.\n"
            "Price / performance = last stored values; unknown values are listed last."
        )
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.combo_sort, 1)

        # Segmented sort direction buttons: [ ▲ Ascending ] [ ▼ Descending ]
        direction_container = QWidget(sidebar_frame)
        direction_layout = QHBoxLayout(direction_container)
        direction_layout.setContentsMargins(0, 0, 0, 0)
        direction_layout.setSpacing(0)

        self.sort_direction_group = QButtonGroup(self)
        self.sort_direction_group.setExclusive(True)

        self.btn_sort_asc = QPushButton("▲ Ascending", direction_container)
        self.btn_sort_asc.setObjectName("btnSortAsc")
        self.btn_sort_asc.setCheckable(True)
        self.btn_sort_asc.setChecked(True)
        self.btn_sort_asc.setFocusPolicy(Qt.NoFocus)
        self.btn_sort_asc.setToolTip("Sort in ascending order (A–Z, oldest first, lowest first)")
        self.btn_sort_asc.setStyleSheet("""
            QPushButton#btnSortAsc {
                background-color: #252836;
                color: #8b90a0;
                border: 1px solid #323647;
                border-right: none;
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                padding: 4px 6px;
                font-size: 8.25pt;
                font-weight: 600;
            }
            QPushButton#btnSortAsc:hover {
                background-color: #323647;
                color: #e1e3ea;
                border-color: #454b61;
            }
            QPushButton#btnSortAsc:checked {
                background-color: #2962ff;
                border-color: #2962ff;
                color: #ffffff;
            }
        """)

        self.btn_sort_desc = QPushButton("▼ Descending", direction_container)
        self.btn_sort_desc.setObjectName("btnSortDesc")
        self.btn_sort_desc.setCheckable(True)
        self.btn_sort_desc.setFocusPolicy(Qt.NoFocus)
        self.btn_sort_desc.setToolTip("Sort in descending order (Z–A, newest first, highest first)")
        self.btn_sort_desc.setStyleSheet("""
            QPushButton#btnSortDesc {
                background-color: #252836;
                color: #8b90a0;
                border: 1px solid #323647;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                padding: 4px 6px;
                font-size: 8.25pt;
                font-weight: 600;
            }
            QPushButton#btnSortDesc:hover {
                background-color: #323647;
                color: #e1e3ea;
                border-color: #454b61;
            }
            QPushButton#btnSortDesc:checked {
                background-color: #2962ff;
                border-color: #2962ff;
                color: #ffffff;
            }
        """)

        self.sort_direction_group.addButton(self.btn_sort_asc)
        self.sort_direction_group.addButton(self.btn_sort_desc)
        direction_layout.addWidget(self.btn_sort_asc)
        direction_layout.addWidget(self.btn_sort_desc)
        self.btn_sort_asc.clicked.connect(self._on_sort_direction_changed)
        self.btn_sort_desc.clicked.connect(self._on_sort_direction_changed)
        sort_row.addWidget(direction_container)

        sidebar_layout.addLayout(sort_row)

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
        self.lbl_high_low.setStyleSheet("color: #8b90a0; font-size: 9pt; font-weight: bold;")
        self.lbl_info_range = QLabel("Range: 1 Year", right_panel)
        self.lbl_info_range.setStyleSheet("color: #8b90a0; font-size: 8.25pt;")
        self.lbl_last_sync = QLabel("Last Sync: Never", right_panel)
        self.lbl_last_sync.setStyleSheet("color: #8b90a0; font-size: 8.25pt;")
        info_box.addWidget(self.lbl_high_low)
        info_box.addWidget(self.lbl_info_range)
        info_box.addWidget(self.lbl_last_sync)
        self.header_card.addLayout(info_box)

        right_layout.addLayout(self.header_card)

        # Performance strip: win/loss % for fixed lookback ranges
        perf_row = QHBoxLayout()
        perf_row.setSpacing(4)

        perf_title = QLabel("PERFORMANCE", right_panel)
        perf_title.setStyleSheet(
            "font-size: 8.25pt; font-weight: bold; color: #8b90a0; letter-spacing: 1px;"
        )
        perf_title.setAlignment(Qt.AlignVCenter)
        perf_row.addWidget(perf_title)
        perf_row.setAlignment(perf_title, Qt.AlignVCenter)
        perf_row.addSpacing(12)

        self.lbl_performance: Dict[str, QLabel] = {}
        for key, _ in PERFORMANCE_RANGES:
            cell = QVBoxLayout()
            cell.setSpacing(0)

            range_label = QLabel(key, right_panel)
            range_label.setAlignment(Qt.AlignCenter)
            range_label.setStyleSheet("font-size: 7.5pt; font-weight: bold; color: #8b90a0;")
            range_label.setToolTip(f"Price change over the last {key} (local data)")

            value_label = QLabel("--", right_panel)
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setObjectName("changeNeutral")
            value_label.setToolTip(f"Price change over the last {key} (local data)")

            cell.addWidget(range_label)
            cell.addWidget(value_label)
            perf_row.addLayout(cell, 1)

            self.lbl_performance[key] = value_label

        right_layout.addLayout(perf_row)

        # Horizontal Divider Line
        line = QFrame(right_panel)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #282b36;")
        right_layout.addWidget(line)

        # Chart Widget
        self.chart_widget = StockChartWidget(right_panel)
        self.chart_widget.hover_changed.connect(self._on_chart_hover_changed)
        self.chart_widget.hover_left.connect(self._on_chart_hover_left)
        self.chart_widget.forecast_annotation_anchor_changed.connect(
            self.ticker_service.set_forecast_annotation_anchor
        )
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

        QTimer.singleShot(0, self._arrange_toolbar)

    def _arrange_toolbar(self) -> None:
        """Keeps the toolbar on one row when it fits; stacks S3/S4 otherwise."""
        available = (
            self._toolbar_frame.width()
            - self._toolbar_frame.contentsMargins().left()
            - self._toolbar_frame.contentsMargins().right()
        )
        if available <= 0:
            return

        sections_single = (
            self._toolbar_section_updates,
            self._toolbar_section_filter,
            self._toolbar_section_range,
            self._toolbar_section_actions,
        )
        spacing = self._toolbar_row_a.spacing()
        single_row_width = sum(
            section.sizeHint().width() for section in sections_single
        ) + spacing * (len(sections_single) - 1)

        stacked = single_row_width > available
        if stacked == self._toolbar_stacked:
            return
        self._toolbar_stacked = stacked

        for row in (self._toolbar_row_a, self._toolbar_row_b):
            while row.count():
                row.takeAt(0)

        row_a = self._toolbar_row_a
        row_b = self._toolbar_row_b

        row_a.addWidget(self._toolbar_section_updates)
        row_a.addWidget(self._toolbar_section_filter)
        row_a.addStretch()

        if stacked:
            row_b.addWidget(self._toolbar_section_range)
            row_b.addStretch()
            row_b.addWidget(self._toolbar_section_actions)
        else:
            row_a.addWidget(self._toolbar_section_range)
            row_a.addWidget(self._toolbar_section_actions)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrange_toolbar()

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

        self._active_chart_type = self.ticker_service.get_chart_type()
        chart_index = self.combo_chart_type.findData(self._active_chart_type)
        if chart_index >= 0:
            self.combo_chart_type.blockSignals(True)
            self.combo_chart_type.setCurrentIndex(chart_index)
            self.combo_chart_type.blockSignals(False)

        self.chk_structure_labels.blockSignals(True)
        self.chk_structure_labels.setChecked(self.ticker_service.get_show_structure_labels())
        self.chart_widget.set_structure_labels_visible(self.chk_structure_labels.isChecked())
        self.chk_structure_labels.blockSignals(False)

        self._forecast_horizon = self.ticker_service.get_forecast_horizon()
        forecast_index = self.combo_forecast.findData(self._forecast_horizon)
        self.combo_forecast.blockSignals(True)
        self.combo_forecast.setCurrentIndex(forecast_index if forecast_index >= 0 else 0)
        self.combo_forecast.blockSignals(False)
        self._update_forecast_buttons()
        self.chart_widget.set_forecast_annotation_anchor(
            self.ticker_service.get_forecast_annotation_anchor()
        )

        self._forecast_filter = "off"
        self._apply_forecast_filter()

        saved_criterion = self.ticker_service.get_sort_criterion()
        saved_direction = self.ticker_service.get_sort_direction()
        sort_index = self.combo_sort.findData(saved_criterion)
        self.combo_sort.blockSignals(True)
        self.combo_sort.setCurrentIndex(sort_index if sort_index >= 0 else 0)
        self.combo_sort.blockSignals(False)

        self.sort_direction_group.blockSignals(True)
        if saved_direction == "desc":
            self.btn_sort_desc.setChecked(True)
        else:
            self.btn_sort_asc.setChecked(True)
        self.sort_direction_group.blockSignals(False)

        self.ticker_list.set_sort(saved_criterion, saved_direction == "asc")

        self._refresh_ticker_list(select_symbol=target_ticker)

        # Evaluate any pending forecasts against locally stored data (no network).
        try:
            evaluated, unavailable, pending = self.forecast_service.evaluate_on_startup()
            if evaluated or unavailable:
                logger.info(
                    f"Startup forecast evaluation: {evaluated} evaluated, "
                    f"{unavailable} unavailable, {pending} pending."
                )
        except Exception as e:
            logger.warning(f"Startup forecast evaluation failed: {e}")

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

    def _on_sort_changed(self, index: int) -> None:
        criterion = self.combo_sort.itemData(index)
        if not criterion:
            return
        ascending = self.btn_sort_asc.isChecked()
        self.ticker_service.set_sort_criterion(criterion)
        self.ticker_list.set_sort(criterion, ascending)
        dir_str = "ascending" if ascending else "descending"
        self.status_bar.showMessage(
            f"Market watch sorted by {self.combo_sort.itemText(index).lower()} ({dir_str})."
        )

    def _on_sort_direction_changed(self) -> None:
        criterion = self.combo_sort.currentData() or SORT_BY_TICKER
        ascending = self.btn_sort_asc.isChecked()
        self.ticker_service.set_sort_direction("asc" if ascending else "desc")
        self.ticker_list.set_sort(criterion, ascending)
        dir_str = "ascending" if ascending else "descending"
        crit_text = self.combo_sort.currentText().lower()
        self.status_bar.showMessage(
            f"Market watch sorted by {crit_text} ({dir_str})."
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
        self.chart_widget.set_currency(summary.currency)
        self.lbl_symbol.setText(summary.symbol)
        self.lbl_company.setText(summary.company_name)

        self._restore_summary_display()
        self._update_performance_display()

        # Update PyQtGraph Chart (Offline SQLite Query)
        timestamps, prices, date_labels = self.market_data_service.get_chart_data(symbol, self._active_range)
        self._chart_timestamps = timestamps
        self._chart_prices = prices

        if not timestamps or not prices:
            self._period_start_price = None
            self.lbl_high_low.setText("High: -- | Low: --")
            self.chart_widget.clear_overlay()
            self.chart_widget.clear_atr_overlay()
            self.chart_widget.clear_swing_overlay()
            self.chart_widget.clear_swing_levels()
            self.chart_widget.clear_structure_labels()
            self.chart_widget.clear_earnings_events()
            self._earnings_events = []
            self._clear_forecast_overlay()
            self.chart_widget.show_empty_state(
                True,
                f"No local market data available for '{symbol}'.\nPress 'Update all tickers' (Ctrl+U) to download prices from Yahoo Finance."
            )
            self.status_bar.showMessage(f"No local data stored for {symbol}.")
        else:
            self._period_start_price = prices[0]
            hi_val, lo_val = max(prices), min(prices)
            self.lbl_high_low.setText(
                f"High: {format_price(hi_val, summary.currency)} | Low: {format_price(lo_val, summary.currency)}"
            )

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

            ohlc = None
            opens, highs, lows = self.market_data_service.get_chart_ohlcv(
                symbol, self._active_range
            )
            if self._active_chart_type == ChartType.CANDLE:
                ohlc = (opens, highs, lows)
            self.chart_widget.set_data(
                timestamps,
                prices,
                date_labels,
                line_color=color,
                chart_type=self._active_chart_type,
                ohlc=ohlc,
            )

            # Volume bars from the same local OHLCV rows (no extra API call)
            volumes, opens_v, closes_v = self.market_data_service.get_chart_volume(
                symbol, self._active_range
            )
            self.chart_widget.set_volume_data(timestamps, volumes, opens_v, closes_v, date_labels)

            # Apply active noise-reduction / technical-indicator overlay
            self._apply_active_noise_reduction(timestamps, prices)

            # Draw detected swing pivots, structure labels and swing levels
            self._update_swing_overlay()

            # Earnings markers from the local cache (network refresh is async)
            self._load_earnings_for_symbol(symbol, summary.company_name)

            # Forecast projection for the active horizon (local data only)
            if self._forecast_horizon != ForecastHorizon.OFF:
                self._regenerate_forecast()
            elif not (
                self._displaying_saved_forecast
                and self._active_forecast is not None
                and self._active_forecast.ticker == symbol
            ):
                self._clear_forecast_overlay()

            self.status_bar.showMessage(f"Loaded {len(prices)} historical points for {symbol} ({self._active_range.display_name}).")

    def _apply_active_noise_reduction(self, timestamps: List[float], prices: List[float]) -> None:
        """Applies the active filter: noise reduction curve, EMA 20 or ATR bands."""
        algorithm = self._active_noise_algo
        if algorithm == NoiseReductionAlgorithm.NONE or not timestamps:
            self.chart_widget.clear_overlay()
            self.chart_widget.clear_atr_overlay()
            return

        if algorithm in (NoiseReductionAlgorithm.ATR2, NoiseReductionAlgorithm.ATR4):
            self.chart_widget.clear_overlay()
            self._apply_atr_overlay(timestamps, prices, algorithm)
            return

        self.chart_widget.clear_atr_overlay()

        if algorithm == NoiseReductionAlgorithm.EMA20:
            self._apply_ema20_overlay(timestamps, prices)
            return

        red_x, red_y = reduce_noise(algorithm, timestamps, prices)
        self.chart_widget.set_overlay_data(red_x, red_y)

    def _apply_ema20_overlay(self, timestamps: List[float], prices: List[float]) -> None:
        """EMA 20 seeded on warm-up history so left-edge values are accurate."""
        ema = self._compute_warmup_indicator(timestamps, prices, lambda closes: compute_ema(closes, 20))
        if ema is None:
            self.chart_widget.clear_overlay()
            return
        self.chart_widget.set_overlay_data(timestamps, ema, color="#26c6da", label="EMA20")

    def _apply_forecast_filter_extension(self) -> None:
        """Extends the active filter curve into the forecast region.

        Continues the active filter curve seamlessly from the last historical
        filter point through the forecast central path, passing the resulting
        projection to the chart as a dashed continuation. ATR variants are
        skipped because they require OHLCV data that forecasts do not provide.
        """
        forecast = self._active_forecast
        algorithm = self._active_noise_algo

        if (
            forecast is None
            or not forecast.path_epochs
            or algorithm == NoiseReductionAlgorithm.NONE
            or algorithm in (NoiseReductionAlgorithm.ATR2, NoiseReductionAlgorithm.ATR4)
            or not self._chart_timestamps
            or not self._chart_prices
        ):
            self.chart_widget.clear_forecast_filter_curve()
            return

        hist_ts = self._chart_timestamps
        hist_prices = self._chart_prices
        fc_ts = [float(t) for t in forecast.path_epochs]
        fc_prices = [float(p) for p in forecast.path_central]
        n_fc = len(fc_ts)
        if n_fc < 1 or len(fc_prices) < 1:
            self.chart_widget.clear_forecast_filter_curve()
            return

        color = "#26c6da" if algorithm == NoiseReductionAlgorithm.EMA20 else "#ffab00"

        _ema_spans = {
            NoiseReductionAlgorithm.EMA20: 20,
            NoiseReductionAlgorithm.EMA: 10,
            NoiseReductionAlgorithm.EMA50: 50,
            NoiseReductionAlgorithm.EMA200: 200,
        }

        if algorithm in _ema_spans:
            last_ema = None
            if self.chart_widget._overlay_y:
                val = self.chart_widget._overlay_y[-1]
                if val is not None and math.isfinite(val):
                    last_ema = float(val)
            if last_ema is None:
                if algorithm == NoiseReductionAlgorithm.EMA20:
                    warm = self._compute_warmup_indicator(
                        hist_ts, hist_prices, lambda closes: compute_ema(closes, 20)
                    )
                    last_ema = float(warm[-1]) if warm and warm[-1] is not None else float(hist_prices[-1])
                else:
                    _, red_y = reduce_noise(algorithm, hist_ts, hist_prices)
                    last_ema = float(red_y[-1]) if red_y else float(hist_prices[-1])

            span = _ema_spans[algorithm]
            alpha = 2.0 / (span + 1.0)
            ext_ts = [fc_ts[0]]
            ext_prices = [last_ema]
            for t in range(1, n_fc):
                last_ema = alpha * fc_prices[t] + (1.0 - alpha) * last_ema
                ext_ts.append(fc_ts[t])
                ext_prices.append(last_ema)
        else:
            if fc_ts and hist_ts and fc_ts[0] == hist_ts[-1]:
                feed_ts = hist_ts + fc_ts[1:]
                feed_prices = hist_prices + fc_prices[1:]
            else:
                feed_ts = hist_ts + fc_ts
                feed_prices = hist_prices + fc_prices

            red_x, red_y = reduce_noise(algorithm, feed_ts, feed_prices)
            if not red_x or not red_y:
                self.chart_widget.clear_forecast_filter_curve()
                return

            if len(red_x) == len(feed_ts):
                ext_ts = list(red_x[-n_fc:])
                ext_prices = list(red_y[-n_fc:])
            else:
                pts = [(x, y) for x, y in zip(red_x, red_y) if x >= fc_ts[0]]
                if pts:
                    ext_ts = [p[0] for p in pts]
                    ext_prices = [p[1] for p in pts]
                    if self.chart_widget._overlay_y and ext_ts[0] > fc_ts[0]:
                        ext_ts.insert(0, fc_ts[0])
                        ext_prices.insert(0, float(self.chart_widget._overlay_y[-1]))
                else:
                    self.chart_widget.clear_forecast_filter_curve()
                    return

            if self.chart_widget._overlay_y and ext_prices:
                ext_prices[0] = float(self.chart_widget._overlay_y[-1])

        self.chart_widget.set_forecast_filter_curve(ext_ts, ext_prices, color=color)

    def _apply_atr_overlay(
        self,
        timestamps: List[float],
        prices: List[float],
        algorithm: NoiseReductionAlgorithm,
    ) -> None:
        """Close ± N×ATR14 volatility bands from a shared warm-up ATR series."""
        multiplier = 2.0 if algorithm == NoiseReductionAlgorithm.ATR2 else 4.0
        symbol = self.ticker_list.get_selected_symbol() or ""
        n = len(prices)

        def build(closes_tail, highs_tail, lows_tail):
            atr = compute_atr(highs_tail, lows_tail, closes_tail, period=ATR_PERIOD)
            upper, lower = compute_atr_bands(closes_tail, atr, multiplier)
            return upper, lower

        result = self._compute_warmup_ohlc_indicator(
            symbol, n, build
        )
        if result is None:
            self.chart_widget.clear_atr_overlay()
            return
        upper, lower = result
        if all(v is None for v in upper):
            self.chart_widget.clear_atr_overlay()
            return

        label = "ATR14 x 2" if algorithm == NoiseReductionAlgorithm.ATR2 else "ATR14 x 4"
        color = "#29b6f6" if algorithm == NoiseReductionAlgorithm.ATR2 else "#ab47bc"
        self.chart_widget.set_atr_overlay(timestamps, upper, lower, label, color)

    def _compute_warmup_indicator(self, timestamps, prices, compute):
        """Runs ``compute`` on warm-up closes, returning the visible-range tail."""
        symbol = self.ticker_list.get_selected_symbol() or ""
        n = len(prices)
        warm = self.market_data_service.get_warmup_ohlcv(
            symbol, self._active_range, warmup_bars=INDICATOR_WARMUP_BARS
        )
        closes = warm[3]
        values = compute(closes)
        if len(values) >= n:
            tail = values[-n:]
        else:
            tail = compute(prices)
        if len(tail) != n:
            return None
        return tail

    def _compute_warmup_ohlc_indicator(self, symbol, n, build):
        """Runs ``build(closes, highs, lows)`` on warm-up OHLC, sliced to n bars."""
        warm = self.market_data_service.get_warmup_ohlcv(
            symbol, self._active_range, warmup_bars=INDICATOR_WARMUP_BARS
        )
        opens, highs, lows, closes = warm
        if len(closes) < n:
            return None
        return build(closes[-n:], highs[-n:], lows[-n:])

    def _update_swing_overlay(self) -> None:
        """Draws the pivots detected by the active swing algorithm on the chart."""
        if not self._chart_timestamps or not self._chart_prices:
            self.chart_widget.clear_swing_overlay()
            self.chart_widget.clear_swing_levels()
            self.chart_widget.clear_structure_labels()
            return

        algorithm = self._active_swing_algo
        params = self.ticker_service.get_swing_params(algorithm)
        range_settings = self.ticker_service.get_swing_range_settings()
        symbol = self.ticker_list.get_selected_symbol() or ""
        timestamps = self._chart_timestamps
        prices = self._chart_prices
        pivots, legs = self.market_data_service.detect_swing_overlay(
            symbol,
            self._active_range,
            prices,
            timestamps,
            algorithm,
            params,
            range_settings,
        )
        title = f"Swing: {algorithm.value} ({len(pivots)} pivots)"
        details = (
            f"{format_swing_params(algorithm, params)}\n"
            f"Swing range: {describe_swing_range(range_settings)}"
        )
        self.chart_widget.set_swing_overlay(timestamps, prices, pivots, title, details, legs)

        # Market structure labels on the same confirmed pivots
        if self.ticker_service.get_show_structure_labels():
            macro_threshold = params.get("min_swing_pct", SWING_THRESHOLD_PCT)
            structure_points = classify_structure(
                pivots, prices, macro_threshold_pct=macro_threshold
            )
            placements = compute_label_positions(structure_points, timestamps, prices)
            self.chart_widget.set_structure_labels(placements)
        else:
            self.chart_widget.clear_structure_labels()

        # Latest confirmed swing high/low levels with distances and crossing status
        opens, highs, lows = self.market_data_service.get_chart_ohlcv(symbol, self._active_range)
        reference_close = prices[-1]
        currency = self._current_summary.currency if self._current_summary else None
        high_level, low_level = compute_swing_levels(
            pivots,
            prices,
            reference_close,
            highs=highs,
            lows=lows,
            closes=prices,
            currency_code=currency,
        )
        self.chart_widget.set_swing_levels(high_level, low_level, reference_close)

    def _load_earnings_for_symbol(self, symbol: str, company_name: Optional[str]) -> None:
        """Shows cached earnings markers and refreshes them in the background when stale."""
        events = self.earnings_service.get_events(symbol)
        self._earnings_events = events
        self.chart_widget.set_earnings_events(events, symbol, company_name)
        if self.earnings_service.is_stale(symbol):
            self._start_earnings_refresh(symbol)

    def _start_earnings_refresh(self, symbol: str) -> None:
        if self._earnings_worker is not None and self._earnings_worker.isRunning():
            return
        self._earnings_worker = EarningsWorker(self.earnings_service, symbol, self)
        self._earnings_worker.finished_events.connect(self._on_earnings_refreshed)
        self._earnings_worker.start()

    def _on_earnings_refreshed(self, symbol: str, events) -> None:
        if symbol != (self.ticker_list.get_selected_symbol() or ""):
            return
        self._earnings_events = list(events) if events else []
        company = self._current_summary.company_name if self._current_summary else None
        self.chart_widget.set_earnings_events(self._earnings_events, symbol, company)
        if self._earnings_events:
            self.status_bar.showMessage(
                f"Earnings events updated for {symbol} ({len(self._earnings_events)} events)."
            )

    def _on_structure_labels_toggled(self, checked: bool) -> None:
        """Toggles label visibility without recalculating the swing structure."""
        self.ticker_service.set_show_structure_labels(checked)
        self.chart_widget.set_structure_labels_visible(checked)
        self.status_bar.showMessage(
            f"Market structure labels {'shown' if checked else 'hidden'}."
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
        self.forecast_service.active_filter_algorithm = self._active_noise_algo

    def _on_noise_algorithm_changed(self, index: int) -> None:
        algo = self.combo_noise.itemData(index)
        if algo:
            self._active_noise_algo = algo
            self.forecast_service.active_filter_algorithm = algo
            selected_symbol = self.ticker_list.get_selected_symbol()
            if selected_symbol:
                self._on_ticker_selected(selected_symbol)
            if self._active_forecast is not None:
                self._apply_forecast_filter_extension()

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
        self.forecast_service.active_swing_algorithm = self._active_swing_algo

    def _on_swing_algorithm_changed(self, index: int) -> None:
        algorithm = self.combo_swing.itemData(index)
        if not algorithm:
            return
        self._active_swing_algo = algorithm
        self.forecast_service.active_swing_algorithm = algorithm
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
            self.lbl_price.setText(format_price(summary.current_price, summary.currency))
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

    def _update_performance_display(self) -> None:
        """Refreshes the fixed-range win/loss percentages shown above the chart."""
        symbol = self.ticker_list.get_selected_symbol()
        performance = self.market_data_service.get_performance(symbol) if symbol else {}

        for key, label in self.lbl_performance.items():
            pct = performance.get(key)
            if pct is None:
                label.setText("--")
                object_name = "changeNeutral"
                tooltip = (
                    f"Not enough local history for {key}. "
                    "Press 'Update all tickers' (Ctrl+U) to download more."
                )
            else:
                label.setText(f"{pct:+.2f}%")
                if pct > 0:
                    object_name = "changePositive"
                elif pct < 0:
                    object_name = "changeNegative"
                else:
                    object_name = "changeNeutral"
                tooltip = f"{key} price change based on local adjusted close data"

            label.setObjectName(object_name)
            label.setToolTip(tooltip)
            label.setStyle(label.style())

    def _on_chart_hover_changed(self, dt_str: str, price: float) -> None:
        """Dynamically updates header card to display exact hovered date & price."""
        currency = self._current_summary.currency if self._current_summary else None
        self.lbl_price.setText(format_price(price, currency))
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

    def _on_chart_type_changed(self, index: int) -> None:
        chart_type = self.combo_chart_type.itemData(index)
        if not chart_type:
            return
        self._active_chart_type = chart_type
        self.ticker_service.set_chart_type(chart_type)
        selected_symbol = self.ticker_list.get_selected_symbol()
        if selected_symbol:
            self._on_ticker_selected(selected_symbol)
        self.status_bar.showMessage(f"Chart type set to {chart_type.value}.")

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
        self._run_update(self.ticker_service.get_enabled_tickers())

    def _on_update_new_clicked(self) -> None:
        enabled_configs = self.ticker_service.get_enabled_tickers()
        missing_configs = self.market_data_service.get_tickers_without_data(enabled_configs)
        if not missing_configs:
            QMessageBox.information(
                self,
                "No New Tickers",
                "Every enabled ticker already has price data in the local database.",
            )
            return
        self._run_update(missing_configs)

    def _run_update(self, configs: List[TickerConfig]) -> None:
        if not configs:
            QMessageBox.information(self, "No Enabled Tickers", "Please enable or add at least one ticker in Manage Tickers.")
            return

        progress_dlg = UpdateProgressDialog(configs, self)

        self._update_worker = UpdateWorker(self.sync_service, configs)
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
        # Newly downloaded data may make pending forecasts evaluable.
        try:
            evaluated, _, pending = self.forecast_service.evaluate_pending()
            if evaluated:
                self.status_bar.showMessage(
                    f"Update completed: {success_count} successful, {fail_count} failed. "
                    f"{evaluated} forecast(s) evaluated ({pending} pending)."
                )
        except Exception as e:
            logger.warning(f"Post-update forecast evaluation failed: {e}")

    def _update_forecast_buttons(self) -> None:
        enabled = self._forecast_horizon != ForecastHorizon.OFF
        self.btn_forecast_generate.setEnabled(enabled)
        self.btn_forecast_save.setEnabled(enabled and self._active_forecast is not None)

    def _on_forecast_horizon_changed(self, index: int) -> None:
        horizon = self.combo_forecast.itemData(index)
        if not horizon:
            return
        self._forecast_horizon = horizon
        self.ticker_service.set_forecast_horizon(horizon)
        self._update_forecast_buttons()
        if horizon == ForecastHorizon.OFF:
            self._clear_forecast_overlay()
            self.status_bar.showMessage("Forecast overlay turned off.")
            return
        self._regenerate_forecast()



    def _apply_forecast_filter(self) -> None:
        """Applies the forecast filter to the sidebar list and the chart overlay."""
        key = normalize_forecast_filter(self._forecast_filter)
        active = key != "off"
        symbols: set = set()
        if active:
            try:
                latest = self.forecast_service.latest_forecast_by_ticker()
            except Exception as e:
                logger.warning(f"Forecast filter lookup failed: {e}")
                latest = {}
            symbols = {
                ticker
                for ticker, forecast in latest.items()
                if forecast_matches_filter(forecast, key)
            }
        self.ticker_list.set_forecast_filter(active, symbols)
        if self._active_forecast is not None:
            self.chart_widget.set_forecast_overlay_visible(
                forecast_matches_filter(self._active_forecast, key)
            )

    def _on_history_direction_filter_changed(self, direction: str) -> None:
        pass

    def _regenerate_forecast(self) -> None:
        """Generates a fresh forecast for the selected ticker and horizon."""
        if self._forecast_horizon == ForecastHorizon.OFF:
            return
        symbol = self.ticker_list.get_selected_symbol()
        if not symbol:
            self._clear_forecast_overlay()
            return
        try:
            forecast = self.forecast_service.generate(symbol, self._forecast_horizon)
        except ForecastError as e:
            self._clear_forecast_overlay()
            self.status_bar.showMessage(f"Forecast unavailable: {e}")
            QMessageBox.information(self, "Forecast", str(e))
            return
        except Exception as e:
            logger.error(f"Forecast generation failed for {symbol}: {e}")
            self._clear_forecast_overlay()
            self.status_bar.showMessage(f"Forecast failed: {e}")
            return
        self._active_forecast = forecast
        self._displaying_saved_forecast = False
        self.chart_widget.set_forecast_overlay(forecast, is_saved=False)
        self.chart_widget.set_forecast_overlay_visible(
            forecast_matches_filter(forecast, self._forecast_filter)
        )
        self._apply_forecast_filter_extension()
        self._update_forecast_buttons()
        self.status_bar.showMessage(
            f"Forecast generated for {symbol}: {forecast.horizon_label}, "
            f"bias {forecast.directional_bias.lower()}, "
            f"target {forecast.target_date}."
        )

    def _clear_forecast_overlay(self) -> None:
        self._active_forecast = None
        self._displaying_saved_forecast = False
        self.chart_widget.clear_forecast_overlay()
        self._apply_forecast_filter_extension()
        self._update_forecast_buttons()

    def _on_generate_forecast_clicked(self) -> None:
        self._regenerate_forecast()

    def _on_save_forecast_clicked(self) -> None:
        forecast = self._active_forecast
        if forecast is None or self._displaying_saved_forecast:
            QMessageBox.information(
                self, "Save Forecast", "Generate a forecast before saving."
            )
            return
        ok, message, is_duplicate = self.forecast_service.save(forecast)
        if not ok:
            QMessageBox.warning(self, "Save Forecast", message)
            return
        if is_duplicate:
            answer = QMessageBox.question(
                self,
                "Duplicate Forecast",
                "An identical forecast is already saved.\nSave another copy anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            ok, message, _ = self.forecast_service.save(forecast)
            if not ok:
                QMessageBox.warning(self, "Save Forecast", message)
                return
        self.status_bar.showMessage(message)
        QMessageBox.information(self, "Save Forecast", message)

    def _on_open_forecast_history(self) -> None:
        direction = None
        if self._forecast_filter in ("bullish", "bearish", "neutral"):
            direction = DirectionalBias.from_str(self._forecast_filter).value
        dlg = ForecastHistoryDialog(
            self.forecast_service, self, direction_filter=direction
        )
        dlg.show_forecast_requested.connect(self._on_show_saved_forecast)
        dlg.direction_filter_changed.connect(self._on_history_direction_filter_changed)
        dlg.exec()

    def _on_show_saved_forecast(self, record) -> None:
        """Displays a saved forecast snapshot on the chart (never regenerated)."""
        forecast = record.forecast
        selected = self.ticker_list.get_selected_symbol() or ""
        if forecast.ticker != selected:
            # Only show forecasts for the currently selected ticker so the
            # historical series behind the projection stays consistent.
            QMessageBox.information(
                self,
                "Show Forecast",
                f"This forecast is for {forecast.ticker}. "
                f"Select {forecast.ticker} in the market watch to display it.",
            )
            return
        self._active_forecast = forecast
        self._displaying_saved_forecast = True
        self.chart_widget.set_forecast_overlay(forecast, is_saved=True)
        self.chart_widget.set_forecast_overlay_visible(
            forecast_matches_filter(forecast, self._forecast_filter)
        )
        self._apply_forecast_filter_extension()
        self.status_bar.showMessage(
            f"Showing saved forecast #{record.id} for {forecast.ticker} "
            f"({forecast.horizon_label}, generated {forecast.generated_at})."
        )

    def closeEvent(self, event) -> None:
        """Joins the background earnings refresh so the thread dies with the window."""
        if self._earnings_worker is not None and self._earnings_worker.isRunning():
            self._earnings_worker.finished_events.disconnect(self._on_earnings_refreshed)
            self._earnings_worker.wait(3000)
        super().closeEvent(event)
