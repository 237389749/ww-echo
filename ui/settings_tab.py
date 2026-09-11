"""
设备 & 全局设置 — 窗口/截图/交互/热键/月卡。
"""
import os
import subprocess

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QLabel, QFrame, QPushButton,
                               QCheckBox, QSpinBox, QRadioButton, QButtonGroup)

from ok import og, Logger
from ok.gui.Communicate import communicate

from config import MODE_LOCAL, MODE_CLOUD

logger = Logger.get_logger(__name__)


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_picked = False  # 云模式是否已自动/手动瞄准过含"鸣潮"的窗口
        self._setup_ui()
        self._load_mode()
        self._load_config()
        self._refresh()
        communicate.adb_devices.connect(self._on_devices_updated)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ═══════ 运行模式 ═══════
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("运行模式:"))
        self.mode_local = QRadioButton("本地客户端")
        self.mode_cloud = QRadioButton("云游戏(浏览器/云客户端)")
        mode_row.addWidget(self.mode_local)
        mode_row.addWidget(self.mode_cloud)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_local)
        self.mode_group.addButton(self.mode_cloud)
        self.mode_cloud.toggled.connect(self._on_mode_changed)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet("color: #b06000; font-size: 11px;")
        layout.addWidget(self.mode_hint)

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

    # ── 运行模式 ──
    def _settings(self):
        return QSettings("OK-Echo", "OK-Echo")

    def _load_mode(self):
        mode = self._settings().value("run_mode", MODE_LOCAL)
        cloud = mode == MODE_CLOUD
        self.mode_cloud.blockSignals(True)
        self.mode_cloud.setChecked(cloud)
        self.mode_cloud.blockSignals(False)
        self._update_mode_hint(cloud)

    def _on_mode_changed(self, cloud_checked):
        mode = MODE_CLOUD if cloud_checked else MODE_LOCAL
        self._settings().setValue("run_mode", mode)
        self._update_mode_hint(cloud_checked)

    def _update_mode_hint(self, cloud):
        if cloud:
            self.mode_hint.setText(
                "云游戏模式：自动锁定标题含“鸣潮”的窗口（也可在下方列表手动改选）。"
                "已使用前台真实键鼠，请以管理员身份运行本程序；重启后生效。")
        else:
            self.mode_hint.setText(
                "本地模式：自动匹配 Client-Win64-Shipping.exe (UnrealWindow)，支持后台运行。"
                "切换模式需重启生效。")

    # ── 配置加载 ──
    def _load_config(self):
        try:
            mc = og.executor.global_config.get_config('Monthly Card Config')
            self.monthly_check.setChecked(mc.get('Check Monthly Card', False))
            self.monthly_hour.setValue(mc.get('Monthly Card Time', 4))
        except Exception:
            pass

    # ── 设备 ──
    def _refresh(self):
        og.device_manager.refresh()

    def _is_cloud(self):
        return self.mode_cloud.isChecked()

    def _on_devices_updated(self, finished):
        if not finished:
            return
        devices = og.device_manager.get_devices()
        preferred = og.device_manager.config.get("preferred", "")
        # 重建列表期间阻断 itemSelectionChanged, 避免 setCurrentRow 误触发 _on_device 造成自激刷新
        self.device_list.blockSignals(True)
        self.device_list.clear()
        sel = -1
        auto = -1  # 标题含"鸣潮"的候选窗口
        for i, d in enumerate(devices):
            conn = "✓已连接" if d.get('connected') else "✗未连接"
            item = QListWidgetItem(f"{d.get('nick', '')} [{d.get('address', '')}] {conn}")
            item.setData(Qt.UserRole, d)
            self.device_list.addItem(item)
            if d.get('imei') == preferred:
                sel = i
            if auto < 0 and '鸣潮' in str(d.get('nick', '')):
                auto = i
        if sel >= 0:
            self.device_list.setCurrentRow(sel)
        self.device_list.blockSignals(False)
        self._update_lists()
        # 云游戏模式: 尚未手动选择过且存在标题含"鸣潮"的窗口时, 自动选中它(触发连接)
        if sel < 0 and auto >= 0 and self._is_cloud() and not self._auto_picked:
            self._auto_picked = True
            self.device_list.setCurrentRow(auto)

    def _on_device(self):
        self._auto_picked = True
        item = self.device_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict) or not data.get('imei'):
            return
        try:
            # 用 item 携带的 imei 在最新设备列表里定位, 避免列表刷新竞态导致 IndexError
            devices = og.device_manager.get_devices()
            for index, d in enumerate(devices):
                if d.get('imei') == data['imei']:
                    og.device_manager.set_preferred_device(index=index)
                    self._update_lists()
                    return
            logger.warning(f"所选窗口 '{data.get('nick', '')}' 已不在设备列表, 请重新刷新")
        except Exception:
            logger.exception("选择设备失败")

    def _update_lists(self):
        self.capture_list.clear()
        self.interaction_list.clear()
        cfg = og.device_manager.windows_capture_config
        for c in (cfg.get('capture_method', []) if isinstance(cfg.get('capture_method', []), list) else [cfg.get('capture_method', '')]):
            if c:
                self.capture_list.addItem(QListWidgetItem(str(c)))
        for im in (cfg.get('interaction', []) if isinstance(cfg.get('interaction', []), list) else [cfg.get('interaction', '')]):
            if im:
                self.interaction_list.addItem(QListWidgetItem(str(im)))

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
