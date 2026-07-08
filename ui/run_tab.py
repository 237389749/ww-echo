"""
运行面板 — 强化策略选择, 启停控制, 实时日志。
"""
import json
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QTextEdit, QLabel, QFrame, QSizePolicy)


class RunTab(QWidget):
    log_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.log_signal.connect(self._append_log)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 控制行 ──
        ctrl = QHBoxLayout()

        ctrl.addWidget(QLabel("强化策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        ctrl.addWidget(self.strategy_combo)

        ctrl.addSpacing(16)
        ctrl.addWidget(QLabel("当前套装:"))
        self.set_combo = QComboBox()
        self.set_combo.setMinimumWidth(140)
        self._load_sets()
        ctrl.addWidget(self.set_combo)

        ctrl.addStretch()

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setMinimumWidth(80)
        self.start_btn.clicked.connect(self._on_start)
        ctrl.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setMinimumWidth(80)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        ctrl.addWidget(self.stop_btn)

        layout.addLayout(ctrl)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # ── 日志区 ──
        layout.addWidget(QLabel("运行日志"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("QTextEdit { font-family: Consolas, monospace; font-size: 12px; }")
        layout.addWidget(self.log_area, 1)

    def _load_sets(self):
        path = os.path.join("assets", "echo_set_templates.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            names = list(data.get("sets", {}).keys())
            self.set_combo.clear()
            self.set_combo.addItem("通用")
            self.set_combo.addItems(names)
        except Exception:
            self.set_combo.addItem("通用")

    def _append_log(self, text):
        self.log_area.append(text)

    def log(self, text):
        self.log_signal.emit(text)

    def _on_start(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log("══════════ 任务开始 ══════════")
        self.log(f"策略: {self.strategy_combo.currentText()}")
        self.log(f"套装: {self.set_combo.currentText()}")
        self.log("(执行引擎接入中...)")

    def _on_stop(self):
        self.log("══════════ 任务停止 ══════════")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
