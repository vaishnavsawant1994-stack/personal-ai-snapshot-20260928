"""Shared semantic presentation tokens for the native desktop companion."""
from __future__ import annotations

from PyQt6.QtGui import QGuiApplication

COLORS = {
    "background": "#030405",
    "surface": "#0b1115",
    "surface_raised": "#101b21",
    "text": "#edf3f6",
    "secondary": "#9badb7",
    "muted": "#71818b",
    "border": "#2b4350",
    "accent": "#67b7ff",
    "danger": "#ff929f",
    "selection": "#244656",
}

SPACE = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40}
TYPE = {"display": 30, "page_title": 23, "section_title": 19, "body": 16, "supporting": 14, "control": 14, "metadata": 12}
CONTROL_HEIGHT = 44
TOUCH_TARGET = 44


def stylesheet(*, high_contrast: bool = False) -> str:
    colors = dict(COLORS)
    if high_contrast:
        colors.update(secondary="#cbd8de", muted="#b2c2ca", border="#536f7c", accent="#8acaff")
    return f"""
    QWidget {{ color: {colors['text']}; font-family: Inter, 'Segoe UI', Arial; font-size: {TYPE['body']}px; }}
    QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QTreeWidget {{
      color: {colors['text']}; background: {colors['surface']}; border: 1px solid {colors['border']};
      border-radius: 10px; padding: 8px 10px; selection-background-color: {colors['selection']};
    }}
    QPushButton {{ color: {colors['text']}; background: {colors['surface']}; border: 1px solid {colors['border']};
      border-radius: 10px; padding: 8px 13px; min-height: {CONTROL_HEIGHT}px; }}
    QPushButton:hover {{ background: {colors['surface_raised']}; border-color: {colors['accent']}; }}
    QPushButton:pressed {{ background: {colors['selection']}; }}
    QPushButton:disabled {{ color: {colors['muted']}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus,
    QTreeWidget:focus, QPushButton:focus, QTabBar::tab:focus {{ border: 2px solid {colors['accent']}; }}
    QCheckBox {{ spacing: 9px; }} QCheckBox::indicator {{ width: 20px; height: 20px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
    """


def fit_window_to_screen(widget, *, preferred: tuple[int, int], minimum: tuple[int, int] = (560, 440)) -> None:
    """Pick a usable initial size while retaining resizability and user zoom."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        widget.resize(*preferred)
        widget.setMinimumSize(*minimum)
        return
    available = screen.availableGeometry()
    width = max(320, min(preferred[0], int(available.width() * 0.92)))
    height = max(320, min(preferred[1], int(available.height() * 0.9)))
    widget.setMinimumSize(min(minimum[0], width), min(minimum[1], height))
    widget.resize(width, height)
