"""
运行面板 — 策略/套装选择, 启停控制, 实时日志。
"""
import json
import os
import logging
import threading

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QTextEdit, QLabel, QFrame)

from ok import og

logger = logging.getLogger(__name__)


class RunTab(QWidget):
    def __init__(self, ok_engine, log_bridge, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self._task = None
        self._running = False
        self._thread = None
        self._setup_ui()

        # 日志桥接
        log_bridge.log_signal.connect(self._append_log)

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

        ctrl.addSpacing(16)
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

        # ── 分隔 ──
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
        if current and current in names:
            self.set_combo.setCurrentText(current)

    def _append_log(self, text):
        self.log_area.append(text)
        # 自动滚到底部
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── 任务控制 ──
    def _start(self):
        task = self._get_task()
        if task is None:
            self._append_log("[ERROR] 任务未就绪, 请稍后重试")
            return
        if self._running:
            return

        # 同步 UI 配置到任务
        task.config['强化策略'] = self.strategy_combo.currentText()
        task.config['当前套装'] = self.set_combo.currentText()

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._append_log("══════════ 开始强化 ══════════")
        self._append_log(f"策略: {task.config.get('强化策略')}")
        self._append_log(f"套装: {task.config.get('当前套装')}")

        # 在后台线程跑任务
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
            # 使用 ok-script 的 StartController 启动完整流程
            og.app.start_controller.start(task)
        except Exception as e:
            self._append_log(f"[ERROR] {e}")
        finally:
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _get_task(self):
        """获取 EnhanceEchoTask 实例。"""
        if self._task is not None:
            return self._task
        try:
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            self._task = og.executor.get_task_by_class(EnhanceEchoTask)
            return self._task
        except Exception as e:
            logger.warning(f"获取任务失败: {e}")
            return None
