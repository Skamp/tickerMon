import logging
from typing import Dict, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from app.models.trend import TrendBucket

logger = logging.getLogger(__name__)

_BUCKET_COLORS = {
    TrendBucket.RISE: "#00e676",
    TrendBucket.DOWN: "#ff5252",
    TrendBucket.LATERAL: "#8b90a0",
    TrendBucket.UNSURE: "#ffab00",
    "swing": "#b388ff",
}


class TrendFilterBar(QWidget):
    """Toggle button grid that filters the ticker list by trend bucket or swing move."""

    filter_changed = Signal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._buttons: Dict[TrendBucket, QPushButton] = {}

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._all_button = QPushButton(self)
        self._all_button.setCheckable(True)
        self._all_button.setChecked(True)
        self._all_button.setCursor(Qt.PointingHandCursor)
        self._all_button.setProperty("bucket", "all")
        self._all_button.setToolTip("Show all tickers")
        self._all_button.clicked.connect(self._on_all_clicked)
        layout.addWidget(self._all_button, 0, 0)

        self._swing_button = QPushButton(self)
        self._swing_button.setCheckable(True)
        self._swing_button.setCursor(Qt.PointingHandCursor)
        self._swing_button.setProperty("bucket", "swing")
        self._swing_button.setToolTip("Show tickers that swung at least 10% within the selected range")
        self._swing_button.clicked.connect(self._on_bucket_clicked)
        layout.addWidget(self._swing_button, 0, 1)

        for row, bucket in enumerate(TrendBucket):
            button = QPushButton(self)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("bucket", bucket.name.lower())
            button.setToolTip(f"Show tickers with a {bucket.value.lower()} trend")
            button.clicked.connect(self._on_bucket_clicked)
            layout.addWidget(button, 1 + row // 2, row % 2)
            self._buttons[bucket] = button

        self.setStyleSheet("""
            TrendFilterBar QPushButton {
                background-color: #252836;
                color: #e1e3ea;
                border: 1px solid #323647;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            TrendFilterBar QPushButton:hover {
                border-color: #454b61;
            }
            TrendFilterBar QPushButton:checked {
                background-color: #2962ff;
                border-color: #2962ff;
                color: #ffffff;
            }
            TrendFilterBar QPushButton[bucket="rise"] {
                color: #00e676;
            }
            TrendFilterBar QPushButton[bucket="down"] {
                color: #ff5252;
            }
            TrendFilterBar QPushButton[bucket="lateral"] {
                color: #8b90a0;
            }
            TrendFilterBar QPushButton[bucket="unsure"] {
                color: #ffab00;
            }
            TrendFilterBar QPushButton[bucket="swing"] {
                color: #b388ff;
            }
            TrendFilterBar QPushButton[bucket="rise"]:checked,
            TrendFilterBar QPushButton[bucket="down"]:checked,
            TrendFilterBar QPushButton[bucket="lateral"]:checked,
            TrendFilterBar QPushButton[bucket="unsure"]:checked,
            TrendFilterBar QPushButton[bucket="swing"]:checked {
                color: #ffffff;
            }
        """)

        self.set_counts({bucket: 0 for bucket in TrendBucket}, 0)

    def set_counts(self, counts: Dict[TrendBucket, int], swing_count: int) -> None:
        for bucket, button in self._buttons.items():
            count = counts.get(bucket, 0)
            button.setText(f"{bucket.value} {count}")
        self._all_button.setText(f"All {sum(counts.values())}")
        self._swing_button.setText(f"Swing {swing_count}")

    def set_swing_algorithm(self, algorithm_name: str) -> None:
        self._swing_button.setToolTip(
            f"Show tickers flagged as swinging by '{algorithm_name}' (moves of at least 10%)"
        )

    def active_trends(self) -> Set[TrendBucket]:
        return {bucket for bucket, button in self._buttons.items() if button.isChecked()}

    def swing_active(self) -> bool:
        return self._swing_button.isChecked()

    def all_active(self) -> bool:
        return self._all_button.isChecked()

    def _any_filter_active(self) -> bool:
        return bool(self.active_trends()) or self._swing_button.isChecked()

    def _on_all_clicked(self) -> None:
        self._all_button.setChecked(True)
        self._swing_button.setChecked(False)
        for button in self._buttons.values():
            button.setChecked(False)
        self.filter_changed.emit()

    def _on_bucket_clicked(self) -> None:
        if self._all_button.isChecked():
            self._all_button.setChecked(False)
        if not self._any_filter_active():
            self._all_button.setChecked(True)
        self.filter_changed.emit()
