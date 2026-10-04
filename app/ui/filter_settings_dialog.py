import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from app.services.ticker_service import TickerService
from app.services.noise_reduction import NoiseReductionAlgorithm

logger = logging.getLogger(__name__)


class FilterSettingsDialog(QDialog):
    def __init__(self, ticker_service: TickerService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ticker_service = ticker_service
        self.setWindowTitle("Filter Settings")
        self.setMinimumSize(360, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(16, 16, 16, 16)

        hint = QLabel('Checked filters are shown in the Filter dropdown.\n"None (Raw Data)" is always available.', self)
        hint.setStyleSheet("color: #8b90a0;")
        self.layout.addWidget(hint)

        self.list_widget = QListWidget(self)
        self.layout.addWidget(self.list_widget)

        selection_box = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All", self)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.deselect_all_btn = QPushButton("Deselect All", self)
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        selection_box.addWidget(self.select_all_btn)
        selection_box.addWidget(self.deselect_all_btn)
        selection_box.addStretch()
        self.layout.addLayout(selection_box)

        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save", self)
        self.save_btn.clicked.connect(self._on_save)
        bottom_box.addWidget(self.cancel_btn)
        bottom_box.addWidget(self.save_btn)
        self.layout.addLayout(bottom_box)

        self.refresh_list()

    def refresh_list(self) -> None:
        enabled = set(self.ticker_service.get_enabled_filters())
        self.list_widget.clear()
        for algorithm in NoiseReductionAlgorithm:
            if algorithm == NoiseReductionAlgorithm.NONE:
                continue
            item = QListWidgetItem(algorithm.value)
            item.setData(Qt.UserRole, algorithm)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if algorithm.value in enabled else Qt.Unchecked)
            self.list_widget.addItem(item)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.list_widget.count()):
            self.list_widget.item(row).setCheckState(state)

    def _on_save(self) -> None:
        enabled: List[str] = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() == Qt.Checked:
                algorithm = item.data(Qt.UserRole)
                enabled.append(algorithm.value)

        self.ticker_service.set_enabled_filters(enabled)
        self.accept()
