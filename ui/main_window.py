"""
主窗口 — FluentWindow + 左侧导航(导航项带图标/分组, 低频页放底部)。

与旧版(QTabWidget 平铺 7 个 tab)的差别:
- 用 qfluentwidgets 的 `FluentWindow`/`NavigationInterface`: 云母/亚克力标题栏、导航项图标、"关于"沉到底部;
- 默认尺寸回到"能放下表格与日志"的 1120x760(旧版 700x520 会把内容挤没), 并**记住上次窗口几何**;
- 主题(浅色/深色/跟随系统)在此统一设置一次, 供设置页切换;
- **运行页现在自己显示实时日志**(旧版日志只在「调试工具」页显示, 跑任务时要来回切页); 由于一个 `QWidget`
  不能同时属于两个布局, 运行页与调试页各持一份独立视图, 都接同一条日志流。
"""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

from qfluentwidgets import (FluentWindow, FluentIcon as FIF, NavigationItemPosition, Theme,
                            setTheme, setThemeColor)

from ui.run_tab import RunTab
from ui.plan_tab import PlanTab
from ui.set_config_tab import SetConfigTab
from ui.settings_tab import SettingsTab
from ui.hotkey_tab import HotkeyTab
from ui.debug_tab import DebugTab
from ui.about_tab import AboutTab
from ui.dev_tab import DevTab

# 日志视图样式: 等宽 + 中文回退字体(与旧版一致)
LOG_QSS = "QTextEdit { font-family: Consolas, 'Microsoft YaHei', monospace; font-size: 12px; }"


def new_log_view() -> QTextEdit:
    """一份独立日志视图。**一个 QWidget 只能属于一个父布局**, 所以每页各要一份, 不能共享。"""
    view = QTextEdit()
    view.setReadOnly(True)
    view.setStyleSheet(LOG_QSS)
    return view


class MainWindow(FluentWindow):
    def __init__(self, ok_engine, log_bridge):
        super().__init__()
        self.setWindowTitle("OK-Echo — 声骸强化")
        self._settings = QSettings("OK-Echo", "MainWindow")

        self._init_theme()
        self._init_log_views(log_bridge)
        self._init_pages(ok_engine, log_bridge)
        self._init_navigation()
        self._init_shortcuts()
        self._init_geometry()

    # ── 初始化 ──
    def _init_theme(self):
        name = str(self._settings.value("theme", Theme.LIGHT.name))
        self.apply_theme(name, remember=False)

    def _init_log_views(self, log_bridge):
        self.run_log = new_log_view()
        self.debug_log = new_log_view()
        # 运行页自己连 log_bridge(见 RunTab.__init__); 调试页这份在这里接同一条日志流
        log_bridge.log_signal.connect(self.debug_log.append)

    def _init_pages(self, ok_engine, log_bridge):
        self.settings_page = SettingsTab()
        self.hotkey_page = HotkeyTab()
        self.run_page = RunTab(ok_engine, log_bridge, self.run_log)
        self.plan_page = PlanTab()
        self.set_config_page = SetConfigTab()
        self.set_config_page.saved.connect(self.run_page._load_sets)
        self.debug_page = DebugTab(self.debug_log)
        self.dev_tab = DevTab()
        self.about_tab = AboutTab()

    def _init_navigation(self):
        # addSubInterface 以 objectName 作路由键 → 必须唯一且非空
        pages = (
            (self.run_page, FIF.HOME, "运行"),
            (self.plan_page, FIF.TILES, "组合穷举"),
            (self.settings_page, FIF.SETTING, "设备设置"),
            (self.hotkey_page, FIF.GAME, "热键设置"),
            (self.set_config_page, FIF.LIBRARY, "套装配置"),
            (self.debug_page, FIF.DEVELOPER_TOOLS, "调试工具"),
            (self.dev_tab, FIF.CODE, "开发者"),
        )
        for page, icon, text in pages:
            page.setObjectName(f"page_{text}")
            self.addSubInterface(page, icon, text)
        self.about_tab.setObjectName("page_关于")
        self.addSubInterface(self.about_tab, FIF.INFO, "关于", NavigationItemPosition.BOTTOM)

        self.navigationInterface.setExpandWidth(190)
        # 恢复上次停留的页面(默认"运行"); 找不到(改名/首次运行)就回运行页
        last = str(self._settings.value("page", "page_运行"))
        page = next((p for p, _, _ in pages if p.objectName() == last), self.run_page)
        self.switchTo(page)

    def _init_shortcuts(self):
        """全局快捷键: Ctrl+Enter 开始/停止, Ctrl+L 清日志, F1 打开关于。"""

        def toggle_run():
            self.switchTo(self.run_page)
            (self.run_page._stop if self.run_page._running else self.run_page._start)()

        for keys, slot in (("Ctrl+Return", toggle_run),
                           ("Ctrl+L", self.run_page._clear_log),
                           ("F1", lambda: self.switchTo(self.about_tab))):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _init_geometry(self):
        """默认 1120x760(旧版 700x520 放不下表格+日志), 记住上次几何, 并 clamp 到当前工作区。"""
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        self.setMinimumSize(940, 620)

        saved = self._settings.value("geometry")
        if saved is not None:
            self.restoreGeometry(saved)
        elif avail is not None:
            self.resize(1120, 760)
            geo = self.frameGeometry()
            geo.moveCenter(avail.center())
            self.move(geo.topLeft())
        else:
            self.resize(1120, 760)

        if avail is not None:                 # 换了显示器/分辨率时不要把窗口丢到屏幕外
            self.resize(min(self.width(), avail.width() - 32), min(self.height(), avail.height() - 32))

    # ── 主题 ──
    def apply_theme(self, name: str, remember: bool = True):
        """设置页调用: 主题名 = Theme.LIGHT/DARK/AUTO 的 name。"""
        theme = getattr(Theme, str(name), Theme.LIGHT)
        setTheme(theme)
        try:
            setThemeColor("#0a84ff")
        except Exception:
            pass
        try:
            # 深色下关掉云母, 避免半透明与深色卡片叠出脏色
            self.setMicaEffectEnabled(theme is not Theme.DARK)
        except Exception:
            pass
        if remember:
            self._settings.setValue("theme", theme.name)
        # 注: 不手动 unpolish/polish 整棵树 —— qfluentwidgets 的 setTheme 会走全局重绘(Gallery 也是实时切换),
        # 手动 repolish 反而在离屏/构造期不稳(实测崩过)。运行中切换后的观感需真机确认一次。

    # ── 关闭: 沿用 ok-script 标准退出通道, 避免进程残留 ──
    def closeEvent(self, event: QCloseEvent):
        try:
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("page", self.stackedWidget.currentWidget().objectName())
        except Exception:
            pass
        try:
            from ok.gui.Communicate import communicate
            communicate.quit.emit()   # OK.quit(): exit_event.set() + app.quit()
        except Exception:
            pass
        event.accept()
