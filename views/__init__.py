"""
Package views: Chứa toàn bộ giao diện người dùng theo kiến trúc Modular Monolith.
"""

from views.tab_grading import render_tab_grading
from views.tab_history import render_tab_history
from views.tab_keys import render_tab_keys

__all__ = [
    "render_tab_grading",
    "render_tab_history",
    "render_tab_keys"
]
