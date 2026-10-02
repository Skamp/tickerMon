DARK_THEME_QSS = """
/* Global Application Dark Theme */
QMainWindow, QDialog {
    background-color: #121318;
    color: #e1e3ea;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: #121318;
    color: #e1e3ea;
}

/* Sidebar & Cards */
QFrame#sidebarFrame, QFrame#cardFrame, QFrame#headerFrame {
    background-color: #1a1c24;
    border-radius: 6px;
    border: 1px solid #282b36;
}

/* Toolbars */
QToolBar {
    background-color: #1a1c24;
    border-bottom: 1px solid #282b36;
    spacing: 6px;
    padding: 6px;
}

/* Buttons */
QPushButton {
    background-color: #252836;
    color: #c5c9d6;
    border: 1px solid #323647;
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #323647;
    color: #ffffff;
    border-color: #454b61;
}

QPushButton:pressed {
    background-color: #1c1e29;
}

QPushButton:checked {
    background-color: #2962ff;
    color: #ffffff;
    border-color: #2962ff;
}

QPushButton#updateButton {
    background-color: #00c853;
    color: #ffffff;
    border-color: #00e676;
    font-weight: bold;
    padding: 7px 18px;
}

QPushButton#updateButton:hover {
    background-color: #00e676;
    border-color: #69f0ae;
}

/* List Widgets */
QListWidget {
    background-color: #1a1c24;
    border: 1px solid #282b36;
    border-radius: 6px;
    outline: none;
    padding: 4px;
}

QListWidget::item {
    background-color: transparent;
    border-radius: 4px;
    padding: 4px;
    margin-bottom: 2px;
}

QListWidget::item:hover {
    background-color: #252836;
}

QListWidget::item:selected {
    background-color: #2a3147;
    border: 1px solid #2962ff;
}

/* Labels */
QLabel {
    color: #e1e3ea;
    background: transparent;
}

QLabel#titleLabel {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
}

QLabel#subtitleLabel {
    font-size: 12px;
    color: #8b90a0;
}

QLabel#priceLabel {
    font-size: 26px;
    font-weight: bold;
    color: #ffffff;
}

QLabel#changePositive {
    font-size: 14px;
    font-weight: bold;
    color: #00e676;
}

QLabel#changeNegative {
    font-size: 14px;
    font-weight: bold;
    color: #ff5252;
}

QLabel#changeNeutral {
    font-size: 14px;
    font-weight: bold;
    color: #8b90a0;
}

/* Inputs & LineEdits */
QLineEdit, QSpinBox {
    background-color: #121318;
    border: 1px solid #323647;
    border-radius: 4px;
    padding: 6px 10px;
    color: #ffffff;
}

QLineEdit:focus {
    border-color: #2962ff;
}

/* Tables */
QTableWidget {
    background-color: #1a1c24;
    border: 1px solid #282b36;
    gridline-color: #282b36;
    border-radius: 4px;
}

QHeaderView::section {
    background-color: #252836;
    color: #8b90a0;
    padding: 6px;
    border: none;
    font-weight: bold;
}

/* Scrollbars */
QScrollBar:vertical {
    background: #121318;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #323647;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #454b61;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #1a1c24;
    color: #8b90a0;
    border-top: 1px solid #282b36;
}
"""
