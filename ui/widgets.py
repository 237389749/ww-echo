"""
UI 共享小工具(Fluent 页面里重复用到、且各页踩过同一坑的东西放这里)。
"""
from PySide6.QtWidgets import QScrollArea


def make_scroll_transparent(scroll: QScrollArea) -> QScrollArea:
    """让滚动容器"透出"窗口背景。

    **为什么必须做**: qfluentwidgets 切深色只换样式表, 不改 QPalette; 而 `QScrollArea` 的 viewport
    默认用自己的调色板画底(Base/Window 色) → 深色主题下滚动页会**仍是浅色底、文字却已变浅**, 看起来
    "发白/糊"。把 viewport 背景置透明后, 深/浅色都由窗口背景决定(实测深色下三页正常回暗)。
    """
    try:
        scroll.enableTransparentBackground()      # 库自带的助手(有则优先用)
    except Exception:
        pass
    try:
        scroll.viewport().setAutoFillBackground(False)
        scroll.setFrameShape(QScrollArea.NoFrame)
    except Exception:
        pass
    scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
    return scroll
