# gui/widgets/motion.py
"""
Shared helpers for the motion polish pass (docs/design/motion-system.md).
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget


def install_motion_wrapper(page: QWidget) -> QWidget:
    """Create the per-page child wrapper used by incoming-only page transitions.

    The page stays a plain container in the QStackedWidget; the returned
    `_motion_wrapper` child owns the real content layout and is the only
    widget animated during switches (children only — never the top-level
    window). Public page APIs are untouched.
    """
    wrap = QWidget(page)
    wrap.setObjectName("PageMotionWrapper")
    lay = QHBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(wrap)
    page._motion_wrapper = wrap
    return wrap
