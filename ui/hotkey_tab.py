"""
热键设置 — 游戏内技能按键 + OK-Echo 启动热键(Fluent 卡片式)。

口径: 游戏内按键必须与游戏设置一致(程序靠模拟按键操作); 启动/停止由 ok-script 控制, 暂只读。
保存写回 ok-script 的 `Game Hotkey` 配置, 成功/失败用 InfoBar 反馈。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition, LineEdit,
                            PushSettingCard, SettingCard, SettingCardGroup, SingleDirectionScrollArea,
                            StrongBodyLabel, TitleLabel)

from ok import og

# 游戏内按键默认值
GAME_HOTKEYS = {
    "声骸技能 (Echo)": "q",
    "共鸣解放 (Liberation)": "r",
    "共鸣技能 (Resonance)": "e",
    "声骸工具 (Tool)": "t",
    "跳跃 (Jump)": "space",
    "闪避 (Dodge)": "lshift",
    "轮盘 (Wheel)": "tab",
    "索拉指南 (Guidebook)": "f2",
}

OK_HOTKEYS = {
    "启动/停止 (Start/Stop)": "F9",
}


class HotkeyTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._editors = {}
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        self.view = QWidget()
        self.view.setObjectName("hotkeyView")
        vbox = QVBoxLayout(self.view)
        vbox.setContentsMargins(24, 20, 24, 24)
        vbox.setSpacing(16)

        title = TitleLabel()
        title.setText("热键设置")
        sub = CaptionLabel()
        sub.setText("游戏内按键必须与游戏设置保持一致(程序靠模拟按键操作); 改完点最下方「保存」。")
        vbox.addWidget(title)
        vbox.addWidget(sub)
        vbox.addSpacing(4)

        # ── OK-Echo 自身热键(只读) ──
        g_ok = SettingCardGroup("OK-Echo 热键", self.view)
        for label, default in OK_HOTKEYS.items():
            card = SettingCard(FIF.GAME, label, "由 ok-script 全局控制, 暂不支持在界面修改", self.view)
            value = StrongBodyLabel()
            value.setText(default)
            card.hBoxLayout.addWidget(value, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(16)
            g_ok.addSettingCard(card)
        vbox.addWidget(g_ok)

        # ── 游戏内按键 ──
        g_game = SettingCardGroup("游戏内按键 (与游戏设置一致)", self.view)
        for label, default in GAME_HOTKEYS.items():
            card = SettingCard(FIF.LABEL, label, "填游戏里该功能绑定的按键, 如 q / e / space / lshift", self.view)
            edit = LineEdit()
            edit.setFixedWidth(110)
            edit.setText(default)
            card.hBoxLayout.addWidget(edit, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(16)
            self._editors[label] = edit
            g_game.addSettingCard(card)
        vbox.addWidget(g_game)

        save_card = PushSettingCard("保存", FIF.SAVE, "保存热键",
                                    "写入 ok-script 的 Game Hotkey 配置(立即生效)", self.view)
        save_card.clicked.connect(self._save)
        vbox.addWidget(save_card)
        vbox.addStretch(1)

        scroll = SingleDirectionScrollArea(orient=Qt.Vertical)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.view)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _load(self):
        try:
            cfg = og.executor.global_config.get_config('Game Hotkey')
        except Exception:
            cfg = {}
        for label, edit in self._editors.items():
            default = GAME_HOTKEYS.get(label, "")
            key = self._label_to_key(label)
            val = cfg.get(key, default)
            edit.setText(str(val))

    def _save(self):
        try:
            cfg = og.executor.global_config.get_config('Game Hotkey')
        except Exception:
            cfg = {}
        for label, edit in self._editors.items():
            if label in OK_HOTKEYS:
                continue  # 启动热键暂时只读
            cfg[self._label_to_key(label)] = edit.text()
        try:
            og.executor.global_config.save_config('Game Hotkey', cfg)
            InfoBar.success("已保存", "游戏内按键已写入配置", duration=2500,
                            position=InfoBarPosition.TOP_RIGHT, parent=self)
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("保存失败", str(e), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _label_to_key(self, label):
        # "声骸技能 (Echo)" → "Echo Key"
        name = label.split(" (")[0]
        mapping = {
            "声骸技能": "Echo Key",
            "共鸣解放": "Liberation Key",
            "共鸣技能": "Resonance Key",
            "声骸工具": "Tool Key",
            "跳跃": "Jump Key",
            "闪避": "Dodge Key",
            "轮盘": "Wheel Key",
            "索拉指南": "Guidebook Key",
        }
        return mapping.get(name, label)
