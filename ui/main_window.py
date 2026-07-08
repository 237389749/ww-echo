"""
主窗口 — 标签页布局: 强化运行 | 套装配置。
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PySide6.QtCore import Qt

from ui.run_tab import RunTab
from ui.set_config_tab import SetConfigTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OK-Echo")
        self.resize(860, 640)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.run_tab = RunTab()
        self.tabs.addTab(self.run_tab, "强化运行")

        self.set_config_tab = SetConfigTab()
        self.tabs.addTab(self.set_config_tab, "套装配置")
        self.set_config_tab.saved.connect(self.run_tab._load_sets)
