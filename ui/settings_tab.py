"""
设备设置 — 选择游戏窗口, 截图方式, 交互方式。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QLabel, QFrame, QPushButton)

from ok import og, Logger
from ok.gui.Communicate import communicate

logger = Logger.get_logger(__name__)


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        communicate.adb_devices.connect(self._on_devices_updated)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 设备列表 ──
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("选择窗口"))
        toolbar.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self.device_list = QListWidget()
        self.device_list.itemSelectionChanged.connect(self._on_device)
        layout.addWidget(self.device_list, 1)

        # ── 截图方式 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)
        layout.addWidget(QLabel("截图方式"))

        self.capture_list = QListWidget()
        self.capture_list.itemSelectionChanged.connect(self._on_capture)
        layout.addWidget(self.capture_list)

        # ── 交互方式 ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        layout.addWidget(sep2)
        layout.addWidget(QLabel("交互方式"))

        self.interaction_list = QListWidget()
        self.interaction_list.itemSelectionChanged.connect(self._on_interaction)
        layout.addWidget(self.interaction_list)

    # ── 刷新 ──
    def _refresh(self):
        og.device_manager.refresh()

    def _on_devices_updated(self, finished):
        if not finished:
            return
        devices = og.device_manager.get_devices()
        preferred = og.device_manager.config.get("preferred", "")
        self.device_list.clear()
        sel = -1
        for i, d in enumerate(devices):
            conn = "✓已连接" if d.get('connected') else "✗未连接"
            item = QListWidgetItem(f"{d.get('nick', '')} [{d.get('address', '')}] {conn}")
            item.setData(Qt.UserRole, d)
            self.device_list.addItem(item)
            if d.get('imei') == preferred:
                sel = i
        if sel >= 0:
            self.device_list.setCurrentRow(sel)
            self._update_lists()

    def _on_device(self):
        i = self.device_list.currentRow()
        if i < 0:
            return
        og.device_manager.set_preferred_device(index=i)
        self._update_lists()

    def _update_lists(self):
        self.capture_list.clear()
        self.interaction_list.clear()
        cfg = og.device_manager.windows_capture_config
        caps = cfg.get('capture_method', [])
        if isinstance(caps, str):
            caps = [caps]
        for c in caps:
            self.capture_list.addItem(QListWidgetItem(str(c)))

        ints = cfg.get('interaction', [])
        if isinstance(ints, str):
            ints = [ints]
        for im in ints:
            self.interaction_list.addItem(QListWidgetItem(str(im)))

    def _on_capture(self):
        i = self.capture_list.currentRow()
        if i < 0:
            return
        cfg = og.device_manager.windows_capture_config
        methods = cfg.get('capture_method', [])
        if isinstance(methods, str):
            methods = [methods]
        if i < len(methods):
            og.device_manager.set_capture(methods[i])

    def _on_interaction(self):
        i = self.interaction_list.currentRow()
        if i < 0:
            return
        cfg = og.device_manager.windows_capture_config
        methods = cfg.get('interaction', [])
        if isinstance(methods, str):
            methods = [methods]
        if i < len(methods):
            og.device_manager.set_interaction(methods[i])
