"""
运行面板 — 任务/策略/套装选择, 启停, 状态, 日志。
"""
import json
import os
import threading

from PySide6.QtCore import QTimer, QSettings
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QTextEdit, QLabel, QFrame,
                               QCheckBox)

from ok import og


class RunTab(QWidget):
    def __init__(self, ok_engine, log_bridge, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self._task = None
        self._running = False
        self._thread = None
        self._settings = QSettings("OK-Echo", "RunTab")

        self._setup_ui()
        self._load_settings()

        log_bridge.log_signal.connect(self._append_log)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 第1行: 任务选择 + 策略 ──
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("任务:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(["批量强化声骸", "批量修改主属性"])
        row1.addWidget(self.task_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        row1.addWidget(self.strategy_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("套装:"))
        self.set_combo = QComboBox()
        self.set_combo.setMinimumWidth(140)
        self._load_sets()
        row1.addWidget(self.set_combo)

        row1.addStretch()
        layout.addLayout(row1)

        # ── 第2行: 传统模式选项 ──
        self.traditional_opts = QWidget()
        trad = QHBoxLayout(self.traditional_opts)
        trad.setContentsMargins(0, 0, 0, 0)
        self.opt_double_crit = QCheckBox("必须有双爆")
        self.opt_double_crit.setChecked(True)
        trad.addWidget(self.opt_double_crit)
        self.opt_all_valid_before_crit = QCheckBox("双爆前全有效")
        self.opt_all_valid_before_crit.setChecked(True)
        trad.addWidget(self.opt_all_valid_before_crit)
        self.opt_first_must_valid = QCheckBox("首条必须有效")
        self.opt_first_must_valid.setChecked(True)
        trad.addWidget(self.opt_first_must_valid)
        trad.addSpacing(8)
        trad.addWidget(QLabel("首条双爆≥"))
        self.opt_first_crit = QComboBox()
        self.opt_first_crit.setMinimumWidth(60)
        self.opt_first_crit.addItems([str(x) for x in [6.3, 6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5]])
        self.opt_first_crit.setCurrentText("6.9")
        trad.addWidget(self.opt_first_crit)
        trad.addWidget(QLabel("双爆总计≥"))
        self.opt_total_crit = QComboBox()
        self.opt_total_crit.setMinimumWidth(60)
        self.opt_total_crit.addItems([str(x) for x in [6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5, 12.0, 13.8, 15.0, 16.5, 18.0]])
        self.opt_total_crit.setCurrentText("13.8")
        trad.addWidget(self.opt_total_crit)
        trad.addWidget(QLabel("有效词条≥"))
        self.opt_valid_count = QComboBox()
        self.opt_valid_count.setMinimumWidth(50)
        self.opt_valid_count.addItems(["1", "2", "3", "4", "5"])
        self.opt_valid_count.setCurrentText("3")
        trad.addWidget(self.opt_valid_count)
        trad.addStretch()
        self.traditional_opts.setVisible(False)
        layout.addWidget(self.traditional_opts)

        self.strategy_combo.currentTextChanged.connect(
            lambda s: self.traditional_opts.setVisible(s == "传统"))

        # 通用选项
        row_gen = QHBoxLayout()
        self.opt_pause = QCheckBox("成功后暂停")
        self.opt_pause.setChecked(True)
        row_gen.addWidget(self.opt_pause)
        row_gen.addStretch()
        layout.addLayout(row_gen)

        # 传统模式额外选项: 评分
        trad2 = QHBoxLayout()
        self.opt_score_enable = QCheckBox("启用评分模式")
        trad2.addWidget(self.opt_score_enable)
        trad2.addWidget(QLabel("最低得分≥"))
        self.opt_score_min = QComboBox()
        self.opt_score_min.setMinimumWidth(60)
        for v in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
            self.opt_score_min.addItem(str(v))
        self.opt_score_min.setCurrentText("3.0")
        trad2.addWidget(self.opt_score_min)
        trad2.addStretch()
        layout.addLayout(trad2)

        # 修改主属性: 目标属性和策略行 (默认隐藏)
        self.change_opts = QWidget()
        chg = QHBoxLayout(self.change_opts)
        chg.setContentsMargins(0, 0, 0, 0)
        chg.addWidget(QLabel("目标属性:"))
        self.change_target = QComboBox()
        self.change_target.addItems([
            "攻击", "暴击伤害", "暴击", "生命", "防御", "共鸣效率",
            "冷凝伤害加成", "热熔伤害加成", "导电伤害加成",
            "气动伤害加成", "衍射伤害加成", "湮灭伤害加成",
        ])
        chg.addWidget(self.change_target)
        chg.addStretch()
        self.change_opts.setVisible(False)
        layout.addWidget(self.change_opts)

        self.task_combo.currentTextChanged.connect(
            lambda t: self._on_task_changed(t))
        self._on_task_changed(self.task_combo.currentText())

        # ── 第3行: 启停按钮 ──
        row3 = QHBoxLayout()

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setMinimumWidth(100)
        self.start_btn.setStyleSheet("QPushButton { font-weight: bold; font-size: 14px; }")
        self.start_btn.clicked.connect(self._start)
        row3.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row3.addWidget(self.stop_btn)

        row3.addStretch()
        # 状态
        self.success_label = QLabel("成功: 0")
        self.fail_label = QLabel("失败: 0")
        self.score_label = QLabel("得分: -")
        for lbl in [self.success_label, self.fail_label, self.score_label]:
            lbl.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 8px;")
            row3.addWidget(lbl)

        layout.addLayout(row3)

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

    def _on_task_changed(self, task_name):
        is_enhance = "强化" in task_name
        self.strategy_combo.setVisible(is_enhance)
        self.traditional_opts.setVisible(is_enhance and self.strategy_combo.currentText() == "传统")
        self.change_opts.setVisible(not is_enhance)

    # ── 设置持久化 ──
    def _load_settings(self):
        idx = self.task_combo.findText(self._settings.value("task", "批量强化声骸"))
        if idx >= 0:
            self.task_combo.setCurrentIndex(idx)
        idx = self.strategy_combo.findText(self._settings.value("strategy", "渐进式"))
        if idx >= 0:
            self.strategy_combo.setCurrentIndex(idx)

    def _save_settings(self):
        self._settings.setValue("task", self.task_combo.currentText())
        self._settings.setValue("strategy", self.strategy_combo.currentText())

    # ── 套装 ──
    def _load_sets(self):
        path = os.path.join("assets", "echo_set_templates.json")
        current = self.set_combo.currentText()
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
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

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
        self._save_settings()
        task = self._get_task()
        if task is None:
            self._append_log("[ERROR] 任务未就绪")
            return
        if self._running:
            return

        task.config['强化策略'] = self.strategy_combo.currentText()
        task.config['当前套装'] = self.set_combo.currentText()

        # 修改主属性模式
        if "修改" in self.task_combo.currentText():
            task.config['目标属性'] = self.change_target.currentText()

        if self.strategy_combo.currentText() == '传统':
            task.config['必须有双爆'] = self.opt_double_crit.isChecked()
            task.config['双爆出现之前必须全有效词条'] = self.opt_all_valid_before_crit.isChecked()
            task.config['第一条必须为有效词条'] = self.opt_first_must_valid.isChecked()
            task.config['首条双爆>='] = float(self.opt_first_crit.currentText())
            task.config['双爆总计>='] = float(self.opt_total_crit.currentText())
            task.config['有效词条>='] = int(self.opt_valid_count.currentText())
            task.config['启用评分模式'] = self.opt_score_enable.isChecked()
            task.config['最低得分>='] = float(self.opt_score_min.currentText())

        task.config['成功后暂停'] = self.opt_pause.isChecked()

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._append_log("══════════ 开始 ══════════")
        self._append_log(f"任务: {self.task_combo.currentText()}  策略: {task.config['强化策略']}  套装: {task.config['当前套装']}")

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
            self._append_log("══════════ 结束 ══════════")

    def _get_task(self):
        if self._task is not None:
            return self._task
        try:
            module_name = "EnhanceEchoTask" if "强化" in self.task_combo.currentText() else "ChangeEchoTask"
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            from src.task.ChangeEchoTask import ChangeEchoTask
            cls = EnhanceEchoTask if module_name == "EnhanceEchoTask" else ChangeEchoTask
            self._task = og.executor.get_task_by_class(cls)
            return self._task
        except Exception:
            return None
