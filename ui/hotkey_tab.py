"""
热键设置 — 游戏内技能按键 + ok-script 启动热键。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QFrame, QPushButton)
from PySide6.QtCore import Qt

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ═══════ ok-script 热键 ═══════
        self._add_section(layout, "OK-Echo 热键", OK_HOTKEYS)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)

        # ═══════ 游戏内按键 ═══════
        self._add_section(layout, "游戏内按键 (与游戏设置保持一致)", GAME_HOTKEYS)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); layout.addWidget(sep2)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        layout.addStretch()

    def _add_section(self, layout, title, keys):
        layout.addWidget(QLabel(f"◆ {title}"))
        for label, default in keys.items():
            row = QHBoxLayout()
            lbl = QLabel(f"  {label}")
            lbl.setMinimumWidth(180)
            row.addWidget(lbl)
            edit = QLineEdit()
            edit.setMaximumWidth(100)
            edit.setText(default)
            row.addWidget(edit)
            row.addStretch()
            self._editors[label] = edit
            layout.addLayout(row)

    def _load(self):
        try:
            cfg = og.executor.global_config.get_config('Game Hotkey')
        except Exception:
            cfg = {}
        for label, edit in self._editors.items():
            default = OK_HOTKEYS.get(label) or GAME_HOTKEYS.get(label, "")
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
            key = self._label_to_key(label)
            cfg[key] = edit.text()
        og.executor.global_config.save_config('Game Hotkey', cfg)

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
