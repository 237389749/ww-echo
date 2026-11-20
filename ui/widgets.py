"""
UI 共享小工具(Fluent 页面里重复用到、且各页踩过同一坑的东西放这里)。
"""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QScrollArea, QTextEdit


class LogView(QTextEdit):
    """日志视图(等宽字体由调用方设)。

    **sizeHint 必须压小(2026-11-20)**: QTextEdit 默认 sizeHint 高 192px, 会把运行页/调试页的
    sizeHint 撑到 833 —— 套上滚动容器后, 默认 760 的窗口就出现滚动条、日志卡被切在窗口下沿。
    这里只把"建议高度"压到 70(实际高度由布局里的 stretch 决定, 窗口高时照常长高);
    `minimumSizeHint` 同步压到 60, 让页面最小高度落在 620 附近, 再矮才出滚动条。
    """
    HINT_HEIGHT = 70

    def sizeHint(self) -> QSize:
        return QSize(480, self.HINT_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, 60)


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
