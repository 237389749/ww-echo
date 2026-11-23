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
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, CheckBox, ComboBox, FluentIcon as FIF,
                            HeaderCardWidget, IndeterminateProgressBar, InfoBar, InfoBarPosition,
                            PrimaryPushButton, PushButton, SettingCardGroup, SimpleCardWidget,
                            SingleDirectionScrollArea, StrongBodyLabel, SubtitleLabel, SwitchButton,
                            ToolTipFilter)

from ww_engine import og, communicate

from src.echo_stats import DEFAULT_WEIGHTS
from src.echo_set_templates import get_set_weights
from ui.present import (VERDICT_CHIP_BG, VERDICT_CN, VERDICT_COLOR, VERDICT_MARK, VERDICT_ORDER,
                        count_verdicts, status_texts, summary_text, verdict_color)
from ui.widgets import WrapSettingCard, flow_row, make_scroll_transparent


class RunTab(QWidget):
    _log_signal = Signal(str)
    _eval_done_signal = Signal(str, str)  # json_path, ss_dir
    _eval_error_signal = Signal(str)
    _task_done_signal = Signal(str)  # message
    _start_result_signal = Signal(bool)  # 引擎提交结果（handler 线程 → UI 线程）

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
        self._start_result_signal.connect(self._on_start_result_ui)
        # 引擎跑完 onetime task 时会发 task_done（执行器线程）→ 转成我们的"结束"状态。
        # **别在 `_run_task` 里直接打「结束」**：`start()` 只是投递，提交完就返回（B2）。
        communicate.task_done.connect(self._on_engine_task_done)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

    # ══════════════════ 界面 ══════════════════
    def _setup_ui(self):
        # 布局(U-05): **状态卡固定在顶部** + 下面左右两栏(左=设置卡组可滚, 右=日志)。
        # 以前整页一个滚动容器, 日志卡的 stretch 在滚动容器里只按 sizeHint 分高度 ——
        # 1120×760 只露出日志卡的标题/工具栏(约 70px), 940×620 整块在折叠之下。
        # 而日志正是评估/强化的**主监控面**(要看"本屏完成/滚动/失败"那些行), 必须常驻。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_status_card())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        # 左栏: 任务卡组 + 规则说明 + 上次评估结果(内容比高度多 → 自己滚)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        # 构建顺序有讲究: 「规则」框必须在「任务卡组」之前 —— 任务卡组末尾会调 _on_task_changed,
        # 那里要 setVisible(self.strategy_info); 而规则框的初始文案要读 strategy_combo,
        # 所以把"填文案"这一步延后到两者都建好之后。
        left_layout.addWidget(self._build_rules_box())
        left_layout.addWidget(self._build_task_group())
        left_layout.addWidget(self._build_eval_card())
        left_layout.addStretch(1)
        left_scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left)
        left_scroll.setMinimumWidth(320)
        splitter.addWidget(left_scroll)

        log_card = self._build_log_card()
        log_card.setMinimumHeight(300)          # 约 12 行日志; 再矮就只剩标题了
        splitter.addWidget(log_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)         # 多余宽度给日志(日志行很长)
        splitter.setSizes([360, 700])
        outer.addWidget(splitter, 1)
        self.splitter = splitter
        self.left_scroll = left_scroll

        self._update_strategy_info(self.strategy_combo.currentText())
        self._update_status_text()
        self._update_mode_badge()

    @staticmethod
    def _cap(text: str) -> CaptionLabel:
        lbl = CaptionLabel()
        lbl.setText(text)
        return lbl

    @staticmethod
    def _card_body(card: HeaderCardWidget, margins=None) -> QVBoxLayout:
        """HeaderCardWidget 的 viewLayout 是**横向**的(库源码: QHBoxLayout(self.view)), 正文要自己套一层纵向。

        `margins` 给紧凑卡片用: 库默认 `24/24/24/24`, 状态卡与日志卡不需要那么大留白
        (状态卡光"标题 48 + 分隔线 + 上下各 24"就吃掉 ~100px, 570 高的最小窗口里太贵)。
        """
        if margins is not None:
            card.viewLayout.setContentsMargins(*margins)
        body = QWidget()
        vb = QVBoxLayout(body)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(10)
        card.viewLayout.addWidget(body)
        return vb

    def _build_status_card(self):
        # U-15: 以前这里有两个同级"标题" —— 卡片头「运行」(15pt) 与 `SubtitleLabel`「强化声骸·渐进式·通用」
        # (20px) 抢层级, 而导航项本来就写着"运行"。改成**无卡片头**的 `SimpleCardWidget`: 只留一个标题,
        # 顺带省掉 48px 的头部留白(570 高的最小窗口里很值)。
        card = SimpleCardWidget()
        self.status_task = SubtitleLabel()
        self.status_state = CaptionLabel()
        # 模式徽标(U-07): 评估的套装判定模式(图标优先 / 精确)以前只在启动日志里打印一行, 界面上看不出来
        self.mode_badge = CaptionLabel()
        body = QVBoxLayout(card)
        body.setContentsMargins(20, 14, 20, 14)
        body.setSpacing(8)
        body.addWidget(self.status_task)
        state_row = QHBoxLayout()
        state_row.addWidget(self.status_state)
        state_row.addSpacing(12)
        state_row.addWidget(self.mode_badge)
        state_row.addStretch()
        body.addLayout(state_row)

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

        # 左栏只有 ~360px: 用 WrapSettingCard(说明换行 + 控件进 FlowLayout), 别往 hBoxLayout 里横排
        self.task_card = WrapSettingCard(
            FIF.ROBOT, "模式", "强化: 强化到满级并按规则丢弃/上锁; 评估: 只读遍历, 打分并生成 HTML 报告", self)
        self.task_combo = ComboBox()
        self.task_combo.addItems(["强化声骸", "评估声骸"])
        self.task_card.add_controls([self.task_combo])

        self.strategy_card = WrapSettingCard(
            FIF.SPEED_HIGH, "策略", "渐进式: 每级单独评估, 不达标立即止损; 传统: 拉满后一次性判断", self)
        self.strategy_combo = ComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        self.strategy_card.add_controls([self.strategy_combo])

        self.set_label = WrapSettingCard(
            FIF.LIBRARY, "套装", "强化按该套装权重与 A/B 两条线判定; 评估忽略此项(按面板图标/声骸名自动映射)", self)
        self.set_combo = ComboBox()
        self.set_combo.setMinimumWidth(150)
        self._load_sets()
        self.set_label.add_controls([self.set_combo])

        # ── 传统模式选项(整块塞进卡片右侧; 仅「传统」策略可见) ──
        self.opt_score_enable = CheckBox("启用评分模式")
        self.opt_score_min = ComboBox()
        self.opt_score_min.setMinimumWidth(60)
        for v in [24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48]:
            self.opt_score_min.addItem(str(v))
        self.opt_score_min.setCurrentText("32")

        trad = QHBoxLayout()          # 暂存; 下面包进 flow_row(左栏只有 ~360px, 必须能换行)
        self.opt_double_crit = CheckBox("必须有双爆")
        self.opt_double_crit.setChecked(True)
        self.opt_all_valid_before_crit = CheckBox("双爆前全有效")
        self.opt_all_valid_before_crit.setChecked(True)
        self.opt_first_must_valid = CheckBox("首条必须有效")
        self.opt_first_must_valid.setChecked(True)
        trad.addWidget(self.opt_double_crit)
        trad.addWidget(self.opt_all_valid_before_crit)
        trad.addWidget(self.opt_first_must_valid)
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
        # 那一排 10 个控件包成**流式行**(窄窗口自动换行); 逐个从暂存布局里取出来
        self.traditional_opts = flow_row([trad.itemAt(i).widget() for i in range(trad.count())])

        self.traditional_card = WrapSettingCard(FIF.TILES, "传统模式选项", "仅在「传统」策略下生效", self)
        self.traditional_card.add_controls([self.traditional_opts])
        self.traditional_card.setVisible(False)

        # 评估: 默认「图标优先」(不滚面板, report6 回归 top-1 99.3%); 勾选后总是下滑读合鸣效果明文
        self.precise_card = WrapSettingCard(
            FIF.ZOOM, "精确模式（评估）",
            "默认图标优先(不滚面板, 约省 8 分钟/轮); 勾选=总是下滑读合鸣效果明文(更慢, 复核用)", self)
        self.opt_precise = CheckBox("开启")
        self.opt_precise.stateChanged.connect(lambda *_: self._update_mode_badge())
        self.precise_card.add_controls([self.opt_precise])
        self.precise_card.setVisible(False)

        self.pause_card = WrapSettingCard(FIF.PAUSE, "成功后暂停", "一轮任务结束后暂停, 便于查看结果与报告", self)
        self.opt_pause = SwitchButton()
        self.opt_pause.setChecked(True)
        self.pause_card.add_controls([self.opt_pause])

        g.addSettingCards([self.task_card, self.strategy_card, self.set_label,
                           self.traditional_card, self.precise_card, self.pause_card])
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
            "套装(默认图标优先): 详情面板图标(固定表头, 不滚面板) → 卡片徽章环色 → 图标低置信才下滑读"
            "「合鸣效果」区明文 → 声骸名候选 → 通用; 勾选「精确模式」= 总是下滑读明文(更慢, 用于复核)\n\n"
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
            "通用权重: 暴击1.0 爆伤0.7 攻击%/生命%/防御% 0.5 共效0.5 专伤0.4 小攻/小生命/小防御 0.25\n"
            "暴击6.3%→8.40分, 10.5%→14.00分; 套装模式权重由套装模板决定, 无效词条=0分\n"
            "判定: 达标线 A = 10×本只出现有效词条的权重和; 基准线 B = 套装有效键最低 tier-1 条之和 ×10\n"
            "满级: A≥B 且 总分≥A → 达标; 总分≥B → 保留; 未过线但「锁 N 刷 M 后达标概率≥60%」→ 建议重铸; "
            "Lv5/10 只看首条是否在首核内(低权重套装可配前 N 档门槛)")
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
        self.log_level_combo = ComboBox()
        self.log_level_combo.addItems(list(self.LOG_LEVELS))
        self.log_level_combo.setMinimumWidth(90)
        self.log_level_combo.currentTextChanged.connect(self._on_log_filter)
        self.log_autoscroll = SwitchButton()
        self.log_autoscroll.setChecked(True)
        self.log_autoscroll.setOnText("自动滚动")
        self.log_autoscroll.setOffText("手动滚动")
        # 工具条走**流式行**: 横排时这一条的最小宽是 ~586px, 两栏布局下会把整页撑到 942
        # (940 窗口的内容区只有 750 → 横向裁切)。换行后最小宽 ≈ 单个控件。
        bar_widgets = [self._cap("级别"), self.log_level_combo, self.log_autoscroll]
        for icon, text, slot in ((FIF.COPY, "复制", self._copy_log),
                                 (FIF.DELETE, "清空", self._clear_log),
                                 (FIF.SAVE, "导出", self._export_log)):
            btn = PushButton(icon, text)
            btn.clicked.connect(slot)
            btn.installEventFilter(ToolTipFilter(btn, 400))
            bar_widgets.append(btn)
        body = self._card_body(card, (16, 10, 16, 14))
        body.addWidget(flow_row(bar_widgets))
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

    def _update_mode_badge(self):
        """U-07: 评估的套装判定模式要**一直可见**（以前只在启动日志里打印一行）。"""
        is_eval = "评估" in self.task_combo.currentText()
        self.mode_badge.setVisible(is_eval)
        if not is_eval:
            self.mode_badge.setText("")
            return
        self.mode_badge.setText(
            "套装判定: 精确模式（总是读合鸣效果明文）" if self.opt_precise.isChecked()
            else "套装判定: 图标优先（低置信才读明文）")

    def _update_strategy_info(self, strategy):
        if strategy == "渐进式":
            self.strategy_info.setText(
                "渐进式: 每级单独评估, 不达标即停丢\n"
                "Lv5  第1条 → 首条在「首核」内即过(不限分); 该套装配了低权重门槛时, 首条还须达到前 N 档\n"
                "Lv10 第2条 → 同上(只看第1条, 第2条不兜底)\n"
                "Lv15 第3条 / Lv20 第4条 → 总分 ≥ 基准线 B(满级; 通用 17.5); 或 前瞻概率≥60% 且 总分 ≥ 达标线 A\n"
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
        self.precise_card.setVisible(not is_enhance)
        self._update_mode_badge()
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
        self.opt_precise.setChecked(self._settings.value("precise_set", "false") == "true")

    def _save_settings(self):
        self._settings.setValue("task", self.task_combo.currentText())
        self._settings.setValue("strategy", self.strategy_combo.currentText())
        self._settings.setValue("precise_set", "true" if self.opt_precise.isChecked() else "false")

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
            first, second, third = status_texts(task, "评估" in self.task_combo.currentText())
            self.success_label.setText(first)
            self.fail_label.setText(second)
            self.score_label.setText(third)
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
        reset_stop = getattr(task, 'reset_stop', None)
        if callable(reset_stop):
            reset_stop()
        task.config['强化策略'] = self.strategy_combo.currentText()
        # 评估按面板套装信息自动映射套装(见 evaluate_only / resolve_set_name); 这里置"通用"仅作映射失败时的兜底
        task.config['当前套装'] = '通用' if is_eval else self.set_combo.currentText()
        # 评估: 默认图标优先(不滚面板); 勾选"精确模式"则总是下滑读合鸣效果明文
        task.config['套装精确模式'] = bool(self.opt_precise.isChecked()) if is_eval else False

        if is_eval:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            # 评估的计数从 0 起(状态卡三格读的是评估链的键, 与强化不同 —— 见 status_texts)
            self.success_label.setText("已记录: 0")
            self.fail_label.setText("失败: 0")
            self.score_label.setText("")
            self._append_log("══════════ 开始评估 ══════════")
            self._append_log("评估按面板套装信息(图标/环色/合鸣效果明文)或声骸名自动映射套装权重, 仅打分, 不修改声骸")
            self._append_log("套装模式: " + ("精确模式(总是下滑读明文)" if task.config.get('套装精确模式')
                                          else "图标优先(不滚面板, 低置信才下滑)"))

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
                    # 立刻失败的异常必须落到日志里（带 traceback）：只弹 InfoBar 的话，
                    # 日志里只剩"评估遍历: ..."一行，排查时完全看不到原因（2026-11-14 踩过）。
                    task.log_error('评估异常, 已中止', exception=e)
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
            # 评估跑在本页自己的线程里(不是 executor 线程), disable() 打断不了它;
            # 先置任务的停止事件, evaluate_only 会在每格/每屏之间退出。
            request_stop = getattr(task, 'request_stop', None)
            if callable(request_stop):
                request_stop()
            task.disable()
            task.unpause()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                self._append_log("⚠ 任务线程仍在运行, 将在后台自行结束")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log("══════════ 已停止 ══════════")

    def _run_task(self, task):
        """把任务**提交**给引擎执行器（异步），真正"开始/结束"由引擎回调驱动。

        旧实现把 `start()` 当同步用：它只是 `handler.post(...)` 就返回，于是提交完立刻打
        「══ 结束 ══」、按钮恢复可用 —— 而任务还在跑（日志撒谎 + 可以重复点开始）。
        见 2026-11-22 后端审查 B2。
        """
        self._task = task
        try:
            og.app.start_controller.start(task, on_done=self._start_result_signal.emit)
        except Exception as e:
            self._task_done_signal.emit(f"[ERROR] 启动失败: {e}")

    def _on_start_result_ui(self, ok: bool):
        """引擎的启动结果（设备就绪 / 连不上窗口）。失败才复位，成功继续等 task_done。"""
        if ok:
            self._append_log("已交给执行器, 运行中…")
            return
        self._task_done_signal.emit("[ERROR] 启动失败: 没找到游戏窗口或截图不可用 —— 看日志里的 device 提示")

    def _on_engine_task_done(self, task):
        """执行器发来 `task_done`：只认本页提交的那个任务。"""
        if self._running and task is not None and task is getattr(self, "_task", None):
            self._on_task_done_ui("══════════ 结束 ══════════")

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
            with open(json_path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            # ① **先落数据**: 这是整轮评估唯一不可重建的产物(12 分钟); HTML/截图都可能因为
            #    路径/权限/渲染问题失败 —— 不能连带把数据一起丢(以前顺序反了, 失败时 finally 就把
            #    临时目录删了。2026-11-22 后端审查 B1)。
            json_dest = os.path.join(dest_dir, os.path.splitext(os.path.basename(save_path))[0] + ".json")
            with open(json_dest, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            self._append_log(f"评估数据已存: {json_dest}(「组合穷举」页可直接导入它当库存)")

            # ② 再拷截图: 失败只告警 —— 图缺了报告还能看, 数据已经安全
            ss_dest = os.path.join(dest_dir, "eval_screenshots")
            try:
                if os.path.exists(ss_dest):
                    shutil.rmtree(ss_dest)
                if os.path.exists(ss_dir):
                    shutil.copytree(ss_dir, ss_dest)
                n_ss = len(os.listdir(ss_dest)) if os.path.isdir(ss_dest) else 0
                if n_ss == 0:
                    self._append_log("[!] 没有复制到任何截图 —— 检查上一段日志里有没有『截图落盘失败』")
            except Exception as e:                 # noqa: BLE001 - 截图失败不该让数据/报告也失败
                self._append_log(f"[!] 截图复制失败(报告里的图会缺): {e}")

            # ③ 最后渲染 HTML(失败也只影响报告本体, 数据与截图都已落盘)
            self._update_eval_summary(data)
            html = _build_eval_html(data)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)

            if QMessageBox.question(None, "完成",
                                    f"报告已保存:\n{save_path}\n数据已保存:\n{json_dest}\n\n打开查看?"
                                    ) == QMessageBox.Yes:
                os.startfile(save_path)
        except Exception as e:
            self._append_log(f"[ERROR] 保存失败: {e}"
                             f"{'（评估数据已写出，见上面『评估数据已存』那行）' if 'json_dest' in locals() else ''}")
        finally:
            shutil.rmtree(os.path.dirname(json_path), ignore_errors=True)
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 评估结束 ══════════")

    def _update_eval_summary(self, data: dict):
        """报告数据 → 「上次评估结果」卡: 判定分布 + 平均完成度(同套装内跨件可比)。

        判定分布走 `summary_text` → `count_verdicts`（六档、按 `verdict_cn` 拆分），与报告摘要
        **同一份口径** —— 以前这里按 verdict 码把「不合格 / 不建议强化」并成一个数（U-04）。
        """
        results = data.get("results") or []
        if not results:
            return
        self.sum_verdicts.setText(summary_text(results))
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


# 判定档位的中文名/配色/计数/状态卡文案都在 `ui/present.py`（纯展示逻辑, 无 Qt/引擎依赖:
# 报告 HTML、汇总卡、状态卡共用同一份口径; 也让 tools/ui_probe.py 与单测能直接跑真代码验收）。

# 评估报告样式: 词条按档位(档位/均值)着色, 筛选区样式, 行折叠(U-10), 打印(U-20)
_EVAL_CSS = """
body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#f5f5f5;color:#1f2937}
h1{font-size:24px;margin:0 0 12px}
.card{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.summary{display:flex;gap:12px;font-size:15px;flex-wrap:wrap}
.summary span{padding:4px 12px;border-radius:4px;font-weight:600}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:8px 12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
th{background:#fafafa;font-weight:bold;position:sticky;top:0;font-size:13px;color:#475467;z-index:1}
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

/* ── 行折叠(U-10): 主行 56px 只给"一眼要判断的"; 截图/词条/公式收进详情行 ── */
tr.main{cursor:pointer;height:56px}
tr.main:hover{background:#f6f9fd}
tr.main.open{background:#eef4fb}
tr.main td{padding:5px 12px;border-bottom:1px solid #eef1f5;vertical-align:middle;font-size:13px}
tr.main td.thumb{padding:4px 8px;width:48px}
tr.main img.thumb{width:40px;height:52px;object-fit:cover;display:block}
tr.main td.idx{color:#98a2b3;font-size:12px;width:44px}
tr.main td.score{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.main .comp{display:block;font-size:11px;font-weight:400;color:#667085}
tr.detail td{padding:0;background:#fbfdff;border-bottom:1px solid #e2ebf5}
.detail-box{display:flex;gap:18px;padding:14px 16px;align-items:flex-start}
.detail-box img.full{width:180px;flex:0 0 180px}
.detail-side{flex:1;min-width:0}
.srows{margin-bottom:8px}
.srow{display:flex;align-items:center;gap:10px;padding:2px 0;font-size:13px;line-height:1.5}
.srow .sname{width:8em;color:#42576B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srow .sval{width:6em;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}
.srow .sbar{flex:1;height:6px;background:#eef2f6;border-radius:3px;overflow:hidden}
.srow .sbar i{display:block;height:100%}
.srow.invalid{color:#98a2b3}
.notes{font-size:11px;color:#667085;line-height:1.7}
.notes b{color:#344054}
.vchip{display:inline-block;padding:2px 9px;border-radius:10px;font-size:12px;font-weight:700;white-space:nowrap}
.mark{margin-right:4px}
.hint{font-size:12px;color:#667085;margin:6px 0 0}

/* ── 打印/导出 PDF(U-20): 隐藏筛选条、展开所有行、去阴影 ── */
@media print{
  body{background:#fff;margin:0;font-size:12px}
  .filters,.noprint{display:none!important}
  .card{box-shadow:none;border:1px solid #ddd;break-inside:auto}
  th{position:static}
  tr.detail[hidden]{display:table-row!important}
  tr.main{cursor:default;height:auto}
  tr.main:hover{background:transparent}
  a{color:inherit;text-decoration:none}
}
"""

# 评估报告脚本(原生 JS, 无外部依赖): 行折叠 + 得分区间/判定/名称/套装/COST 筛选 + 排序 + 筛选写进 hash
_EVAL_JS = """
// ── 行折叠(U-10): 只认 tr.main 当数据行; tr.detail 是它的配对详情行 ──
function mainRows(){
  return Array.prototype.slice.call(document.querySelectorAll('#tbody tr.main'));
}
function detailOf(tr){
  var d = tr.nextElementSibling;
  return (d && d.classList.contains('detail')) ? d : null;
}
function syncDetail(tr){
  var d = detailOf(tr);
  if(!d) return;
  // 只有"主行可见 + 已展开"时才显示详情 —— 否则筛掉的行会留下一条孤儿详情
  d.hidden = !(tr.classList.contains('open') && tr.style.display !== 'none');
}
function toggleRow(tr){
  tr.classList.toggle('open');
  syncDetail(tr);
}
document.getElementById('tbody').addEventListener('click', function(e){
  var tr = e.target.closest ? e.target.closest('tr.main') : null;
  if(tr) toggleRow(tr);
});

// ── 筛选 ──
function applyFilter(){
  var min=parseFloat(document.getElementById('fmin').value);
  var max=parseFloat(document.getElementById('fmax').value);
  var nm=document.getElementById('fname').value.trim();
  var st=document.getElementById('fset').value;
  var co=document.getElementById('fcost').value;
  var vs=Array.prototype.slice.call(document.querySelectorAll('.fv'))
            .filter(function(c){return c.checked}).map(function(c){return c.value});
  var shown=0;
  mainRows().forEach(function(tr){
    var s=parseFloat(tr.getAttribute('data-score'));
    // 判定按**中文口径**过滤: "保留(词条缺失)" 以"保留"开头也算保留; 不合格/不建议强化分开选
    var v=tr.getAttribute('data-vcn')||tr.getAttribute('data-verdict')||'';
    var n=tr.getAttribute('data-name')||'';
    var ok=true;
    if(!isNaN(min)&&!(s>=min)) ok=false;
    if(!isNaN(max)&&!(s<=max)) ok=false;
    if(vs.length&&!vs.some(function(x){return v.indexOf(x)===0})) ok=false;
    if(nm&&n.indexOf(nm)<0) ok=false;
    if(st&&(tr.getAttribute('data-set')||'')!==st) ok=false;
    if(co&&(tr.getAttribute('data-cost')||'')!==co) ok=false;
    tr.style.display=ok?'':'none';
    syncDetail(tr);
    if(ok) shown++;
  });
  document.getElementById('cnt').textContent='显示 '+shown+' / '+TOTAL;
  saveHash();
}

// ── 排序: 主行与配对的详情行**一起搬**(否则详情会错位到别的件下面) ──
var _origOrder=null;
function applySort(){
  var tb=document.getElementById('tbody');
  var rows=mainRows();
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
  arr.forEach(function(tr){
    var d=detailOf(tr);            // **先取**配对行: appendChild 之后 nextElementSibling 就变了
    tb.appendChild(tr);
    if(d) tb.appendChild(d);
  });
  saveHash();
}

// ── 筛选/排序写进 location.hash(U-20): 刷新/分享/收藏都能还原 ──
function saveHash(){
  var vs=Array.prototype.slice.call(document.querySelectorAll('.fv'))
            .filter(function(c){return c.checked}).map(function(c){return c.value});
  var q=[['min',document.getElementById('fmin').value],
         ['max',document.getElementById('fmax').value],
         ['name',document.getElementById('fname').value],
         ['set',document.getElementById('fset').value],
         ['cost',document.getElementById('fcost').value],
         ['sort',document.getElementById('fsort').value],
         ['v',vs.join(',')]]
        .filter(function(kv){return kv[1]!==''})
        .map(function(kv){return kv[0]+'='+encodeURIComponent(kv[1])}).join('&');
  if(q!==location.hash.slice(1)) history.replaceState(null,'','#'+q);
}
function loadHash(){
  var q=location.hash.slice(1);
  if(!q) return false;
  var map={};
  q.split('&').forEach(function(kv){
    var i=kv.indexOf('='); if(i<0) return;
    map[kv.slice(0,i)]=decodeURIComponent(kv.slice(i+1));
  });
  if(map.min!==undefined) document.getElementById('fmin').value=map.min;
  if(map.max!==undefined) document.getElementById('fmax').value=map.max;
  if(map.name!==undefined) document.getElementById('fname').value=map.name;
  if(map.set!==undefined) document.getElementById('fset').value=map.set;
  if(map.cost!==undefined) document.getElementById('fcost').value=map.cost;
  if(map.sort!==undefined) document.getElementById('fsort').value=map.sort;
  if(map.v!==undefined){
    var want=map.v.split(',');
    document.querySelectorAll('.fv').forEach(function(c){c.checked=want.indexOf(c.value)>=0});
  }
  return true;
}

['fmin','fmax','fname'].forEach(function(id){
  document.getElementById(id).addEventListener('input',applyFilter)});
['fset','fcost'].forEach(function(id){
  document.getElementById(id).addEventListener('change',applyFilter)});
document.querySelectorAll('.fv').forEach(function(c){
  c.addEventListener('change',applyFilter)});
document.getElementById('fclear').addEventListener('click',function(){
  document.getElementById('fmin').value='';
  document.getElementById('fmax').value='';
  document.getElementById('fname').value='';
  document.getElementById('fset').value='';
  document.getElementById('fcost').value='';
  document.getElementById('fsort').value='orig';
  document.querySelectorAll('.fv').forEach(function(c){c.checked=true});
  applySort();
  applyFilter();
});
document.getElementById('fsort').addEventListener('change',function(){applySort();applyFilter();});
// 打印前先把所有行展开(打印样式里也会强制显示, 这里保证用户看到的就是打印出来的)
window.addEventListener('beforeprint',function(){
  mainRows().forEach(function(tr){tr.classList.add('open');syncDetail(tr);});
});
loadHash();
applySort();
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
"有效" = 该套装启用、权重 &gt; 0 的词条；<b>基准线 B</b>（旧规则）= 该套装有效键最低 L 条之和 × 10。
<b>B 只看该套装自己的非零权重</b>：只有「通用」模式（套装未映射）才是 <b>6.5 / 11.5 / 17.5</b>，套装模式常见 17.5~20.5。<br>
A 要求"这只有效词条每条都达到自己的平均档位"（平均档 = 有价值）。出现有效词条数 k ≥ L 时
<b>A ≥ B 恒成立</b>；k &lt; L 时 A 的求和项变少、可能低于 B —— 此时该只<b>最高只能到"保留"</b>（基准线是下限）。<br>
Lv5 / Lv10 为结构判定：<b>只看首条</b>——首条在「首核」内即通过（不限分）；套装配置了「低权重首条门槛」时，
首条权重 ≤ 阈值还必须落在该词条档位表的前 N 档。</p>
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
<p><b>再下方的「通用评分」</b>：散件口径 —— 按<b>主属性族</b>只启用 攻击/生命/防御 其中一族的
百分比(0.5) + 固定(0.25)（生命主属性的件，攻击%/固定攻击的副词条不计）；暴击 1.0 / 暴击伤害 0.7 /
共鸣效率 0.5 不变；<b>专伤统一 0.2</b>（低于固定攻击 0.25、远低于攻击% 0.5，因为通用口径不知道角色吃哪种）。
<b>主属性是 3C 增伤/共效、4C 暴击/爆伤/治疗时，识别不出三系 → 默认按攻击族（输出向）算</b>。
同名同套装的重复件往往只能当散件或狗粮，这个数衡量那部分价值；<b>只作参考，不参与判定</b>。</p>
<p><b>建议强化</b>（未满级）：总分 ≥ B(满级)（已达保留线, 稳了）；或「继续开到满级达 B(满级) 的概率 ≥ 60%」<b>且</b>
现有条分 ≥ A(现有) —— 后者是"现有几条自己站得住"，只看前瞻会放过"权重低但档位好"的件。<br>
<b>不建议强化</b>（未满级）：两者都不满足 —— 强化材料有限, 没前途的件及时止损。<br>
<b>0 级 / 无词条</b>：无评估价值，不写入报告。<br>
<b>保留 / 建议重铸仅为报告建议，强化流程不豁免</b>（不达标仍丢弃）。</p>
<h3>套装如何判定</h3>
<p><b>默认「图标优先」</b>（2026-11-20 起）：名字有 ≥2 个候选或没认出来时，先读详情面板<b>固定表头</b>的套装图标
（锚定到等级 <code>+NN</code> 框，与 <code>assets/echo_icons/</code> 37 套模板做灰度 ZNCC，s1 ≥ 0.60 且与次优间隔 ≥ 0.05 才采信）
—— <b>不滚面板</b>，真机上约占整轮 46% 的下滑时间因此省掉；
图标不达线就用网格卡片<b>徽章环色</b>收窄名字候选；<b>都不到才下滑</b>读「合鸣效果」区的<b>套装名明文</b>；
再不行才退回"声骸名 → 套装候选"（官方配置表 229 个显示名，<code>异相·X</code> 皮肤条目按自己的套装），最后按通用。</p>
<p><b>勾选「精确模式」</b>时<b>总是</b>下滑读明文（更慢，用于复核）。<b>只属于一套的名字直接按名字定</b>、不读面板。
「合鸣效果<b>原文</b>反查」已停用 —— 那是长文本覆盖率匹配，会把技能描述里的"热熔伤害"当成套装效果（宁缺毋滥）。</p>
<p>报告里「套装」列可悬停查看<b>来源</b>：合鸣效果区套装名 / 套装图标判定 / 卡片徽章环色判定 / 声骸名兜底 / 默认(通用)。
本报告的判定模式见页首「套装判定」一行。</p>
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


def _esc(value) -> str:
    """HTML 转义（属性与正文都用 `quote=True`）。

    报告里的名字/词条/主属性名来自 **OCR**：一个 `"` 就能截断属性、一个 `<` 就吃掉半行，
    筛选下拉与 JS `dataset` 读到的值也会跟着对不上（2026-11-22 后端审查 B8）。
    判定码/套装来源这类枚举值也一起转义 —— 便宜且免得以后加字段时漏掉。
    """
    return html.escape(str(value), quote=True)


def _build_eval_html(data):
    """生成评估报告 HTML。"""
    total = data.get("total", 0)
    results = data.get("results", [])
    ts = data.get("evaluated_at", "")
    # U-07: 本次的套装判定模式(旧报告没有该字段 → "—")
    set_mode = {"precise": "精确模式（总是读明文）",
                "icon_first": "图标优先（低置信才读明文）"}.get(data.get("set_mode"), "—")

    # 判定计数走**共享**的 count_verdicts(与「上次评估结果」卡同一份口径, 见 U-04):
    # fail 一个码里装了两档(满级"不合格" / 未满级"不建议强化"), 必须按 verdict_cn 拆开。
    vcounts = count_verdicts(results)
    pass_n, hold_n, keep_n = vcounts["达标"], vcounts["保留"], vcounts["建议重铸"]
    pend_n, fail_n, bad_n = vcounts["建议强化"], vcounts["不建议强化"], vcounts["不合格"]

    rows = []
    for r in results:
        v = r["verdict"]
        # 判定文案**以记录里的 verdict_cn 为准**(判定层产出); 旧报告缺该字段时才用 VERDICT_CN 兜底
        vcn = r.get("verdict_cn") or VERDICT_CN.get(v, "")
        color = verdict_color(vcn, v)     # U-11: 按中文档位配色(fail 的两档才分得开, 且对比度 ≥4.5)
        # 词条(U-10): 有效词条逐行(名字 + 数值右对齐 + 档位条), 公式/分位只放 title;
        # 无效词条(ratio==0: 该套装不认 / 无档位数据)折叠成一行, 不再占 5 行版面。
        good_stats, bad_stats = [], []
        for st in r.get("stats", []):
            ratio = st.get("ratio")
            if isinstance(ratio, (int, float)) and ratio > 0:
                good_stats.append(st)
            else:
                bad_stats.append(st)
        stat_rows = []
        for st in good_stats:
            ratio = st["ratio"]
            pct = max(0.0, min(1.0, (ratio - 0.65) / 0.7)) * 100
            tip = _esc(st.get("detail") or "")
            stat_rows.append(
                f'<div class="srow" title="{tip}">'
                f'<span class="sname">{_esc(st.get("name", ""))}</span>'
                f'<span class="sval">{_esc(st.get("value", ""))}</span>'
                f'<span class="sbar"><i style="width:{pct:.0f}%;background:{_ratio_color(ratio)}"></i></span>'
                f'</div>')
        if bad_stats:
            names = "、".join(_esc(f'{st.get("name", "")} {st.get("value", "")}') for st in bad_stats)
            stat_rows.append(f'<div class="srow invalid"><span class="sname">无效/不计</span>'
                             f'<span style="flex:1" title="该套装不认这条词条(权重 0)或没有档位数据">'
                             f'{names}</span></div>')
        stats_html = "".join(stat_rows) or '<div class="srow invalid">未强化/无词条</div>'
        name = r.get("name", "")
        name_esc = _esc(name) if name else ("?" if r.get("name_candidates") else "")
        # OCR 原文与规范名不同(错字已被容错匹配纠正)时, 把原文放进 title 供追溯
        name_raw = r.get("name_raw") or name
        # 名字来源: OCR / 套装反查纠正 / 只有候选(读空) —— 都放进 title, 表格里不占宽度
        title_bits = []
        if name_raw != name:
            title_bits.append(f"OCR 识别为: {name_raw}")
        if r.get("name_src") in ("set-fix", "set-only"):
            title_bits.append(f'套装反查纠正({"共享汉字" if r.get("name_how") else ""})'
                              if not r.get("name_how") else f'套装反查纠正({r["name_how"]})')
        if r.get("name_candidates"):
            title_bits.append("候选: " + " / ".join(str(x) for x in r["name_candidates"]))
        name_title = f' title="{_esc(" · ".join(title_bits))}"' if title_bits else ''
        # 套装来源(resolve_set_name): text=合鸣效果区的套装名明文 / effect=合鸣效果原文反查 /
        # icon=详情面板图标 / hue=卡片徽章环色 / name=声骸名候选兜底 / default=通用; 旧报告无字段 → "—"
        set_name = r.get("set") or "—"
        set_name_esc = _esc(set_name)
        set_src = {"text": "合鸣效果区套装名", "effect": "合鸣效果原文反查",
                   "icon": "套装图标判定", "hue": "卡片徽章环色判定", "name": "声骸名兜底",
                   "default": "默认(通用)"}.get(r.get("set_src"), "")
        if r.get("badge_hue") is not None:
            set_src += f' (环色 {float(r["badge_hue"]):.0f})'
        # 主指标"完成度" = 得分 ÷ 该套装 Top-5 全满档 —— 玩家直觉的"离毕业多远"(100% = 毕业)
        # 注: 旧的"击败 X%"(相对随机产出的分位)已按用户要求**不再展示** —— 它对"抽到几条有效词条"远比
        #     "档位多高"敏感(5 条全最低档就已击败 97%), 与玩家的比较体系不符;
        #     实现仍留在 src/echo_score_sim.score_percentile 供离线分析用。
        from src.echo_score_sim import completeness
        comp = completeness(r.get("set"), r["score"])
        comp_html = (f'<br><b style="font-size:12px">完成度 {comp:g}%</b>' if comp is not None else '')
        # 通用评分(散件口径): 按主属性族只启用一族(攻/生/防)的百分比+固定, 专伤 0.2 ——
        # 同名同套装的重复件往往只能当散件/狗粮, 这个数才是它们"换到别的配队"的参考值;
        # **不参与判定**(判定看专用分)。
        gs = r.get("score_generic")
        gen_html = (f'<br><span style="color:#777;font-size:11px;cursor:help" '
                    f'title="通用评分(散件): 按主属性族只启用 攻击/生命/防御 其中一族的百分比(0.5)+固定(0.25), '
                    f'专伤统一 0.2(低于固定攻击、远低于攻击%); 暴击 1.0/爆伤 0.7/共效 0.5 不变。'
                    f'只衡量当散件/狗粮的价值, 不参与判定(判定仍看专用分)">'
                    f'通用评分 {gs:g}</span>'
                    if isinstance(gs, (int, float)) else '')
        # 词条漏读(等级 +NN 说应有更多条): 分数只是下界 → 判定统一压成「保留(词条缺失)」, 这里标出来
        sm = r.get("stats_missing") or 0
        sm_html = ''
        if sm:
            sm_html = (f'<br><span title="等级 +{r.get("level", "?")}: 应有 {5} 条词条, 只读到 {5 - sm} 条'
                       f'(OCR 漏读 → 分数偏低)。判定已压成「保留」, 建议复读这一只" '
                       f'style="color:#c62828;font-size:11px">⚠ 词条缺失 {sm}</span>')
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
                   f' · 期望 {rf.get("expected_units", "—")} 个频整器/件'
                   f' · 期望 {rf["expected"]} 分 · r̄ {rf.get("rbar", "—")}'
                   f' · 届时达标线 {rf.get("a_after", "—")}</span>'
                   ) if rf else ''
        # COST + 主属性 + 官方管理方案(PhantomManagePlanV2)判定: L2 起由 evaluate_one 提供;
        # 旧报告没有这些字段 → 整格显示 "—"(不报错)
        mp_html = "".join(
            f'<div class="stat">{_esc(m.get("name"))} {m.get("value"):g}</div>'
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
        # 主行只放"一眼要判断的": 缩略图/名称/套装/COST+首条主属性/得分+完成度/判定 chip(U-11)
        mp_first = (r.get("main_props") or [{}])[0]
        mp_brief = (f'<span class="mprop">{_esc(mp_first.get("name", ""))} {mp_first.get("value"):g}</span>'
                    if mp_first.get("name") else "")
        chip = (f'<span class="vchip" style="background:{VERDICT_CHIP_BG.get(vcn, "#F2F2F2")};color:{color}">'
                f'<span class="mark">{VERDICT_MARK.get(vcn, "·")}</span>{_esc(vcn)}</span>')
        notes_html = "".join(x for x in (sm_html, gen_html, pr_html, rf_html, plan_html, val_html) if x)
        rows.append(
            f'<tr class="main" data-score="{r["score"]}" data-verdict="{_esc(v)}" data-vcn="{_esc(vcn)}"'
            f' data-name="{name_esc}"'
            f' data-set="{set_name_esc}" data-cost="{r.get("cost") or ""}" data-plan="{pc.get("state") or ""}"'
            f' data-mpval="{"bad" if mvc else ""}" data-comp="{comp if comp is not None else -1}">'
            f'<td class="idx">{r["index"]}</td>'
            f'<td class="thumb"><img class="thumb" src="eval_screenshots/{_esc(r["screenshot"])}" alt=""></td>'
            f'<td{name_title}>{name_esc}</td>'
            f'<td title="{_esc(set_src)}">{set_name_esc}</td>'
            f'<td><b>{cost_txt}</b>{mp_brief}</td>'
            f'<td class="score">{r["score"]}'
            + (f'<span class="comp">完成度 {comp:g}%</span>' if comp is not None else '')
            + f'</td>'
            f'<td>{chip}</td></tr>'
            # 配对详情行: 点击主行展开。**筛选/排序只认 tr.main**(见 _EVAL_JS)
            f'<tr class="detail" hidden><td colspan="7"><div class="detail-box">'
            f'<img class="full" src="eval_screenshots/{_esc(r["screenshot"])}" alt="">'
            f'<div class="detail-side"><div class="srows">{stats_html}</div>'
            f'<div class="notes">{notes_html}</div>'
            f'</div></div></td></tr>')

    names = sorted({r.get("name", "") for r in results if r.get("name")})
    datalist = "".join(f'<option value="{_esc(n)}">' for n in names)
    set_counts = {}
    for r in results:
        name = r.get("set") or "通用"
        set_counts[name] = set_counts.get(name, 0) + 1
    set_options = '<option value="">全部套装</option>' + "".join(
        f'<option value="{_esc(n)}">{_esc(n)}（{c}）</option>'
        for n, c in sorted(set_counts.items(), key=lambda kv: -kv[1]))
    rules_html = _build_rules_html(results)
    # 六档摘要 chips: 与行内判定文字**同一套色**(U-11 —— 以前这里是另一套 #2e7d32/#e65100…,
    # 建议强化 那对只有 3.46:1)。顺序固定, 全部显示(同时充当下面筛选条的图例)。
    chips_html = "".join(
        f'<span style="background:{VERDICT_CHIP_BG[k]};color:{VERDICT_COLOR[k]}">'
        f'<span class="mark">{VERDICT_MARK.get(k, "·")}</span>{k} {n}</span>'
        for k, n in zip(VERDICT_ORDER, (pass_n, hold_n, keep_n, pend_n, fail_n, bad_n)))

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>声骸评估报告</title>
<style>{_EVAL_CSS}</style></head>
<body>
<h1>声骸评估报告</h1>
<div class="card">
<p>评估时间: {ts} | 共 <b>{total}</b> 个 | 套装判定: <span id="setmode">{set_mode}</span></p>
<div class="summary">
{chips_html}
</div>
<p class="hint">截图在同目录的 <code>eval_screenshots/</code> —— 移动/分享报告时请把它一起带走；
要<b>单文件</b>存档用浏览器「打印 → 另存为 PDF」（打印样式会自动展开所有行、隐藏筛选条）。
筛选与排序会写进地址栏，刷新/分享都能还原。</p>
</div>
{rules_html}
<div class="card">
<div class="filters">
<span>得分: ≥ <input id="fmin" type="number" step="0.1" style="width:70px"></span>
<span>≤ <input id="fmax" type="number" step="0.1" style="width:70px"></span>
<span class="sep">|</span>
<span>判定:</span>
<label><input type="checkbox" class="fv" value="达标" checked> 达标</label>
<label><input type="checkbox" class="fv" value="保留" checked> 保留</label>
<label><input type="checkbox" class="fv" value="建议重铸" checked> 建议重铸</label>
<label><input type="checkbox" class="fv" value="建议强化" checked> 建议强化</label>
<label><input type="checkbox" class="fv" value="不建议强化" checked> 不建议强化</label>
<label><input type="checkbox" class="fv" value="不合格" checked> 不合格</label>
<span class="sep">|</span>
<span>名称: <input id="fname" list="namelist" placeholder="包含匹配" style="width:130px"></span>
<span class="sep">|</span>
<span>套装: <select id="fset">{set_options}</select></span>
<span class="sep">|</span>
<span>COST: <select id="fcost"><option value="">全部</option><option value="4">4C</option><option value="3">3C</option><option value="1">1C</option></select></span>
<span class="sep">|</span>
<span>排序: <select id="fsort"><option value="orig">默认</option><option value="comp_desc">完成度 ↓</option><option value="comp_asc">完成度 ↑</option></select></span>
<datalist id="namelist">{datalist}</datalist>
<button id="fclear">清除筛选</button>
<span id="cnt" class="cnt"></span>
</div>
<p class="hint noprint">点任意一行展开截图与词条明细（公式/分位在悬停提示里）；筛选与排序会写进地址栏，可收藏或分享。</p>
<table>
<thead><tr><th>#</th><th>截图</th><th>名称</th><th>套装</th><th>COST/主属性</th><th>得分</th><th>判定</th></tr></thead>
<tbody id="tbody">{"".join(rows)}</tbody>
</table>
</div>
<p class="hint">报告依赖同目录的 <code>eval_screenshots/</code>，分享时请一并带走。</p>
<script>const TOTAL={total};
{_EVAL_JS}</script>
</body></html>'''
