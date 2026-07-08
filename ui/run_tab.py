"""
运行面板 — 策略/套装选择, 启停控制, 实时状态, 日志。
"""
import json
import os
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QTextEdit, QLabel, QFrame)

from ok import og


class RunTab(QWidget):
    def __init__(self, ok_engine, log_bridge, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self._task = None
        self._running = False
        self._thread = None

        self._setup_ui()

        log_bridge.log_signal.connect(self._append_log)

        # 定时刷新任务状态
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 控制行 ──
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        ctrl.addWidget(self.strategy_combo)

        ctrl.addSpacing(12)
        ctrl.addWidget(QLabel("套装:"))
        self.set_combo = QComboBox()
        self.set_combo.setMinimumWidth(140)
        self._load_sets()
        ctrl.addWidget(self.set_combo)

        ctrl.addStretch()

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setMinimumWidth(80)
        self.start_btn.clicked.connect(self._start)
        ctrl.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setMinimumWidth(80)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        ctrl.addWidget(self.stop_btn)

        layout.addLayout(ctrl)

        # ── 状态栏 ──
        status = QHBoxLayout()
        self.success_label = QLabel("成功: 0")
        self.fail_label = QLabel("失败: 0")
        self.score_label = QLabel("得分: -")
        self.tier_label = QLabel("进度: -")
        for lbl in [self.success_label, self.fail_label, self.score_label, self.tier_label]:
            lbl.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 8px;")
            status.addWidget(lbl)
        status.addStretch()
        layout.addLayout(status)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # ── 日志 ──
        layout.addWidget(QLabel("运行日志"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
            "QTextEdit { font-family: Consolas, 'Microsoft YaHei', monospace; font-size: 12px; }"
        )
        layout.addWidget(self.log_area, 1)

    # ── 套装下拉 ──
    def _load_sets(self):
        path = os.path.join("assets", "echo_set_templates.json")
        current = self.set_combo.currentText() if self.set_combo.count() > 0 else ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            names = list(data.get("sets", {}).keys())
        except Exception:
            names = []
        self.set_combo.clear()
        self.set_combo.addItem("通用")
        self.set_combo.addItems(names)
        if current in names:
            self.set_combo.setCurrentText(current)

    def _append_log(self, text):
        self.log_area.append(text)
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── 状态刷新 ──
    def _refresh_status(self):
        task = self._get_task()
        if task is None:
            return
        try:
            self.success_label.setText(f"成功: {task.info_get('成功声骸数量') or 0}")
            self.fail_label.setText(f"失败: {task.info_get('失败声骸数量') or 0}")
            score = task.info_get('声骸得分')
            self.score_label.setText(f"得分: {score}" if score else "得分: -")
        except Exception:
            pass

    # ── 启停 ──
    def _start(self):
        task = self._get_task()
        if task is None:
            self._append_log("[ERROR] 任务未就绪")
            return
        if self._running:
            return

        task.config['强化策略'] = self.strategy_combo.currentText()
        task.config['当前套装'] = self.set_combo.currentText()

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._append_log("══════════ 开始强化 ══════════")
        self._append_log(f"策略: {task.config.get('强化策略')}  套装: {task.config.get('当前套装')}")

        self._thread = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._thread.start()

    def _stop(self):
        task = self._get_task()
        if task:
            task.disable()
            task.unpause()
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log("══════════ 已停止 ══════════")

    def _run_task(self, task):
        try:
            og.app.start_controller.start(task)
        except Exception as e:
            self._append_log(f"[ERROR] {e}")
        finally:
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 任务结束 ══════════")

    def _get_task(self):
        if self._task is not None:
            return self._task
        try:
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            self._task = og.executor.get_task_by_class(EnhanceEchoTask)
            return self._task
        except Exception:
            return None
