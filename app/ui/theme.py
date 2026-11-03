"""深色主题。"""

QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QWidget { background: #14161a; color: #e6e9ef; }
QMainWindow, QDialog { background: #14161a; }

QGroupBox {
    border: 1px solid #2a2f38; border-radius: 8px; margin-top: 9px;
    padding: 8px 9px 6px 9px; background: #191c22;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 6px;
    color: #9fb0c8; font-weight: 600;
}

QPushButton {
    background: #232833; border: 1px solid #2f3743; border-radius: 7px;
    padding: 6px 14px; color: #dfe6f1;
}
QPushButton:hover { background: #2b313d; border-color: #3d4656; }
QPushButton:pressed { background: #1d222b; }
QPushButton:disabled { color: #5b6373; background: #1a1e25; border-color: #252a33; }
QPushButton#primary {
    background: #3b6fd4; border: 1px solid #4f8cff; color: #ffffff; font-weight: 600;
}
QPushButton#primary:hover { background: #4a7fe4; }
QPushButton#danger { color: #ff9b9b; border-color: #5a3030; }
QPushButton#danger:hover { background: #3a2222; }

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #1e232b; border: 1px solid #303845; border-radius: 6px;
    padding: 5px 8px; selection-background-color: #3b6fd4;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #46536a; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #1e232b; border: 1px solid #303845; selection-background-color: #3b6fd4;
    outline: none;
}

QTableView {
    background: #171a20; alternate-background-color: #1b1f26;
    border: 1px solid #262c36; border-radius: 8px; gridline-color: #232933;
    selection-background-color: #24344f; selection-color: #eaf1ff;
}
QHeaderView::section {
    background: #1c2129; color: #93a1b5; border: none;
    border-bottom: 1px solid #2a303b; padding: 7px 8px; font-weight: 600;
}
QTableCornerButton::section { background: #1c2129; border: none; }

QCheckBox, QRadioButton { spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 15px; height: 15px; border: 1px solid #3a4352; border-radius: 4px;
    background: #1c212a;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: #4f8cff; border-color: #4f8cff;
}

QPlainTextEdit {
    background: #101318; border: 1px solid #262c36; border-radius: 8px;
    color: #b9c4d4; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
}

QProgressBar {
    background: #1c212a; border: 1px solid #2a303b; border-radius: 6px;
    text-align: center; height: 16px; color: #cfd8e6;
}
QProgressBar::chunk { background: #4f8cff; border-radius: 5px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #333c4a; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #445064; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #333c4a; border-radius: 5px; min-width: 30px; }

QSplitter::handle { background: #222831; width: 1px; }
QLabel#hint { color: #7f8a9c; }
QLabel#banner {
    background: #3a2f1a; border: 1px solid #6b5626; color: #f0d79a;
    border-radius: 7px; padding: 7px 10px;
}
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab {
    background: #1b1f26; color: #93a1b5; border: 1px solid #262c36;
    padding: 6px 14px; margin-right: 4px; border-radius: 6px;
}
QTabBar::tab:selected { background: #2b3b56; color: #eaf1ff; border-color: #3f5c8a; }
QTabBar::tab:hover { color: #dfe8f6; }

QToolTip { background: #232833; color: #e6e9ef; border: 1px solid #3a4352; padding: 4px; }
QMenu { background: #1e232b; border: 1px solid #303845; }
QMenu::item { padding: 6px 22px; }
QMenu::item:selected { background: #2f4a76; }
"""
