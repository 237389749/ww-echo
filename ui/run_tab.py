"""
运行面板 — 任务/策略/套装选择, 启停, 状态, 日志。

布局(2026-10 重构): 顶部**状态卡**(当前任务 + 大主按钮 + 进度 + 计数/耗时) → 任务卡组(模式/策略/套装/传统选项/暂停)
→ 可折叠的「规则与评分说明」→ 上次评估摘要 → **日志卡**(级别过滤/自动滚动/复制/清空/导出)。
"""
import html
import os
import threading
import time

from PySide6.QtCore import QTimer, QSettings, Signal, QObject, Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, CheckBox, ComboBox, FluentIcon as FIF,
                            HeaderCardWidget, IndeterminateProgressBar, InfoBar, InfoBarPosition,
                            PrimaryPushButton, PushButton, SettingCard, SettingCardGroup,
                            StrongBodyLabel, SubtitleLabel, SwitchButton, ToolTipFilter)

from ok import og

from src.echo_stats import DEFAULT_WEIGHTS
from src.echo_set_templates import get_set_weights


class RunTab(QWidget):
    _log_signal = Signal(str)
    _eval_done_signal = Signal(str, str)  # json_path, ss_dir
    _eval_error_signal = Signal(str)
    _task_done_signal = Signal(str)  # message

    LOG_LEVELS = ("全部", "信息", "警告", "错误")     # 日志级别过滤下拉
    _LEVEL_COLOR = {"ERROR": "#c62828", "WARNING": "#b06000", "INFO": None}

    def __init__(self, ok_engine, log_bridge, log_area, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self.log_area = log_area
        self._task = None
        self._running = False
        self._thread = None
        self._settings = QSettings("OK-Echo", "RunTab")
        # 日志级别过滤要拿原文重渲染, 所以自己留一份缓冲(上限防内存膨胀)
        self._log_lines: list[tuple[str, str]] = []
        self._log_filter = "全部"
        self._run_since: float | None = None

        self._setup_ui()
        self._load_settings()

        log_bridge.log_signal.connect(self._append_log)

        # 线程安全信号
        self._log_signal.connect(self._append_log)
        self._eval_done_signal.connect(self._on_eval_done_ui)
        self._eval_error_signal.connect(self._on_eval_error_ui)
        self._task_done_signal.connect(self._on_task_done_ui)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

    # ══════════════════ 界面 ══════════════════
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)
        # 构建顺序有讲究: 「规则」框必须在「任务卡组」之前 —— 任务卡组末尾会调 _on_task_changed,
        # 那里要 setVisible(self.strategy_info); 而规则框的初始文案要读 strategy_combo,
        # 所以把"填文案"这一步延后到两者都建好之后。
        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_rules_box())
        layout.addWidget(self._build_task_group())
        layout.addWidget(self._build_eval_card())
        layout.addWidget(self._build_log_card(), 1)
        self._update_strategy_info(self.strategy_combo.currentText())
        self._update_status_text()

    @staticmethod
    def _cap(text: str) -> CaptionLabel:
        lbl = CaptionLabel()
        lbl.setText(text)
        return lbl

    @staticmethod
    def _add_card_widget(card: SettingCard, widget: QWidget):
        # Gallery 的标准写法: 控件追加到 hBoxLayout 末尾(即右侧) + 补 16px 边距
        card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
        card.hBoxLayout.addSpacing(16)

    @staticmethod
    def _card_body(card: HeaderCardWidget) -> QVBoxLayout:
        """HeaderCardWidget 的 viewLayout 是**横向**的(库源码: QHBoxLayout(self.view)), 正文要自己套一层纵向。"""
        body = QWidget()
        vb = QVBoxLayout(body)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(10)
        card.viewLayout.addWidget(body)
        return vb

    def _build_status_card(self) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle("运行")
        self.status_task = SubtitleLabel()
        self.status_state = CaptionLabel()
        body = self._card_body(card)
        body.addWidget(self.status_task)
        body.addWidget(self.status_state)

        row = QHBoxLayout()
        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = PushButton(FIF.PAUSE, "停止")
        self.stop_btn.setMinimumWidth(110)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addStretch()
        self.elapsed_label = CaptionLabel()
        row.addWidget(self.elapsed_label)
        body.addLayout(row)

        self.progress = IndeterminateProgressBar()
        self.progress.setVisible(False)
        body.addWidget(self.progress)

        counts = QHBoxLayout()
        self.success_label = StrongBodyLabel()
        self.fail_label = StrongBodyLabel()
        self.score_label = StrongBodyLabel()
        self.success_label.setText("成功: 0")
        self.fail_label.setText("失败: 0")
        self.score_label.setText("得分: -")
        for lbl in (self.success_label, self.fail_label, self.score_label):
            counts.addWidget(lbl)
            counts.addSpacing(18)
        counts.addStretch()
        body.addLayout(counts)
        return card

    def _build_task_group(self) -> SettingCardGroup:
        g = SettingCardGroup("任务与策略", self)

        self.task_card = SettingCard(
            FIF.ROBOT, "模式", "强化: 强化到满级并按规则丢弃/上锁; 评估: 只读遍历, 打分并生成 HTML 报告", self)
        self.task_combo = ComboBox()
        self.task_combo.addItems(["强化声骸", "评估声骸"])
        self._add_card_widget(self.task_card, self.task_combo)

        self.strategy_card = SettingCard(
            FIF.SPEED_HIGH, "策略", "渐进式: 每级单独评估, 不达标立即止损; 传统: 拉满后一次性判断", self)
        self.strategy_combo = ComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        self._add_card_widget(self.strategy_card, self.strategy_combo)

        self.set_label = SettingCard(
            FIF.LIBRARY, "套装", "强化按该套装权重与 A/B 两条线判定; 评估忽略此项(按面板图标/声骸名自动映射)", self)
        self.set_combo = ComboBox()
        self.set_combo.setMinimumWidth(150)
        self._load_sets()
        self._add_card_widget(self.set_label, self.set_combo)

        # ── 传统模式选项(整块塞进卡片右侧; 仅「传统」策略可见) ──
        self.opt_score_enable = CheckBox("启用评分模式")
        self.opt_score_min = ComboBox()
        self.opt_score_min.setMinimumWidth(60)
        for v in [24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48]:
            self.opt_score_min.addItem(str(v))
        self.opt_score_min.setCurrentText("32")

        self.traditional_opts = QWidget()
        trad = QHBoxLayout(self.traditional_opts)
        trad.setContentsMargins(0, 0, 0, 0)
        trad.setSpacing(10)
        self.opt_double_crit = CheckBox("必须有双爆")
        self.opt_double_crit.setChecked(True)
        self.opt_all_valid_before_crit = CheckBox("双爆前全有效")
        self.opt_all_valid_before_crit.setChecked(True)
        self.opt_first_must_valid = CheckBox("首条必须有效")
        self.opt_first_must_valid.setChecked(True)
        for w in (self.opt_double_crit, self.opt_all_valid_before_crit, self.opt_first_must_valid):
            trad.addWidget(w)
        trad.addSpacing(6)
        trad.addWidget(self.opt_score_enable)
        trad.addWidget(self._cap("最低得分≥"))
        trad.addWidget(self.opt_score_min)

        self.opt_first_crit = ComboBox()
        self.opt_first_crit.setMinimumWidth(60)
        self.opt_first_crit.addItems([str(x) for x in [6.3, 6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5]])
        self.opt_first_crit.setCurrentText("6.9")
        trad.addWidget(self._cap("首条双爆≥"))
        trad.addWidget(self.opt_first_crit)

        self.opt_total_crit = ComboBox()
        self.opt_total_crit.setMinimumWidth(60)
        self.opt_total_crit.addItems([str(x) for x in [6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5,
                                                       12.0, 13.8, 15.0, 16.5, 18.0]])
        self.opt_total_crit.setCurrentText("13.8")
        trad.addWidget(self._cap("双爆总计≥"))
        trad.addWidget(self.opt_total_crit)

        self.opt_valid_count = ComboBox()
        self.opt_valid_count.setMinimumWidth(50)
        self.opt_valid_count.addItems(["1", "2", "3", "4", "5"])
        self.opt_valid_count.setCurrentText("3")
        trad.addWidget(self._cap("有效词条≥"))
        trad.addWidget(self.opt_valid_count)
        trad.addStretch()

        self.traditional_card = SettingCard(FIF.TILES, "传统模式选项", "仅在「传统」策略下生效", self)
        self.traditional_card.hBoxLayout.addWidget(self.traditional_opts, 0, Qt.AlignRight)
        self.traditional_card.hBoxLayout.addSpacing(16)
        self.traditional_card.setVisible(False)

        self.pause_card = SettingCard(FIF.PAUSE, "成功后暂停", "一轮任务结束后暂停, 便于查看结果与报告", self)
        self.opt_pause = SwitchButton()
        self.opt_pause.setChecked(True)
        self._add_card_widget(self.pause_card, self.opt_pause)

        g.addSettingCards([self.task_card, self.strategy_card, self.set_label,
                           self.traditional_card, self.pause_card])
        self.strategy_combo.currentTextChanged.connect(self._on_strategy_changed)
        self.task_combo.currentTextChanged.connect(self._on_task_changed)
        self._on_task_changed(self.task_combo.currentText())
        return g

    def _on_strategy_changed(self, strategy: str):
        self.traditional_card.setVisible(strategy == "传统" and "强化" in self.task_combo.currentText())
        self._update_strategy_info(strategy)
        self._update_status_text()

    def _build_rules_box(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.rules_toggle = PushButton(FIF.INFO, "规则与评分说明")
        self.rules_toggle.clicked.connect(self._toggle_rules)
        v.addWidget(self.rules_toggle)

        self.rules_box = QWidget()
        rb = QVBoxLayout(self.rules_box)
        rb.setContentsMargins(2, 0, 2, 0)
        rb.setSpacing(6)
        self.strategy_info = CaptionLabel()
        self.strategy_info.setWordWrap(True)
        self.strategy_info_eval = CaptionLabel()
        self.strategy_info_eval.setWordWrap(True)
        self.strategy_info_eval.setText(
            "评估模式 — 只读遍历背包, 截图+打分, 生成 HTML 报告\n\n"
            "评估按详情面板的套装图标识别套装(低置信回退声骸名候选), 都拿不到则用通用权重\n\n"
            "完成后弹出保存框 → 生成 eval_report.html + 截图文件夹\n"
            "报告: 截图+名称+套装+COST/主属性+得分(完成度%)+判定+词条明细(按档位着色), 可按得分/判定/名称/套装筛选与排序\n"
            "不强化/不上锁/不丢弃 — 纯评估\n\n"
            "两条线: 达标线 A = 10×本只出现有效词条权重和 | 基准线 B(通用) = 6.5/11.5/17.5\n"
            "满级: A≥B 且 总分≥A → 达标; 总分≥B → 保留; 锁N刷M 达标概率≥60% → 建议重铸; 否则 不合格\n"
            "未满级: 总分≥B(满级) 或 (前瞻概率≥60% 且 总分≥A) → 建议强化; 否则 不建议强化")
        self.score_info = CaptionLabel()
        self.score_info.setWordWrap(True)
        self.score_info.setText(
            "评分: 条分 = 档位值÷期望值 ×10×权重(期望 = 官方公示概率期望; 平均档 = 10 分, 满档 ≈ 13.1~14.0)\n"
            "通用权重: 暴击1.0 爆伤0.7 攻击%/生命%/防御% 0.5 共效0.6 专伤0.4 小攻/小生命/小防御 0.25\n"
            "暴击6.3%→8.40分, 10.5%→14.00分; 套装模式权重由套装模板决定, 无效词条=0分\n"
            "判定: 达标线 A = 10×本只出现有效词条的权重和; 基准线 B = 套装有效键最低 tier-1 条之和 ×10\n"
            "满级: A≥B 且 总分≥A → 达标; 总分≥B → 保留; 未过线但「锁 N 刷 M 后达标概率≥60%」→ 建议重铸; Lv5/10 有首核即过")
        for w in (self.strategy_info, self.strategy_info_eval, self.score_info):
            rb.addWidget(w)
        self.rules_box.setVisible(False)
        v.addWidget(self.rules_box)
        return wrap

    def _toggle_rules(self):
        show = not self.rules_box.isVisible()
        self.rules_box.setVisible(show)
        self.rules_toggle.setText("规则与评分说明（收起）" if show else "规则与评分说明")

    def _build_eval_card(self) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle("上次评估结果")
        self.sum_verdicts = StrongBodyLabel()
        self.sum_verdicts.setText("—")
        self.sum_avg = CaptionLabel()
        self.sum_avg.setText("跑一次「评估声骸」后, 这里显示判定分布与平均完成度")
        body = self._card_body(card)
        body.addWidget(self.sum_verdicts)
        body.addWidget(self.sum_avg)
        card.setVisible(False)
        self.eval_card = card
        return card

    def _build_log_card(self) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle("运行日志")
        bar = QHBoxLayout()
        bar.addWidget(self._cap("级别"))
        self.log_level_combo = ComboBox()
        self.log_level_combo.addItems(list(self.LOG_LEVELS))
        self.log_level_combo.setMinimumWidth(90)
        self.log_level_combo.currentTextChanged.connect(self._on_log_filter)
        bar.addWidget(self.log_level_combo)
        bar.addSpacing(10)
        self.log_autoscroll = SwitchButton()
        self.log_autoscroll.setChecked(True)
        self.log_autoscroll.setOnText("自动滚动")
        self.log_autoscroll.setOffText("手动滚动")
        bar.addWidget(self.log_autoscroll)
        bar.addStretch()
        for icon, text, slot in ((FIF.COPY, "复制", self._copy_log),
                                 (FIF.DELETE, "清空", self._clear_log),
                                 (FIF.SAVE, "导出", self._export_log)):
            btn = PushButton(icon, text)
            btn.clicked.connect(slot)
            btn.installEventFilter(ToolTipFilter(btn, 400))
            bar.addWidget(btn)
            bar.addSpacing(6)
        body = self._card_body(card)
        body.addLayout(bar)
        body.addWidget(self.log_area, 1)
        return card

    def _update_status_text(self):
        mode = self.task_combo.currentText()
        if "强化" in mode:
            mode += f" · {self.strategy_combo.currentText()} · {self.set_combo.currentText()}"
        self.status_task.setText(mode)
        if not self._running:
            self.status_state.setText("空闲 — 选好模式与策略后点「开始」")
            self.elapsed_label.setText("耗时 —")

    def _update_strategy_info(self, strategy):
        if strategy == "渐进式":
            self.strategy_info.setText(
                "渐进式: 每级单独评估, 不达标即停丢\n"
                "Lv5  第1条 → 有首核词条即过(不限分)\n"
                "Lv10 第2条 → 有首核词条即过(不限分)\n"
                "Lv15 第3条 / Lv20 第4条 → 总分 ≥ 基准线 B(通用 6.5/11.5); 或 前瞻概率≥60% 且 总分 ≥ 达标线 A\n"
                "Lv25 第5条 → A≥B 且 总分≥A → 达标上锁; 不达标则丢弃\n"
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
        self.strategy_card.setVisible(is_enhance)
        self.strategy_info.setVisible(is_enhance)
        self.traditional_card.setVisible(is_enhance and self.strategy_combo.currentText() == "传统")
        # 套装语境只对强化有意义(评估=通用权重; 声骸个体与套装无自动映射) —— 隐藏整张卡而不是只藏控件
        self.set_label.setVisible(is_enhance)
        self.set_combo.setVisible(is_enhance)
        if not is_enhance:
            self.strategy_info_eval.setVisible(True)
        else:
            self.strategy_info_eval.setVisible(False)
        self._update_status_text()

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
        # 套装名单走模板模块(带校验与缓存的唯一来源), 不再自己 json.load 一份
        from src.echo_set_templates import get_all_set_names
        current = self.set_combo.currentText()
        names = get_all_set_names()
        self.set_combo.clear()
        self.set_combo.addItem("通用")
        self.set_combo.addItems(names)
        if current in names:
            self.set_combo.setCurrentText(current)

    def _append_log(self, text):
        """写日志: 判定级别 → 入缓冲(供级别过滤重渲染) → 过筛则追加, 并按需自动滚到底。"""
        level = ("ERROR" if ("ERROR" in text or "Traceback" in text)
                 else "WARNING" if ("WARN" in text or "⚠" in text) else "INFO")
        self._log_lines.append((level, text))
        if len(self._log_lines) > 3000:      # 上限防内存膨胀: 丢最旧的 1/3
            del self._log_lines[:1000]
        if self._passes_filter(level):
            self._render_line(level, text)

    def _passes_filter(self, level: str) -> bool:
        f = self._log_filter
        return (f == "全部"
                or (f == "信息" and level == "INFO")
                or (f == "警告" and level == "WARNING")
                or (f == "错误" and level == "ERROR"))

    def _render_line(self, level: str, text: str):
        color = self._LEVEL_COLOR.get(level)
        self.log_area.append(f'<span style="color:{color}">{html.escape(text)}</span>' if color else text)
        if self.log_autoscroll.isChecked():
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_log_filter(self, level: str):
        self._log_filter = level
        self.log_area.clear()
        for lv, text in self._log_lines[-1500:]:
            if self._passes_filter(lv):
                self._render_line(lv, text)

    def _copy_log(self):
        QGuiApplication.clipboard().setText(self.log_area.toPlainText())
        InfoBar.success("已复制", "日志内容已复制到剪贴板", duration=1500,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _clear_log(self):
        self._log_lines.clear()
        self.log_area.clear()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出运行日志", "ww-echo.log", "日志 (*.log);;文本 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(t for _, t in self._log_lines))
            InfoBar.success("已导出", path, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)
        except OSError as e:
            InfoBar.error("导出失败", str(e), duration=4000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _refresh_status(self):
        self._refresh_run_state()
        task = self._get_task()
        if task is None:
            return
        try:
            self.success_label.setText(f"成功: {task.info_get('成功声骸数量') or 0}")
            self.fail_label.setText(f"失败: {task.info_get('失败声骸数量') or 0}")
            score = task.info_get('声骸得分')
            self.score_label.setText(f"得分: {score}" if score is not None else "得分: -")
            eval_count = task.info_get('评估数量')
            if eval_count:
                self.score_label.setText(f"评估: {eval_count}个")
        except Exception:
            pass

    def _refresh_run_state(self):
        """运行态 → 状态卡(进度条/耗时/文案)。放在 _refresh_status 最前面: 任务未就绪时也要更新。"""
        if self._running:
            if self._run_since is None:
                self._run_since = time.monotonic()
                self.progress.setVisible(True)
                self.progress.start()
            self.status_state.setText("运行中…")
            self.elapsed_label.setText(f"耗时 {self._fmt_elapsed(time.monotonic() - self._run_since)}")
        elif self._run_since is not None:
            self.progress.stop()
            self.progress.setVisible(False)
            self.status_state.setText(f"已结束 · 本轮 {self._fmt_elapsed(time.monotonic() - self._run_since)}")
            self.elapsed_label.setText("耗时 —")
            self._run_since = None

    @staticmethod
    def _fmt_elapsed(sec: float) -> str:
        sec = int(max(0.0, sec))
        return f"{sec} 秒" if sec < 60 else f"{sec // 60} 分 {sec % 60} 秒"

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
        # 评估按声骸名自动映射套装(见 evaluate_only); 这里置"通用"仅作映射失败时的兜底
        task.config['当前套装'] = '通用' if is_eval else self.set_combo.currentText()

        if is_eval:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._append_log("══════════ 开始评估 ══════════")
            self._append_log("评估按声骸名自动映射套装权重, 仅打分, 不修改声骸")

            def _on_eval_done(json_path, ss_dir):
                self._eval_done_signal.emit(json_path, ss_dir)

            def _run_eval():
                try:
                    # [ww-echo cloud patch] 评估也把游戏窗口切到前台再跑
                    hwnd_window = getattr(og.device_manager, 'hwnd_window', None)
                    if hwnd_window is not None and hwnd_window.hwnd:
                        hwnd_window.bring_to_front()
                    task.evaluate_only(on_done=_on_eval_done)
                except Exception as e:
                    self._eval_error_signal.emit(str(e))

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
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                self._append_log("⚠ 任务线程仍在运行, 将在后台自行结束")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log("══════════ 已停止 ══════════")

    def _run_task(self, task):
        try:
            og.app.start_controller.start(task)
        except Exception as e:
            self._task_done_signal.emit(f"[ERROR] {e}")
        else:
            self._task_done_signal.emit("══════════ 结束 ══════════")

    def _on_task_done_ui(self, msg):
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log(msg)

    def _on_eval_done_ui(self, json_path, ss_dir):
        """在主线程中处理评估完成后的 UI 操作。"""
        import json as _json, shutil
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        save_path, _ = QFileDialog.getSaveFileName(
            None, "保存评估报告", "eval_report.html",
            "HTML (*.html)"
        )
        if not save_path:
            shutil.rmtree(os.path.dirname(json_path), ignore_errors=True)
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 评估结束 (已取消) ══════════")
            return

        try:
            dest_dir = os.path.dirname(save_path)
            ss_dest = os.path.join(dest_dir, "eval_screenshots")
            if os.path.exists(ss_dest):
                shutil.rmtree(ss_dest)
            if os.path.exists(ss_dir):
                shutil.copytree(ss_dir, ss_dest)

            with open(json_path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            self._update_eval_summary(data)
            html = _build_eval_html(data)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            # 顺手把评估数据(JSON)存到报告同目录 —— 临时目录随后会被删, 而「组合穷举」页/tools/echo_plan.py
            # 需要这份 JSON 当**库存**(含 名字/套装/COST/主属性/词条)才能穷举; HTML 只供人看。
            json_dest = os.path.join(dest_dir, os.path.splitext(os.path.basename(save_path))[0] + ".json")
            with open(json_dest, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            self._append_log(f"评估数据已存: {json_dest}(「组合穷举」页可直接导入它当库存)")

            if QMessageBox.question(None, "完成",
                                    f"报告已保存:\n{save_path}\n数据已保存:\n{json_dest}\n\n打开查看?"
                                    ) == QMessageBox.Yes:
                os.startfile(save_path)
        except Exception as e:
            self._append_log(f"[ERROR] 保存失败: {e}")
        finally:
            shutil.rmtree(os.path.dirname(json_path), ignore_errors=True)
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 评估结束 ══════════")

    def _update_eval_summary(self, data: dict):
        """报告数据 → 「上次评估结果」卡: 判定分布 + 平均完成度(同套装内跨件可比)。"""
        results = data.get("results") or []
        if not results:
            return
        names = {"pass": "达标", "hold": "保留", "keep": "建议重铸",
                 "pending": "建议强化", "fail": "不合格", "zero": "0级"}
        counts: dict = {}
        for r in results:
            counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
        parts = [f"{names.get(k, k)} {counts[k]}" for k in
                 ("pass", "hold", "keep", "pending", "fail", "zero") if counts.get(k)]
        self.sum_verdicts.setText(f"{len(results)} 只 · " + " · ".join(parts))
        try:
            from src.echo_score_sim import completeness
            comps = [c for c in (completeness(r.get("set"), r.get("score", 0)) for r in results)
                     if c is not None]
            if comps:
                self.sum_avg.setText(
                    f"平均完成度 {sum(comps) / len(comps):.1f}% （完成度 = 得分 ÷ 该套装 Top-5 全满档分, 同套装内可比）")
        except Exception:
            pass
        self.eval_card.setVisible(True)

    def _on_eval_error_ui(self, error_msg):
        self._append_log(f"[ERROR] {error_msg}")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _get_task(self):
        if self._task is not None:
            return self._task
        try:
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            self._task = og.executor.get_task_by_class(EnhanceEchoTask)
            return self._task
        except Exception:
            return None


# 判定档位的中文名与配色。**权威文案来自判定层** —— JSON 记录里的 `verdict_cn`(judge_echo 产出);
# 这两张表只在旧报告缺 `verdict_cn` 字段时兜底。曾用它在渲染时**覆盖**记录里的文案,
# 导致阶段二十三的「建议强化 / 不建议强化」在报告里根本显示不出来(审阅 A 类问题)。
VERDICT_CN = {"pass": "达标", "hold": "保留", "keep": "建议重铸",
              "pending": "建议强化", "fail": "不建议强化", "zero": "0级/无词条"}
VERDICT_COLOR = {"pass": "#4caf50", "hold": "#009688", "keep": "#2196f3",
                 "pending": "#ff9800", "fail": "#f44336", "zero": "#9e9e9e"}

# 评估报告样式: 词条按档位(档位/均值)着色, 筛选区样式
_EVAL_CSS = """
body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#f5f5f5}
.card{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.summary{display:flex;gap:24px;font-size:16px;flex-wrap:wrap}
.summary span{padding:4px 12px;border-radius:4px}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:8px 12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
th{background:#fafafa;font-weight:bold;position:sticky;top:0}
img{border-radius:4px;border:1px solid #ddd}
.stat{margin:2px 0;padding:1px 5px;border-radius:3px;border:1px solid rgba(0,0,0,0.06)}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px;background:#fafafa;padding:10px;border-radius:6px}
.filters input[type=number]{padding:2px 4px;border:1px solid #ddd;border-radius:3px}
.sep{color:#ccc}
.cnt{margin-left:auto;color:#666}
button{padding:4px 10px;cursor:pointer;border:1px solid #ddd;border-radius:3px;background:#fff}
details.rules summary{cursor:pointer;font-weight:bold;font-size:15px}
.rules-body{font-size:13px;line-height:1.75;margin-top:10px;color:#333}
.rules-body h3{margin:12px 0 4px;font-size:14px;color:#1565c0}
.rules-body ul{margin:4px 0 4px 20px}
.rules-body code{background:#f5f5f5;padding:1px 4px;border-radius:3px}
.wtable{width:auto;margin-top:6px}
.wtable th,.wtable td{padding:4px 10px}
.w{display:inline-block;margin:2px 4px 2px 0;padding:1px 6px;border-radius:3px;background:#e3f2fd;color:#1565c0}
"""

# 评估报告筛选脚本(原生 JS, 无外部依赖): 得分区间 + 判定多选 + 名称包含
_EVAL_JS = """
function applyFilter(){
  var min=parseFloat(document.getElementById('fmin').value);
  var max=parseFloat(document.getElementById('fmax').value);
  var nm=document.getElementById('fname').value.trim();
  var st=document.getElementById('fset').value;
  var vs=Array.prototype.slice.call(document.querySelectorAll('.fv'))
            .filter(function(c){return c.checked}).map(function(c){return c.value});
  var shown=0;
  document.querySelectorAll('#tbody tr').forEach(function(tr){
    var s=parseFloat(tr.getAttribute('data-score'));
    var v=tr.getAttribute('data-verdict');
    var n=tr.getAttribute('data-name')||'';
    var ok=true;
    if(!isNaN(min)&&!(s>=min)) ok=false;
    if(!isNaN(max)&&!(s<=max)) ok=false;
    if(vs.length&&vs.indexOf(v)<0) ok=false;
    if(nm&&n.indexOf(nm)<0) ok=false;
    if(st&&(tr.getAttribute('data-set')||'')!==st) ok=false;
    tr.style.display=ok?'':'none';
    if(ok) shown++;
  });
  document.getElementById('cnt').textContent='显示 '+shown+' / '+TOTAL;
}
['fmin','fmax','fname'].forEach(function(id){
  document.getElementById(id).addEventListener('input',applyFilter)});
document.getElementById('fset').addEventListener('change',applyFilter);
document.querySelectorAll('.fv').forEach(function(c){
  c.addEventListener('change',applyFilter)});
document.getElementById('fclear').addEventListener('click',function(){
  document.getElementById('fmin').value='';
  document.getElementById('fmax').value='';
  document.getElementById('fname').value='';
  document.getElementById('fset').value='';
  document.getElementById('fsort').value='orig';
  document.querySelectorAll('.fv').forEach(function(c){c.checked=true});
  applySort();
  applyFilter();
});
// 按"完成度"排序(报告主指标): 同套装内跨件可比 —— 用 data-comp, 缺值(未评估/无套装)排最后
var _origOrder=null;
function applySort(){
  var tb=document.getElementById('tbody');
  var rows=Array.prototype.slice.call(tb.querySelectorAll('tr'));
  if(_origOrder===null) _origOrder=rows.slice();          // 首次记录生成时的原始顺序
  var mode=document.getElementById('fsort').value;
  var arr = (mode==='orig') ? _origOrder.slice() : rows.slice();
  if(mode!=='orig'){
    arr.sort(function(a,b){
      var x=parseFloat(a.getAttribute('data-comp')), y=parseFloat(b.getAttribute('data-comp'));
      if(isNaN(x)) x=-1;
      if(isNaN(y)) y=-1;
      return (mode==='comp_desc') ? (y-x) : (x-y);
    });
  }
  arr.forEach(function(tr){ tb.appendChild(tr); });        // appendChild 移动节点 = 排序
}
document.getElementById('fsort').addEventListener('change',applySort);
applyFilter();
"""


def _ratio_color(ratio):
    """词条档位着色: 单色相(蓝 hue=210)连续渐变, 深=高档、浅=低档。
    ratio=档位值/均值(约 0.65~1.35), 映射 lightness 92%(浅)→46%(深)。"""
    t = (ratio - 0.65) / 0.7
    t = max(0.0, min(1.0, t))
    lightness = 92 - 46 * t
    return f'hsl(210, 60%, {lightness:.0f}%)'


def _build_rules_html(results):
    """评估规则说明(折叠卡片) + 本次报告涉及套装的权重表 —— 让报告自带"分数/判定怎么来的"。"""
    used = {}
    for r in results:
        name = r.get("set") or "通用"
        if name not in used:
            used[name] = dict(DEFAULT_WEIGHTS) if name == "通用" else dict(get_set_weights(name) or {})
    rows = []
    for name in sorted(used, key=lambda n: (n != "通用", n)):
        weights = used[name]
        if not weights:
            continue
        items = "".join(f'<span class="w">{k} {v}</span>'
                        for k, v in sorted(weights.items(), key=lambda kv: -kv[1]))
        rows.append(f'<tr><td>{name}</td><td>{items}</td></tr>')
    weights_html = ('<table class="wtable"><thead><tr><th>套装</th><th>有效词条（权重）</th></tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table>') if rows else ''
    return f'''<details class="card rules">
<summary>评估规则（评分 / 达标线 / 判定 / 本次用到的套装权重）</summary>
<div class="rules-body">
<h3>评分</h3>
<p>条分 = <b>档位值 ÷ 该词条期望值 × 10 × 权重</b>（无效词条记 0 分，总分 = 各条之和）。<br>
<b>期望值</b> = 官方公示的<b>概率期望档位值</b>（Σ 档位值×概率，见 <code>assets/echo_probability.json</code>，统一保留 1 位小数）；官方档位概率不等（双暴低档更常见），
故期望比算术平均低约 10%（双暴）/ 2%~3%（其余）→ <b>平均档 = 10.0 分，满档 ≈ 13.1~14.0 分</b>。<br>
词条只认"落在档位表上的离散值"；详情面板前 2 行是主属性，不计入词条。词条名/声骸名走容错归一化（剥图标误读、拆字、错字）。<br>
词条后的 <code>[前 X%]</code> = 该档位在官方分布中的<b>分位</b>（概率表里 ≥ 该档的概率之和）—— 这是<b>跨词条可比</b>的质量度量：
同一句"达平均档（r ≥ 1.0）"在暴击上其实只覆盖前 53%，在暴击伤害上却是前 30%，用分位才能对齐口径（暴击 8.7 与 攻击% 8.6 都在前 22%）。</p>
<h3>达标线（锚线）</h3>
<p><b>达标线 A = 10 × 本只"出现的有效词条"的权重之和</b>（n = 词条数，L = n−1）。<br>
"有效" = 该套装启用、权重 &gt; 0 的词条；<b>基准线 B</b>（旧规则）= 该套装有效键最低 L 条之和 × 10
（配置未定制的套装即通用线 <b>6.5 / 11.5 / 17.5</b>）。<br>
A 要求"这只有效词条每条都达到自己的平均档位"（平均档 = 有价值）。出现有效词条数 k ≥ L 时
<b>A ≥ B 恒成立</b>；k &lt; L 时 A 的求和项变少、可能低于 B —— 此时该只<b>最高只能到"保留"</b>（基准线是下限）。<br>
Lv5 / Lv10 为结构判定：只要存在"首条核心词条"即通过，不限分。</p>
<h3>判定（六档）</h3>
<p>两条线：<b>达标线 A</b>（平均档水平）、<b>基准线 B</b>（旧规则线）。满级按下表逐级命中：</p>
<ul>
<li><b>达标</b>：<b>A ≥ B</b> 且 总分 ≥ A —— 达标线本身必须站在基准线之上</li>
<li><b>保留</b>：总分 ≥ B —— 过了基准门槛即算（<b>含 A &lt; B 的情形</b>：出现有效词条太少、达标线不成立的，最高只能到这档）</li>
<li><b>建议重铸</b>：值得花频整器 —— 判据是<b>「锁 L 条 + 刷 5−L 条」后真正达标的概率 ≥ 60%</b>（穷举 L=1~4 与"锁哪几条"）：
<b>E_feat = 10 × Σw(可用池) ÷ (13−L)</b>（官方：词条类型等概率、锁定的类型不会再出现）；
<b>期望档位 r̄ = [Σ(rᵢ·wᵢ)锁定 + W_new] ÷ [Σw锁定 + W_new]</b>（新刷的那部分按档位 1.0 计）。<br>
方案要<b>同时</b>满足三道门：<b>① 重铸后的达标线站得住</b>（10×Σw_after ≥ B —— 否则这只永远达不到标，
最典型的就是"锁 1 条低权重词条 + 刷 4 条"）、<b>② r̄ ≥ 1.0</b>（等价于"期望分 ≥ 重铸后的达标线"）、
<b>③ 蒙特卡洛达标概率 ≥ 60%</b>（3000 次模拟：期望只是均值、实际约五成把握，而胚子可无限刷，
花 30 元买低概率不值）。在满足的方案里取<b>成本最低</b>（<b>成本 = max(1, L−1) 个频整器</b>），报告给出
「锁哪几条 · 刷几条 · 约多少元 · <b>达标概率</b> · 期望分 · r̄ · 届时达标线」。判据刻意不是"期望分 ≥ 保留线 B"——
那会允许"花 60 元只买到一个保留档位"</li>
<li><b>不合格</b>（满级）：其余</li>
</ul>
<p><b>得分下方的「完成度 X%」</b>：本只得分 ÷ <b>该套装 Top-5 权重词条全满档</b>的分数 —— 100% = 毕业；
只出 3 条有效的件上限天然约 72%。它同时反映"有效条数"与"档位高低"，是看"离毕业多远"的主指标。<br>
（早期版本还展示过「击败 X%」= 按官方概率模拟"随机满级声骸"分布后本只的分位；它<b>主要反映"抽到几条有效词条"</b>、
而档位高低只影响 ±40%，"5 条全最低档"就已击败 97% —— 与玩家"离毕业多远"的比较习惯不符，已<b>不再展示</b>。）</p>
<p><b>建议强化</b>（未满级）：总分 ≥ B(满级)（已达保留线, 稳了）；或「继续开到满级达 B(满级) 的概率 ≥ 60%」<b>且</b>
现有条分 ≥ A(现有) —— 后者是"现有几条自己站得住"，只看前瞻会放过"权重低但档位好"的件。<br>
<b>不建议强化</b>（未满级）：两者都不满足 —— 强化材料有限, 没前途的件及时止损。<br>
<b>0 级 / 无词条</b>：无评估价值，不写入报告。<br>
<b>保留 / 建议重铸仅为报告建议，强化流程不豁免</b>（不达标仍丢弃）。</p>
<h3>套装如何判定</h3>
<p>优先读游戏详情面板的<b>套装图标</b>（与 <code>assets/echo_icons/</code> 34 套模板做灰度 ZNCC，s1 ≥ 0.60 且与次优间隔 ≥ 0.05 才采信）；
置信不足时回退"声骸名 → 套装候选"（官方配置表 229 个显示名，<code>异相·X</code> 皮肤条目按自己的套装），都拿不到则按通用。
报告中「套装」列可悬停查看来源。</p>
<h3>COST 与官方主属性方案</h3>
<p>「COST/主属性」列给出面板 COST 角标（1/3/4）、两条主属性，以及游戏内置<b>声骸管理方案</b>
（<code>PhantomManagePlanV2</code>，经 <code>tools/gen_echo_data.py</code> 生成到 <code>assets/gamedata/</code>）
对该套装该 COST 的判定：<b style="color:#2e7d32">✔</b> = 在官方保留组、
<b style="color:#c62828">✘</b> = 被官方列入丢弃组、<b style="color:#999">·</b> = 官方未表态（合法但不推荐）。
悬停可看该 (套装, COST) 的保留/丢弃组。</p>
<h3>本次报告涉及的套装权重</h3>
<p>权重决定该词条算多少分，也决定达标线取哪些词条（权重越低越先被算进锚线）。</p>
{weights_html}
</div>
</details>'''


def _build_eval_html(data):
    """生成评估报告 HTML。"""
    total = data.get("total", 0)
    results = data.get("results", [])
    ts = data.get("evaluated_at", "")

    pass_n = sum(1 for r in results if r["verdict"] == "pass")
    pend_n = sum(1 for r in results if r["verdict"] == "pending")
    fail_n = sum(1 for r in results if r["verdict"] == "fail")
    zero_n = sum(1 for r in results if r["verdict"] == "zero")
    keep_n = sum(1 for r in results if r["verdict"] == "keep")
    hold_n = sum(1 for r in results if r["verdict"] == "hold")

    rows = []
    for r in results:
        v = r["verdict"]
        color = VERDICT_COLOR.get(v, "#888")
        # 判定文案**以记录里的 verdict_cn 为准**(判定层产出); 旧报告缺该字段时才用 VERDICT_CN 兜底
        vcn = r.get("verdict_cn") or VERDICT_CN.get(v, "")
        stat_lines = []
        for s in r.get("stats", []):
            detail = s.get("detail") or f"{s.get('name')}={s.get('value')}"
            ratio = s.get("ratio")
            bg = ""
            if isinstance(ratio, (int, float)):
                bg = f' style="background:{_ratio_color(ratio)}"'
            stat_lines.append(f'<div class="stat"{bg}>{detail}</div>')
        stats_html = "".join(stat_lines) or '<div class="stat" style="color:#bbb">未强化/无词条</div>'
        name = r.get("name", "")
        # OCR 原文与规范名不同(错字已被容错匹配纠正)时, 把原文放进 title 供追溯
        name_raw = r.get("name_raw") or name
        name_title = f' title="OCR 识别为: {name_raw}"' if name_raw != name else ''
        # 套装来源(resolve_set_name): icon=详情面板图标判定 / name=声骸名候选兜底 / default=通用; 旧报告无字段 → "—"
        set_name = r.get("set") or "—"
        set_src = {"icon": "套装图标判定", "name": "声骸名兜底",
                   "default": "默认(通用)"}.get(r.get("set_src"), "")
        # 主指标"完成度" = 得分 ÷ 该套装 Top-5 全满档 —— 玩家直觉的"离毕业多远"(100% = 毕业)
        # 注: 旧的"击败 X%"(相对随机产出的分位)已按用户要求**不再展示** —— 它对"抽到几条有效词条"远比
        #     "档位多高"敏感(5 条全最低档就已击败 97%), 与玩家的比较体系不符;
        #     实现仍留在 src/echo_score_sim.score_percentile 供离线分析用。
        from src.echo_score_sim import completeness
        comp = completeness(r.get("set"), r["score"])
        comp_html = (f'<br><b style="font-size:12px">完成度 {comp:g}%</b>' if comp is not None else '')
        # 建议重铸: 附"锁哪几条 / 刷几条 / 约多少元 / 达标概率 / 期望量"(reforge_plan 的结果)
        # 判据已改为**蒙特卡洛达标概率 ≥ 60%** —— "期望达标"实际只有约五成把握, 而胚子可无限刷,
        # 不值得为低概率花频整器(30 元/个); 期望量(e_feat / r̄ / 期望分)仍列出供对照
        # 未满级"建议强化": 附"继续开到满级能过保留线的概率"(enchant_prospect 前瞻)
        pr = r.get("prospect")
        pr_html = (f'<br><span style="color:#999;font-size:11px">继续到满级过保留线 ≈ {pr * 100:.0f}%</span>'
                   if pr is not None else '')
        rf = r.get("reforge")
        rf_html = (f'<br><span style="color:#999;font-size:11px">锁 {"+".join(rf["lock"])}'
                   f' · 刷 {rf["refresh"]} 条 · ≈ {rf["cost"]} 元'
                   f' · <b>达标概率 {rf.get("p_pass", 0) * 100:.0f}%</b>'
                   f' · 期望 {rf["expected"]} 分 · r̄ {rf.get("rbar", "—")}'
                   f' · 届时达标线 {rf.get("a_after", "—")}</span>'
                   ) if rf else ''
        # COST + 主属性 + 官方管理方案(PhantomManagePlanV2)判定: L2 起由 evaluate_one 提供;
        # 旧报告没有这些字段 → 整格显示 "—"(不报错)
        mp_html = "".join(
            f'<div class="stat">{m.get("name")} {m.get("value"):g}</div>'
            for m in (r.get("main_props") or [])) or '<span style="color:#bbb">—</span>'
        pc = r.get("plan_check") or {}
        plan_mark = {"ok": ("✔", "#2e7d32", "官方方案认可该主属性"),
                     "off": ("✘", "#c62828", "官方方案把它列入丢弃组"),
                     "other": ("·", "#999", "官方方案未表态(合法但不推荐)"),
                     "unknown": ("?", "#999", "主属性名没认出来")}.get(pc.get("state"))
        plan_html = ""
        if plan_mark:
            plan = pc.get("plan") or {}
            plan_html = (f'<div title="官方管理方案: 保留 {plan.get("lock", [])} / '
                         f'丢弃 {plan.get("discard", [])}" style="color:{plan_mark[1]};font-size:11px">'
                         f'{plan_mark[0]} 官方方案</div>')
        # 主属性**数值**校验(阶段二十七): 不在官方 5★ 网格上 → 疑似 OCR 误读, 标 ⚠
        mvc = r.get("main_values_check") or []
        val_html = ""
        if mvc:
            detail = "; ".join(f'{m.get("name")} {m.get("value"):g} → 应接近 {m.get("expect"):g}' for m in mvc)
            val_html = (f'<div title="数值不在官方可能的网格上(疑似 OCR 误读): {detail}" '
                        f'style="color:#c62828;font-size:11px">⚠ 数值可疑</div>')
        cost_txt = f'{r["cost"]}C' if r.get("cost") else "—"
        rows.append(
            f'<tr data-score="{r["score"]}" data-verdict="{v}" data-name="{name}" data-set="{set_name}"'
            f' data-cost="{r.get("cost") or ""}" data-plan="{pc.get("state") or ""}"'
            f' data-mpval="{"bad" if mvc else ""}"'
            f' data-comp="{comp if comp is not None else -1}">'
            f'<td>{r["index"]}</td>'
            f'<td><img src="eval_screenshots/{r["screenshot"]}" width="180"></td>'
            f'<td{name_title}>{name}</td>'
            f'<td title="{set_src}">{set_name}</td>'
            f'<td><b>{cost_txt}</b>{plan_html}{val_html}{mp_html}</td>'
            f'<td>{r["score"]}{comp_html}</td>'
            f'<td style="color:{color};font-weight:bold">{vcn}{pr_html}{rf_html}</td>'
            f'<td>{stats_html}</td></tr>')

    names = sorted({r.get("name", "") for r in results if r.get("name")})
    datalist = "".join(f'<option value="{n}">' for n in names)
    set_counts = {}
    for r in results:
        name = r.get("set") or "通用"
        set_counts[name] = set_counts.get(name, 0) + 1
    set_options = '<option value="">全部套装</option>' + "".join(
        f'<option value="{n}">{n}（{c}）</option>'
        for n, c in sorted(set_counts.items(), key=lambda kv: -kv[1]))
    rules_html = _build_rules_html(results)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>声骸评估报告</title>
<style>{_EVAL_CSS}</style></head>
<body>
<h1>声骸评估报告</h1>
<div class="card">
<p>评估时间: {ts} | 共 <b>{total}</b> 个</p>
<div class="summary">
<span style="background:#e8f5e9;color:#2e7d32">达标 {pass_n}</span>
<span style="background:#e0f2f1;color:#00695c">保留 {hold_n}</span>
<span style="background:#e3f2fd;color:#1565c0">建议重铸 {keep_n}</span>
<span style="background:#fff3e0;color:#e65100">建议强化 {pend_n}</span>
<span style="background:#ffebee;color:#c62828">不建议强化 {fail_n}</span>
<span style="background:#eceff1;color:#607d8b">0级/无词条 {zero_n}</span>
</div>
</div>
{rules_html}
<div class="card">
<div class="filters">
<span>得分: ≥ <input id="fmin" type="number" step="0.1" style="width:70px"></span>
<span>≤ <input id="fmax" type="number" step="0.1" style="width:70px"></span>
<span class="sep">|</span>
<span>判定:</span>
<label><input type="checkbox" class="fv" value="pass" checked> 达标</label>
<label><input type="checkbox" class="fv" value="hold" checked> 保留</label>
<label><input type="checkbox" class="fv" value="keep" checked> 建议重铸</label>
<label><input type="checkbox" class="fv" value="pending" checked> 建议强化</label>
<label><input type="checkbox" class="fv" value="fail" checked> 不建议强化</label>
<label><input type="checkbox" class="fv" value="zero" checked> 0级/无词条</label>
<span class="sep">|</span>
<span>名称: <input id="fname" list="namelist" placeholder="包含匹配" style="width:130px"></span>
<span class="sep">|</span>
<span>套装: <select id="fset">{set_options}</select></span>
<span class="sep">|</span>
<span>排序: <select id="fsort"><option value="orig">默认</option><option value="comp_desc">完成度 ↓</option><option value="comp_asc">完成度 ↑</option></select></span>
<datalist id="namelist">{datalist}</datalist>
<button id="fclear">清除筛选</button>
<span id="cnt" class="cnt"></span>
</div>
<table>
<thead><tr><th>#</th><th>截图</th><th>名称</th><th>套装</th><th>COST/主属性</th><th>得分</th><th>判定</th><th>词条明细</th></tr></thead>
<tbody id="tbody">{"".join(rows)}</tbody>
</table>
</div>
<script>const TOTAL={total};
{_EVAL_JS}</script>
</body></html>'''
