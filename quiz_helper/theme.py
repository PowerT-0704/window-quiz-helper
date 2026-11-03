"""统一的浅色与深色 Qt Widgets 样式。"""


def stylesheet(theme: str) -> str:
    dark = theme == "dark"
    bg, card, text, muted, border, hover = (
        ("#172923", "#21372f", "#eef7f2", "#b0c7bb", "#365347", "#2b493d")
        if dark else
        ("#f4faf6", "#ffffff", "#253f36", "#637e72", "#e0ece5", "#e8f5ee")
    )
    accent = "#79d9b8" if dark else "#267563"
    return f"""
    * {{ font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }}
    QMainWindow, QDialog, QWidget#page {{ background: {bg}; color: {text}; }}
    QWidget {{ color: {text}; }}
    QLabel {{ background: transparent; }}
    QFrame#sidebar {{ background: {card}; border-right: 1px solid {border}; }}
    QFrame#card {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
    QLabel#title {{ font-size: 25px; font-weight: 700; }}
    QLabel#section {{ font-size: 16px; font-weight: 600; }}
    QLabel#muted {{ color: {muted}; }}
    QLabel#brand {{ color: #ffffff; background: #318773; border-radius: 12px; font-size: 24px; font-weight: 700; }}
    QLabel#answer {{ font-size: 38px; font-weight: 700; color: {accent}; }}
    QLabel#badge {{ color: {accent if dark else '#477692'}; background: {hover if dark else '#edf6fc'}; padding: 6px 12px; border-radius: 12px; }}
    QPushButton {{ background: {card}; border: 1px solid {border}; padding: 9px 15px; border-radius: 8px; }}
    QPushButton:hover {{ background: {hover}; border-color: #86c7ac; }}
    QPushButton:pressed {{ background: {border}; }}
    QPushButton:disabled {{ color: {muted}; background: {bg}; border-color: {border}; }}
    QPushButton#primary {{ background: #267563; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: #1c6554; }}
    QPushButton#primary:disabled {{ background: #b5d8c9; color: #315b49; }}
    QPushButton#nav {{ text-align: left; border: none; padding: 12px 18px; color: {muted}; }}
    QPushButton#nav:checked {{ color: {accent}; background: {hover}; font-weight: 600; }}
    QLineEdit, QSpinBox, QComboBox, QListWidget, QTextBrowser, QKeySequenceEdit {{ background: {card}; color: {text}; border: 1px solid {border}; border-radius: 7px; padding: 7px; selection-background-color: #318773; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: #318773; }}
    QComboBox QAbstractItemView {{ background: {card}; color: {text}; selection-background-color: #318773; }}
    QCheckBox {{ spacing: 7px; padding: 4px 0; }}
    QScrollArea {{ border: none; background: {bg}; }}
    QScrollArea > QWidget > QWidget {{ background: {bg}; }}
    QTabWidget::pane {{ border: none; background: {bg}; }}
    QTabBar::tab {{ background: {bg}; color: {muted}; padding: 10px 18px; border-bottom: 2px solid {border}; }}
    QTabBar::tab:selected {{ color: {accent}; border-bottom-color: #318773; }}
    QGroupBox {{ border: 1px solid {border}; border-radius: 10px; margin-top: 18px; padding: 18px 12px 12px; background: {card}; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px; }}
    QToolTip {{ background: {card}; color: {text}; border: 1px solid {border}; padding: 5px; }}
    QFrame#overlay {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
    """
