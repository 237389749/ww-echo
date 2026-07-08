"""
运行面板 — 任务/策略/套装选择, 启停, 状态, 日志。
"""
import json
import os
import threading

from PySide6.QtCore import QTimer, QSettings
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QLabel, QFrame,
                               QCheckBox)

from ok import og


class RunTab(QWidget):
    def __init__(self, ok_engine, log_bridge, log_area, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self.log_area = log_area
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
        row1.addWidget(QLabel("模式:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(["强化声骸", "评估声骸"])
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

        # 传统评分选项 (先创建, 后面放进 traditional_opts)
        self.opt_score_enable = QCheckBox("启用评分模式")
        self.opt_score_min = QComboBox()
        self.opt_score_min.setMinimumWidth(60)
        for v in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
            self.opt_score_min.addItem(str(v))
        self.opt_score_min.setCurrentText("3.0")

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
        trad.addWidget(self.opt_score_enable)
        trad.addWidget(QLabel("最低得分≥"))
        trad.addWidget(self.opt_score_min)
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
        self.strategy_combo.currentTextChanged.connect(
            lambda s: self._update_strategy_info(s))

        # 策略说明
        self.strategy_info = QLabel()
        self.strategy_info.setWordWrap(True)
        self.strategy_info.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        layout.addWidget(self.strategy_info)

        # 评估说明 (选评估时可见)
        self.strategy_info_eval = QLabel(
            "评估模式 — 只读遍历背包声骸, 不做任何修改\n\n"
            "输出: 每个声骸输出一行到「调试工具→运行日志」\n"
            "格式: [评估#N] X/5词条 | 得分=X.XX | ⏳/✅/❌\n"
            "不截图, 不强化, 不上锁, 不丢弃 — 纯打分\n\n"
            "针对当前套装: 使用选中套装的权重配置评估\n"
            "阈值: 0词条→跳过 | 1条≥1.0 | 2-3条≥2.0 | 4条≥2.5 | 5条≥3.0\n"
            "⏳待强化=当前通过但未满级, ✅达标=满级通过, ❌=不达标"
        )
        self.strategy_info_eval.setWordWrap(True)
        self.strategy_info_eval.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        self.strategy_info_eval.setVisible(False)
        layout.addWidget(self.strategy_info_eval)

        # 评分说明 (始终可见)
        self.score_info = QLabel(
            "评分: 档位值÷均值×权重. 权重默认: 暴击2.0 爆伤1.5 攻击%1.0 攻击0.5 共效1.0\n"
            "暴击最低6.3%×2.0→1.50, 最高10.5%×2.0→2.50\n"
            "小攻击/小生命/小防御权重0.5≈废物词条. 套装专属词条(共解/共技等)权重2.0\n"
            "强化阈值: 1条≥1.0 / 3条≥2.0 / 4条≥2.5 / 5条≥3.0"
        )
        self.score_info.setWordWrap(True)
        self.score_info.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        layout.addWidget(self.score_info)

        self._update_strategy_info(self.strategy_combo.currentText())

        # 通用选项
        row_gen = QHBoxLayout()
        self.opt_pause = QCheckBox("成功后暂停")
        self.opt_pause.setChecked(True)
        row_gen.addWidget(self.opt_pause)
        row_gen.addStretch()
        layout.addLayout(row_gen)


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

        hint = QLabel('运行日志 → 见「调试工具」tab')
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addStretch()

    def _update_strategy_info(self, strategy):
        if strategy == "渐进式":
            self.strategy_info.setText(
                "渐进式: 每级单独评估, 不达标即停丢\n"
                "Lv5 首条 → 得分 ≥ 1.0 (必须是有分量的词条)\n"
                "Lv10    → 不做判断, 继续\n"
                "Lv15    → 累积得分 ≥ 2.0\n"
                "Lv20    → 累积得分 ≥ 2.5\n"
                "Lv25    → 累积得分 ≥ 3.0, 达标上锁\n"
                "未满级声骸: 已有词条先做渐进判断, 通过则继续强化"
            )
        else:
            self.strategy_info.setText(
                "传统: 拉满到Lv25后一次性判断\n"
                "判断条件: 必须有双爆 / 首条双爆≥阈值 / 双爆总计≥阈值\n"
                "有效词条≥设定数量 / 第一条必须有效\n"
                "未满级声骸: 继续强化至满级再判断"
            )

    def _on_task_changed(self, task_name):
        is_enhance = "强化" in task_name
        self.strategy_combo.setVisible(is_enhance)
        self.strategy_info.setVisible(is_enhance)
        self.traditional_opts.setVisible(is_enhance and self.strategy_combo.currentText() == "传统")
        if not is_enhance:
            self.strategy_info_eval.setVisible(True)
        else:
            self.strategy_info_eval.setVisible(False)

    # ── 设置持久化 ──
    def _load_settings(self):
        idx = self.task_combo.findText(self._settings.value("task", "强化声骸"))
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

        is_eval = "评估" in self.task_combo.currentText()
        task.config['强化策略'] = self.strategy_combo.currentText()
        task.config['当前套装'] = self.set_combo.currentText()

        if is_eval:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._append_log("══════════ 开始评估 ══════════")
            self._append_log(f"套装: {task.config.get('当前套装')}  仅打分, 不修改声骸")

            def _run_eval():
                try:
                    task.evaluate_only()
                except Exception as e:
                    self._append_log(f"[ERROR] {e}")
                finally:
                    self._running = False
                    self.start_btn.setEnabled(True)
                    self.stop_btn.setEnabled(False)
                    self._append_log("══════════ 评估结束 ══════════")

            self._thread = threading.Thread(target=_run_eval, daemon=True)
            self._thread.start()
            return

        if not is_eval and self.strategy_combo.currentText() == '传统':
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
        self._append_log("══════════ 开始强化 ══════════")
        self._append_log(f"策略: {task.config['强化策略']}  套装: {task.config['当前套装']}")

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
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            self._task = og.executor.get_task_by_class(EnhanceEchoTask)
            return self._task
        except Exception:
            return None
