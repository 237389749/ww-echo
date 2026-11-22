"""
UI 共享小工具(Fluent 页面里重复用到、且各页踩过同一坑的东西放这里)。
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QLayout, QScrollArea, QSizePolicy, QTextEdit, QWidget)

from qfluentwidgets import DoubleSpinBox, SettingCard, SpinBox


class FlowLayout(QLayout):
    """自动换行的流式布局(控件放不下就换到下一行)。

    **为什么需要**: 设置卡原来的控件都横着排在右侧(`SettingCard.hBoxLayout`), 窗口窄到 940 时
    整页最小宽度被撑到 1000+, 只能横向裁切; 纵向滚动哪怕高一点也比横向滚动好用(2026-11-20 用户口径)。
    这是 Qt 官方 FlowLayout 示例的精简版: 支持 `heightForWidth`, 供 `WrapSettingCard` 算高度。
    """

    def __init__(self, parent=None, hspacing=8, vspacing=8):
        super().__init__(parent)
        self._items = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > eff.right() + 1 and line_h > 0:
                x, y = eff.x(), y + line_h + self._vspacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._hspacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class WrapSettingCard(SettingCard):
    """可换行的设置卡: 描述自动换行, 控件放到描述下方的 FlowLayout, 高度随内容增长。

    `SettingCard` 原本 `setFixedHeight(70)` + 控件横排在右侧 → 窄窗口下整卡最小宽度能到 1200+。
    这里: ①解除固定高度; ②把标题/描述改成撑满宽度(才能 word wrap); ③控件行放 FlowLayout;
    ④`resizeEvent` 里按当前宽度算流式高度, 再把卡片固定成该高度(否则父布局只按单行高度给它)。
    """

    def __init__(self, icon, title, content=None, parent=None, hspacing=8, vspacing=8):
        super().__init__(icon, title, content, parent)
        self.setMinimumHeight(70 if content else 50)
        self.setMaximumHeight(16777215)
        for label in (self.titleLabel, self.contentLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            # 重新加一次(不带对齐) → 让标签撑满文字列宽度; 留 AlignLeft 时它只会取单行 width
            self.vBoxLayout.removeWidget(label)
            self.vBoxLayout.addWidget(label)
        self.hBoxLayout.setStretch(4, 0)      # 原尾部 stretch 让位
        self.hBoxLayout.setStretch(2, 1)      # 图标后的文字列吃满宽度
        self.hBoxLayout.setAlignment(Qt.AlignTop)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self._flow_widget = QWidget(self)
        self._flow = FlowLayout(self._flow_widget, hspacing=hspacing, vspacing=vspacing)
        self._flow_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self._flow_widget)
        self._adjusting = False

    def add_controls(self, widgets):
        for w in widgets:
            self._flow.addWidget(w)

    def _text_width(self):
        width = self.vBoxLayout.geometry().width()
        return width if width > 0 else max(120, self.width() - 64)

    def _calc_height(self, width):
        text_width = max(120, width - 64)
        title_h = self.titleLabel.sizeHint().height()
        content_h = self.contentLabel.heightForWidth(text_width) if self.contentLabel.text() else 0
        flow_h = self._flow.heightForWidth(text_width)
        return max(70 if self.contentLabel.text() else 50,
                   12 + title_h + 2 + content_h + 8 + flow_h + 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._adjusting:
            return
        flow_h = self._flow.heightForWidth(self._text_width())
        if flow_h > 0 and self._flow_widget.height() != flow_h:
            self._flow_widget.setFixedHeight(flow_h)
        height = self._calc_height(self.width())
        if abs(self.height() - height) > 1:
            self._adjusting = True
            try:
                self.setFixedHeight(height)
            finally:
                self._adjusting = False



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


class _SpinLineEditFix:
    """让 qfluentwidgets 的 SpinBox 真的把数值画出来（U-01）。

    **根因**（2026-11-22 评审定位）: `qfluentwidgets.components.widgets.spin_box.SpinBoxBase`
    在 QAbstractSpinBox 上**额外挂了一个 `QHBoxLayout`**（放上/下两个 31px 按钮）并调了
    `setButtonSymbols(NoButtons)`。Qt 6.12 起 QAbstractSpinBox 不再自己摆内部的 QLineEdit，
    于是它的几何停在 `QRect(0, 1, 1, 31)` —— `lineEdit().text()` 有值，但**一个像素都画不出来**。
    用户看到的是"输入框只有上下箭头、数字看不见、键盘输入也看不见"（14/14 个全中，首个 1px）。

    **改法**: `resizeEvent` 里手动把编辑区摆到左侧、右侧让出按钮。预留量**问布局要**
    （`hBoxLayout.sizeHint().width()` = 右边距 4 + 31 + 间距 5 + 31 = 71），不写死像素 ——
    库里按钮宽度一变就自动跟着走；拿不到布局时才退回 `FALLBACK_RESERVE`（=74，当前版本的实测值）。
    留 `GAP` 空隙，否则文字会钻到按钮底下（实测 74 时有 6px 重叠）。

    **为什么用子类**（而不是改 site-packages / 升降依赖）: 项目纪律要求依赖只读；降级 PySide6 6.12
    会波及 OCR/引擎，得重跑全部单测与真机验证。子类只影响本项目的两个页面。
    """

    LEFT = 9                  # 编辑区左边距(与 Fluent 样式的文字起点一致)
    GAP = 3                   # 编辑区右缘与上/下按钮之间的空隙
    FALLBACK_RESERVE = 74     # 拿不到布局时的预留(两个 31px 按钮 + 边距)

    def _reserve_width(self) -> int:
        layout = getattr(self, 'hBoxLayout', None)
        if layout is None:
            return self.FALLBACK_RESERVE
        hint = layout.sizeHint().width()
        return hint if hint > 0 else self.FALLBACK_RESERVE

    def resizeEvent(self, event):
        super().resizeEvent(event)
        edit = self.lineEdit()
        if edit is None:
            return
        width = max(20, self.width() - self.LEFT - self._reserve_width() - self.GAP)
        edit.setGeometry(self.LEFT, 1, width, self.height() - 2)


class NumberDoubleSpinBox(_SpinLineEditFix, DoubleSpinBox):
    """看得见数值的 DoubleSpinBox（U-01）。用法与 qfluentwidgets.DoubleSpinBox 完全一致。"""


class NumberSpin(_SpinLineEditFix, SpinBox):
    """看得见数值的 SpinBox（U-01）。用法与 qfluentwidgets.SpinBox 完全一致。"""


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
