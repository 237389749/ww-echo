"""
设备 & 全局设置 — Fluent 卡片式设置页。

设计口径(参考 qfluentwidgets Gallery 的 Settings 页与 Windows 11 设置):
- 每个设置项一张卡: 左侧图标 + 标题 + 一句话说明, 控件右对齐; 同类项归入 `SettingCardGroup`;
- 页面可滚动(旧版在 520px 高度下会把下半页内容裁掉), 字号层级用 TitleLabel/CaptionLabel;
- 反馈用 `InfoBar`(保存成功/需重启), 危险动作(重启)用 `MessageBox` 确认。

行为与旧版保持一致: 运行模式写 QSettings("OK-Echo") 的 `run_mode`; 窗口/截图/交互直连 `og.device_manager`;
**新增**: 主题切换、重启按钮; 并修掉旧版"后台静音 / 检查月卡 只读不写(等于装饰控件)"的问题 —— 现在改动即保存。
"""
import os
import subprocess
import sys

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
                            MessageBox, PushButton, PushSettingCard, SettingCard, SettingCardGroup,
                            SingleDirectionScrollArea, SpinBox, StrongBodyLabel, SwitchSettingCard,
                            TitleLabel, Theme)

from ok import og, Logger
from ok.gui.Communicate import communicate

from config import MODE_LOCAL, MODE_CLOUD
from ui.widgets import make_scroll_transparent

logger = Logger.get_logger(__name__)

THEME_ITEMS = (("浅色", Theme.LIGHT.name), ("深色", Theme.DARK.name), ("跟随系统", Theme.AUTO.name))


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_picked = False  # 云模式是否已自动/手动瞄准过含"鸣潮"的窗口
        self._settings = QSettings("OK-Echo", "OK-Echo")
        self._setup_ui()
        self._load_mode()
        self._load_config()
        self._load_theme()
        self._refresh()
        communicate.adb_devices.connect(self._on_devices_updated)

    # ══════════════════ UI ══════════════════
    def _setup_ui(self):
        self.view = QWidget()
        self.view.setObjectName("settingsView")
        vbox = QVBoxLayout(self.view)
        vbox.setContentsMargins(24, 20, 24, 24)
        vbox.setSpacing(16)

        title = TitleLabel(); title.setText("设备设置")
        sub = CaptionLabel(); sub.setText("改动即时保存; 标注「需重启」的项在重开程序后生效。")
        vbox.addWidget(title)
        vbox.addWidget(sub)
        vbox.addSpacing(4)

        vbox.addWidget(self._group_mode())
        vbox.addWidget(self._group_window())
        vbox.addWidget(self._group_capture())
        vbox.addWidget(self._group_misc())
        vbox.addWidget(self._group_appearance())
        vbox.addWidget(self._group_tools())

        ver = CaptionLabel()
        ver.setText(f"OK-Echo v{og.config.get('version', 'dev')} · 引擎 ok-script · 界面 qfluentwidgets")
        vbox.addWidget(ver)
        vbox.addStretch(1)

        scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.view)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _group_mode(self) -> SettingCardGroup:
        g = SettingCardGroup("运行模式", self.view)
        self.mode_card = SwitchSettingCard(
            FIF.CLOUD, "云游戏模式", "", None, self.view)
        self.mode_card.checkedChanged.connect(self._on_mode_changed)
        self.restart_card = PushSettingCard(
            "立即重启", FIF.SYNC, "应用运行模式", "切换本地/云游戏需要重启程序后生效", self.view)
        self.restart_card.clicked.connect(self._restart)
        g.addSettingCards([self.mode_card, self.restart_card])
        return g

    def _group_window(self) -> SettingCardGroup:
        g = SettingCardGroup("窗口与设备", self.view)
        self.device_card = SettingCard(
            FIF.IOT, "目标窗口",
            "云游戏: 自动锁定标题含「鸣潮」的窗口(也可在此手动改选); 本地: 自动匹配 UnrealWindow", self.view)
        self.device_combo = ComboBox()
        self.device_combo.setMinimumWidth(330)
        self.device_combo.currentIndexChanged.connect(self._on_device)
        self.refresh_btn = PushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._refresh)
        self._add_widget(self.device_card, self.device_combo)
        self.device_card.hBoxLayout.addWidget(self.refresh_btn)
        self.device_card.hBoxLayout.addSpacing(16)
        g.addSettingCard(self.device_card)

        self.device_status = CaptionLabel()
        g.vBoxLayout.insertWidget(g.vBoxLayout.count() - 1, self.device_status)
        return g

    def _group_capture(self) -> SettingCardGroup:
        g = SettingCardGroup("截图与交互", self.view)
        self.capture_card = SettingCard(
            FIF.CAMERA, "截图方式",
            "云游戏/被遮挡窗口用 BitBlt_RenderFull; WGC 抓浏览器窗口常黑屏", self.view)
        self.capture_combo = ComboBox()
        self.capture_combo.setMinimumWidth(240)
        self.capture_combo.currentIndexChanged.connect(self._on_capture)
        self._add_widget(self.capture_card, self.capture_combo)

        self.interaction_card = SettingCard(
            FIF.ROBOT, "交互方式",
            "PostMessage 可后台运行; Pynput 为前台真实键鼠(云游戏必须, 需管理员)", self.view)
        self.interaction_combo = ComboBox()
        self.interaction_combo.setMinimumWidth(240)
        self.interaction_combo.currentIndexChanged.connect(self._on_interaction)
        self._add_widget(self.interaction_card, self.interaction_combo)

        self.hotkey_card = SettingCard(
            FIF.GAME, "启动 / 停止热键", "全局热键; 游戏内技能键在「热键设置」页配置", self.view)
        self.hotkey_label = StrongBodyLabel(); self.hotkey_label.setText("F9")
        self._add_widget(self.hotkey_card, self.hotkey_label)
        g.addSettingCards([self.capture_card, self.interaction_card, self.hotkey_card])
        return g

    def _group_misc(self) -> SettingCardGroup:
        g = SettingCardGroup("其它", self.view)
        self.mute_card = SwitchSettingCard(
            FIF.MEGAPHONE, "后台静音", "任务运行时把游戏窗口静音(即 ok-script 的 Mute Game while in Background)",
            None, self.view)
        self.mute_card.checkedChanged.connect(self._save_mute)
        self.monthly_card = SwitchSettingCard(
            FIF.CERTIFICATE, "检查月卡", "启动任务前检查月卡弹窗, 避免打断", None, self.view)
        self.monthly_card.checkedChanged.connect(self._save_monthly)
        self.monthly_hour_card = SettingCard(
            FIF.HISTORY, "月卡时间", "月卡弹窗出现的本机小时(0-23)", self.view)
        self.monthly_hour = SpinBox()
        self.monthly_hour.setRange(0, 23)
        self.monthly_hour.valueChanged.connect(self._save_monthly)
        self._add_widget(self.monthly_hour_card, self.monthly_hour)
        g.addSettingCards([self.mute_card, self.monthly_card, self.monthly_hour_card])
        return g

    def _group_appearance(self) -> SettingCardGroup:
        g = SettingCardGroup("外观", self.view)
        self.theme_card = SettingCard(
            FIF.PALETTE, "主题", "深色主题仍在逐页适配(个别页面的固定色未完全跟随)", self.view)
        self.theme_combo = ComboBox()
        self.theme_combo.addItems([label for label, _ in THEME_ITEMS])
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        self._add_widget(self.theme_card, self.theme_combo)
        g.addSettingCard(self.theme_card)
        return g

    def _group_tools(self) -> SettingCardGroup:
        g = SettingCardGroup("工具", self.view)
        self.open_dir_card = PushSettingCard(
            "打开安装目录", FIF.FOLDER, "程序目录", os.getcwd(), self.view)
        self.open_dir_card.clicked.connect(self._open_cwd)
        g.addSettingCard(self.open_dir_card)
        return g

    @staticmethod
    def _add_widget(card: SettingCard, widget: QWidget):
        """把控件右对齐放进设置卡(Gallery 的标准写法: 追加到 hBoxLayout 末尾 + 补 16px 右边距)。"""
        card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
        card.hBoxLayout.addSpacing(16)

    # ══════════════════ 运行模式 ══════════════════
    def _load_mode(self):
        """读取 QSettings → 开关。**阻断信号**: 否则 setValue 会触发 checkedChanged, 启动就弹"已切换"假提示。"""
        cloud = self._settings.value("run_mode", MODE_LOCAL) == MODE_CLOUD
        self.mode_card.blockSignals(True)
        self.mode_card.setValue(cloud)
        self.mode_card.blockSignals(False)
        self._update_mode_hint(cloud)

    def _on_mode_changed(self, cloud: bool):
        self._settings.setValue("run_mode", MODE_CLOUD if cloud else MODE_LOCAL)
        self._update_mode_hint(cloud)
        InfoBar.success("运行模式已切换", "需重启程序后生效（可点上方「立即重启」）", duration=4000,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _update_mode_hint(self, cloud: bool):
        if cloud:
            self.mode_card.setContent(
                "云游戏: 浏览器/云客户端窗口, 前台真实键鼠注入 → 需以管理员身份运行; 任务运行中勿最小化游戏。")
        else:
            self.mode_card.setContent(
                "本地客户端: 自动匹配 Client-Win64-Shipping.exe (UnrealWindow), 支持后台运行。")

    def _restart(self):
        box = MessageBox("重启程序", "切换运行模式需要重启程序后生效。\n现在重启吗？", self.window())
        if not box.exec():
            return
        try:
            QProcess.startDetached(sys.executable, [os.path.abspath(sys.argv[0])])
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("重启失败", f"{e}（请手动关闭后重新运行）", duration=5000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        from ok.gui.Communicate import communicate as _comm
        _comm.quit.emit()

    # ══════════════════ 配置读写 ══════════════════
    def _global_config(self):
        return og.executor.global_config

    def _load_config(self):
        """读取引擎配置 → 控件。**阻断信号**: 否则 setValue 会立刻触发"保存"回写(无意义且有副作用)。"""
        try:
            mc = self._global_config().get_config('Monthly Card Config')
            for w in (self.monthly_card, self.monthly_hour):
                w.blockSignals(True)
            self.monthly_card.setValue(bool(mc.get('Check Monthly Card', False)))
            self.monthly_hour.setValue(int(mc.get('Monthly Card Time', 4)))
            for w in (self.monthly_card, self.monthly_hour):
                w.blockSignals(False)
        except Exception:
            logger.debug("读取月卡配置失败", exc_info=True)
        try:
            from ok.util.GlobalConfig import basic_options
            basic = self._global_config().get_config(basic_options)
            self.mute_card.blockSignals(True)
            self.mute_card.setValue(bool(basic.get('Mute Game while in Background', False)))
            self.mute_card.blockSignals(False)
        except Exception:
            logger.debug("读取静音配置失败", exc_info=True)

    def _save_monthly(self, *_):
        """旧版这两个控件只读不写(等于装饰); 现在改动即写回引擎配置。"""
        try:
            cfg = self._global_config().get_config('Monthly Card Config')
            cfg['Check Monthly Card'] = self.monthly_card.isChecked()
            cfg['Monthly Card Time'] = self.monthly_hour.value()
            cfg.save_file()
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("保存失败", f"月卡设置: {e}", duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _save_mute(self, checked: bool):
        try:
            from ok.util.GlobalConfig import basic_options
            cfg = self._global_config().get_config(basic_options)
            cfg['Mute Game while in Background'] = bool(checked)
            cfg.save_file()
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("保存失败", f"静音设置: {e}", duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ══════════════════ 主题 ══════════════════
    def _load_theme(self):
        key = str(self._settings.value("theme", Theme.LIGHT.name))
        idx = next((i for i, (_, k) in enumerate(THEME_ITEMS) if k == key), 0)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)

    def _on_theme(self, index: int):
        if not 0 <= index < len(THEME_ITEMS):
            return
        label, key = THEME_ITEMS[index]
        win = self.window()
        if hasattr(win, "apply_theme"):
            win.apply_theme(key)
        self._settings.setValue("theme", key)
        InfoBar.success("主题已切换", f"当前: {label}", duration=2000,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ══════════════════ 设备 ══════════════════
    def _refresh(self):
        og.device_manager.refresh()

    def _is_cloud(self):
        return self.mode_card.isChecked()

    def _on_devices_updated(self, finished):
        if not finished:
            return
        devices = og.device_manager.get_devices()
        preferred = og.device_manager.config.get("preferred", "")

        # 重建下拉期间阻断信号, 避免 setCurrentIndex 误触发 _on_device 造成自激刷新
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        sel = auto = -1
        for i, d in enumerate(devices):
            state = "已连接" if d.get('connected') else "未连接"
            self.device_combo.addItem(f"{d.get('nick', '')}  ·  {state}")
            if d.get('imei') == preferred:
                sel = i
            if auto < 0 and '鸣潮' in str(d.get('nick', '')):
                auto = i
        if not devices:
            self.device_combo.addItem("（未找到可用窗口，点右侧「刷新列表」）")
        if sel >= 0:
            self.device_combo.setCurrentIndex(sel)
        self.device_combo.blockSignals(False)

        connected = sum(1 for d in devices if d.get('connected'))
        self.device_status.setText(f"共 {len(devices)} 个窗口, {connected} 个已连接"
                                   + ("（云游戏模式会自动选中标题含「鸣潮」的窗口）" if self._is_cloud() else ""))
        self._update_lists()
        # 云游戏模式: 尚未手动选择过且存在标题含"鸣潮"的窗口时, 自动选中它(触发连接)
        if sel < 0 and auto >= 0 and self._is_cloud() and not self._auto_picked:
            self._auto_picked = True
            self.device_combo.setCurrentIndex(auto)

    def _on_device(self, index: int):
        self._auto_picked = True
        devices = og.device_manager.get_devices()
        if not 0 <= index < len(devices):
            return
        data = devices[index]
        if not isinstance(data, dict) or not data.get('imei'):
            return
        try:
            for i, d in enumerate(devices):        # 用 imei 定位, 避免列表刷新竞态
                if d.get('imei') == data['imei']:
                    og.device_manager.set_preferred_device(index=i)
                    self._update_lists()
                    InfoBar.success("已选择窗口", str(data.get('nick', '')), duration=2000,
                                    position=InfoBarPosition.TOP_RIGHT, parent=self)
                    return
            logger.warning(f"所选窗口 '{data.get('nick', '')}' 已不在设备列表, 请重新刷新")
        except Exception:
            logger.exception("选择设备失败")

    def _update_lists(self):
        """按引擎当前可选项重建"截图方式/交互方式"下拉(重建期间阻断信号, 避免误触发应用)。"""
        cfg = og.device_manager.windows_capture_config
        for combo, key in ((self.capture_combo, 'capture_method'),
                           (self.interaction_combo, 'interaction')):
            raw = cfg.get(key, [])
            items = [str(x) for x in (raw if isinstance(raw, list) else [raw]) if x]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            try:
                cur = str(og.device_manager.config.get(key, ''))
                if cur in items:
                    combo.setCurrentIndex(items.index(cur))
            except Exception:
                pass
            combo.blockSignals(False)

    def _on_capture(self, index: int):
        methods = og.device_manager.windows_capture_config.get('capture_method', [])
        if isinstance(methods, str):
            methods = [methods]
        if 0 <= index < len(methods):
            og.device_manager.set_capture(methods[index])

    def _on_interaction(self, index: int):
        methods = og.device_manager.windows_capture_config.get('interaction', [])
        if isinstance(methods, str):
            methods = [methods]
        if 0 <= index < len(methods):
            og.device_manager.set_interaction(methods[index])

    # ══════════════════ 工具 ══════════════════
    def _open_cwd(self):
        subprocess.Popen(f'explorer "{os.getcwd()}"')
