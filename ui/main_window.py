"""
主窗口 — 共享日志, 各功能 tab。
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget, QTextEdit

from ui.run_tab import RunTab
from ui.set_config_tab import SetConfigTab
from ui.settings_tab import SettingsTab
from ui.hotkey_tab import HotkeyTab
from ui.debug_tab import DebugTab
from ui.about_tab import AboutTab
from ui.dev_tab import DevTab


class MainWindow(QMainWindow):
    def __init__(self, ok_engine, log_bridge):
        super().__init__()
        self.setWindowTitle("OK-Echo — 声骸强化")
        self.resize(860, 640)

        # 共享日志组件
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
            "QTextEdit { font-family: Consolas, 'Microsoft YaHei', monospace; font-size: 12px; }"
        )

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.settings_tab = SettingsTab()
        self.tabs.addTab(self.settings_tab, "设备设置")

        self.hotkey_tab = HotkeyTab()
        self.tabs.addTab(self.hotkey_tab, "热键设置")

        self.run_tab = RunTab(ok_engine, log_bridge, self.log_area)
        self.tabs.addTab(self.run_tab, "强化运行")

        self.set_config_tab = SetConfigTab()
        self.tabs.addTab(self.set_config_tab, "套装配置")
        self.set_config_tab.saved.connect(self.run_tab._load_sets)

        self.debug_tab = DebugTab(self.log_area)
        self.tabs.addTab(self.debug_tab, "调试工具")

        self.dev_tab = DevTab()
        self.tabs.addTab(self.dev_tab, "开发者")

        self.about_tab = AboutTab()
        self.tabs.addTab(self.about_tab, "关于")
