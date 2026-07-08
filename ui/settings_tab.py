"""
设备 & 全局设置 — 窗口/截图/交互/热键/月卡。
"""
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QLabel, QFrame, QPushButton,
                               QCheckBox, QSpinBox)

from ok import og, Logger
from ok.gui.Communicate import communicate

logger = Logger.get_logger(__name__)


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_config()
        self._refresh()
        communicate.adb_devices.connect(self._on_devices_updated)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ═══════ 设备 ═══════
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("选择窗口"))
        toolbar.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(100)
        self.device_list.itemSelectionChanged.connect(self._on_device)
        layout.addWidget(self.device_list)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)

        # 截图 & 交互并排
        row = QHBoxLayout()
        c = QVBoxLayout()
        c.addWidget(QLabel("截图方式"))
        self.capture_list = QListWidget()
        self.capture_list.setMaximumHeight(80)
        self.capture_list.itemSelectionChanged.connect(self._on_capture)
        c.addWidget(self.capture_list)
        row.addLayout(c)

        c2 = QVBoxLayout()
        c2.addWidget(QLabel("交互方式"))
        self.interaction_list = QListWidget()
        self.interaction_list.setMaximumHeight(80)
        self.interaction_list.itemSelectionChanged.connect(self._on_interaction)
        c2.addWidget(self.interaction_list)
        row.addLayout(c2)
        layout.addLayout(row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); layout.addWidget(sep2)

        # ═══════ 全局 ═══════
        g = QHBoxLayout()
        g.addWidget(QLabel("启动/停止热键:"))
        self.hotkey_label = QLabel("F9")
        self.hotkey_label.setStyleSheet("font-weight: bold;")
        g.addWidget(self.hotkey_label)
        g.addStretch()
        layout.addLayout(g)

        g2 = QHBoxLayout()
        g2.addWidget(QLabel("后台静音"))
        self.mute_check = QCheckBox()
        g2.addWidget(self.mute_check)
        g2.addSpacing(16)
        g2.addWidget(QLabel("检查月卡"))
        self.monthly_check = QCheckBox()
        g2.addWidget(self.monthly_check)
        g2.addWidget(QLabel("月卡时间(时)"))
        self.monthly_hour = QSpinBox()
        self.monthly_hour.setRange(0, 23)
        self.monthly_hour.setValue(4)
        g2.addWidget(self.monthly_hour)
        g2.addStretch()
        layout.addLayout(g2)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); layout.addWidget(sep3)

        # ═══════ 工具 ═══════
        tools = QHBoxLayout()
        for text, slot in [
            ("打开安装目录", self._open_cwd),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        tools.addStretch()
        layout.addLayout(tools)

        # ═══════ 版本 ═══════
        sep4 = QFrame(); sep4.setFrameShape(QFrame.HLine); layout.addWidget(sep4)
        ver = QLabel(f"OK-Echo  v{og.config.get('version', 'dev')}  |  ok-script")
        ver.setStyleSheet("color: #888;")
        layout.addWidget(ver)

        # spacer
        layout.addStretch()

    # ── 配置加载 ──
    def _load_config(self):
        try:
            key_cfg = og.executor.global_config.get_config('Game Hotkey')
            self.hotkey_label.setText(key_cfg.get('Start/Stop', 'F9'))
        except Exception:
            pass
        try:
            mc = og.executor.global_config.get_config('Monthly Card Config')
            self.monthly_check.setChecked(mc.get('Check Monthly Card', False))
            self.monthly_hour.setValue(mc.get('Monthly Card Time', 4))
        except Exception:
            pass

    # ── 设备 ──
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
        if i < 0: return
        og.device_manager.set_preferred_device(index=i)
        self._update_lists()

    def _update_lists(self):
        self.capture_list.clear()
        self.interaction_list.clear()
        cfg = og.device_manager.windows_capture_config
        for c in (cfg.get('capture_method', []) if isinstance(cfg.get('capture_method', []), list) else [cfg.get('capture_method', '')]):
            self.capture_list.addItem(QListWidgetItem(str(c)) if c else None)
        for im in (cfg.get('interaction', []) if isinstance(cfg.get('interaction', []), list) else [cfg.get('interaction', '')]):
            self.interaction_list.addItem(QListWidgetItem(str(im)) if im else None)

    def _on_capture(self):
        i = self.capture_list.currentRow()
        if i < 0: return
        methods = og.device_manager.windows_capture_config.get('capture_method', [])
        if isinstance(methods, str): methods = [methods]
        if i < len(methods): og.device_manager.set_capture(methods[i])

    def _on_interaction(self):
        i = self.interaction_list.currentRow()
        if i < 0: return
        methods = og.device_manager.windows_capture_config.get('interaction', [])
        if isinstance(methods, str): methods = [methods]
        if i < len(methods): og.device_manager.set_interaction(methods[i])

    # ── 工具 ──
    def _open_cwd(self):
        subprocess.Popen(f'explorer "{os.getcwd()}"')
