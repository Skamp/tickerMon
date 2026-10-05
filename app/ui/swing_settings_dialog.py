import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
)

from app.services.ticker_service import TickerService
from app.services.swing_detection import SwingAlgorithm, SWING_ALGORITHM_PARAMS, default_swing_params

logger = logging.getLogger(__name__)


class SwingSettingsDialog(QDialog):
    def __init__(self, ticker_service: TickerService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ticker_service = ticker_service
        self.setWindowTitle("Swing Settings")
        self.setMinimumSize(620, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._params: Dict[str, Dict[str, float]] = ticker_service.get_all_swing_params()
        self._editors: Dict[str, QWidget] = {}

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(16, 16, 16, 16)

        hint = QLabel(
            "Checked algorithms are shown in the Swing dropdown.\n"
            "Select an algorithm to edit its parameters.",
            self,
        )
        hint.setStyleSheet("color: #8b90a0;")
        self.layout.addWidget(hint)

        content_box = QHBoxLayout()
        content_box.setSpacing(16)
        self.layout.addLayout(content_box)

        self.list_widget = QListWidget(self)
        self.list_widget.setMinimumWidth(240)
        content_box.addWidget(self.list_widget)

        self.params_group = QGroupBox("Parameters", self)
        self.params_form = QFormLayout(self.params_group)
        self.params_form.setContentsMargins(12, 12, 12, 12)
        self.params_form.setSpacing(8)
        content_box.addWidget(self.params_group, 1)

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
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self._build_param_form(self.list_widget.item(0).data(Qt.UserRole))

    def refresh_list(self) -> None:
        enabled = set(self.ticker_service.get_enabled_swing_algorithms())
        self.list_widget.clear()
        for algorithm in SwingAlgorithm:
            item = QListWidgetItem(algorithm.value)
            item.setData(Qt.UserRole, algorithm)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if algorithm.value in enabled else Qt.Unchecked)
            self.list_widget.addItem(item)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.list_widget.count()):
            self.list_widget.item(row).setCheckState(state)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self._store_current_editors()
        algorithm = self.list_widget.item(row).data(Qt.UserRole)
        self._build_param_form(algorithm)

    def _build_param_form(self, algorithm: SwingAlgorithm) -> None:
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._editors = {}

        values = self._params.get(algorithm.value) or default_swing_params(algorithm)
        specs = SWING_ALGORITHM_PARAMS.get(algorithm, ())
        if not specs:
            self.params_form.addRow(QLabel("No configurable parameters.", self))
            return

        for spec in specs:
            value = values.get(spec.key, spec.default)
            if spec.kind == "int":
                editor: QWidget = QSpinBox(self)
                editor.setRange(int(spec.minimum), int(spec.maximum))
                editor.setSingleStep(int(spec.step) if spec.step >= 1 else 1)
                editor.setValue(int(round(value)))
            else:
                double_editor = QDoubleSpinBox(self)
                double_editor.setDecimals(spec.decimals)
                double_editor.setRange(spec.minimum, spec.maximum)
                double_editor.setSingleStep(spec.step)
                double_editor.setValue(float(value))
                editor = double_editor
            self._editors[spec.key] = editor
            self.params_form.addRow(spec.label, editor)

    def _store_current_editors(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        algorithm = self.list_widget.item(row).data(Qt.UserRole)
        if not self._editors:
            return
        stored: Dict[str, float] = dict(self._params.get(algorithm.value) or {})
        for key, editor in self._editors.items():
            if isinstance(editor, QSpinBox):
                stored[key] = float(editor.value())
            elif isinstance(editor, QDoubleSpinBox):
                stored[key] = float(editor.value())
        self._params[algorithm.value] = stored

    def _on_save(self) -> None:
        self._store_current_editors()

        enabled: List[str] = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() == Qt.Checked:
                algorithm = item.data(Qt.UserRole)
                enabled.append(algorithm.value)

        self.ticker_service.set_enabled_swing_algorithms(enabled)
        self.ticker_service.set_swing_params(self._params)
        self.accept()
