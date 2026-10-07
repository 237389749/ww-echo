"""
「组合穷举」页 —— 声骸组合穷举 + 伤害排名的**输入装配与展示**(规格 panel_plan.md 的 UI 规格)。

边界(与阶段二十四"判定唯一收口"同一条纪律): **UI 不碰伤害公式** ——
面板聚合/穷举/排序全在 `src/echo_panel.py` / `src/echo_combos.py`, 库存导入在 `src/echo_inventory.py`;
本页只做「装配输入 → 后台线程调引擎 → 展示表格 / 导出 CSV」。

契约(用户已定, 见 `handoff.md`): 模式 `5` 或 `3+2`(两套时必须指定 4C 归属)、5 只互异、ΣCOST ≤ 12、
只用 5★、套装计数按去重只数; **补正一律视为生效**(不自动解析套装效果);
伤害只用于排序: `E = 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区)`, 共效不计。
"""
import csv

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, ComboBox, DoubleSpinBox, EditableComboBox, FluentIcon as FIF,
                            HeaderCardWidget, IndeterminateProgressBar, InfoBar, InfoBarPosition, MessageBox,
                            PushButton, SettingCard, SettingCardGroup, SingleDirectionScrollArea, SpinBox,
                            TableWidget, TitleLabel)

from src.echo_combos import PlanRequest, candidate_pool, plan
from src.echo_inventory import load_inventory, summarize
from src.echo_panel import BASE_KEYS, EXTRA_BONUS_KEYS, Correction, aggregate, defense_zone, resist_zone
from src.echo_set_templates import STAT_ORDER, get_all_set_names
from ui.widgets import make_scroll_transparent

# 裸面板/补正表的行 = 13 个词条 + 3 个额外加成键(属伤/声骸技能专伤/通用增伤)
PANEL_ROWS: tuple[str, ...] = tuple(STAT_ORDER) + tuple(EXTRA_BONUS_KEYS)
CRIT_MODES = (("期望(1+暴击率×暴击伤害)", "expect"), ("单次暴击(1+暴击伤害)", "crit"),
              ("单次不暴击(1.0)", "non_crit"))
CORRECTION_SOURCES = ("套装 2 件套", "套装 3 件套", "套装 5 件套", "共鸣链", "队伍增伤", "天赋", "武器", "其他")


def _card_body(card: HeaderCardWidget) -> QVBoxLayout:
    """HeaderCardWidget 的 viewLayout 是横向的, 正文要自己套一层纵向容器。"""
    body = QWidget()
    vb = QVBoxLayout(body)
    vb.setContentsMargins(0, 0, 0, 0)
    vb.setSpacing(10)
    card.viewLayout.addWidget(body)
    card.vBoxLayout.setStretchFactor(card.view, 1)
    return vb


class _PlanWorker(QThread):
    """把 `echo_combos.plan` 放到后台线程跑(穷举是纯 CPU 循环, 不阻塞界面)。"""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, items, req, bare, corrections, parent=None):
        super().__init__(parent)
        self._items, self._req, self._bare, self._corrections = items, req, bare, corrections
        self._stop = False

    def cancel(self):
        self._stop = True                      # 协作式取消: 引擎每 512 组查一次

    def run(self):
        try:
            self.done.emit(plan(self._items, self._req, bare=self._bare,
                                corrections=self._corrections, should_stop=lambda: self._stop))
        except Exception as e:                 # noqa: BLE001 - 线程里必须兜住, 否则界面无声卡住
            self.failed.emit(f"{type(e).__name__}: {e}")


class PlanTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._corrections: list[Correction] = []
        self._combos: list = []
        self._worker: _PlanWorker | None = None
        self._setup_ui()
        self._load_sets()
        self._refresh_panel()

    # ══════════════════ UI ══════════════════
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)
        title = TitleLabel()
        title.setText("组合穷举")
        sub = CaptionLabel()
        sub.setText("对指定套装与仓库里的 5★ 声骸穷举合法 5 件组合并排名; "
                    "套装效果/共鸣链/天赋等一律手填「补正」, 程序不自动解析套装效果。")
        outer.addWidget(title)
        outer.addWidget(sub)

        self.view = QWidget()
        vbox = QVBoxLayout(self.view)
        vbox.setContentsMargins(24, 12, 24, 24)
        vbox.setSpacing(16)
        vbox.addWidget(self._group_goal())
        vbox.addWidget(self._group_battle())
        vbox.addWidget(self._card_panel())
        vbox.addWidget(self._card_result(), 1)

        scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.view)
        outer.addWidget(scroll, 1)

    # ── 角色与目标 ──
    def _group_goal(self) -> SettingCardGroup:
        g = SettingCardGroup("角色与目标", self.view)

        self.goal_card = SettingCard(FIF.TILES, "缩放属性与暴击口径",
                                     "缩放属性决定主属性最优解(攻击/防御/生命角色完全不同); "
                                     "暴击口径影响「暴击区」", self.view)
        self.scaling_combo = ComboBox()
        self.scaling_combo.addItems(list(BASE_KEYS))
        self.crit_combo = ComboBox()
        for text, _key in CRIT_MODES:
            self.crit_combo.addItem(text)
        self.goal_card.hBoxLayout.addWidget(self.scaling_combo, 0, Qt.AlignRight)
        self.goal_card.hBoxLayout.addSpacing(12)
        self.goal_card.hBoxLayout.addWidget(self.crit_combo)
        self.goal_card.hBoxLayout.addSpacing(16)

        self.mode_card = SettingCard(FIF.LIBRARY, "模式与套装",
                                     "5 = 同一套装 5 只; 3+2 = 套装 A 3 只 + 套装 B 2 只"
                                     "(两套时必须指定 4C 归属)", self.view)
        self.mode_combo = ComboBox()
        self.set_a_combo, self.set_b_combo, self.cost4_combo = ComboBox(), ComboBox(), ComboBox()
        self.set_a_combo.setMinimumWidth(170)
        self.set_b_combo.setMinimumWidth(170)
        self.set_a_combo.setToolTip("套装 A(3+2 时是 3 件那套)")
        self.set_b_combo.setToolTip("套装 B(3+2 时 2 件那套; 与 A 不能相同)")
        self.cost4_combo.setToolTip("4C(COST 4)那只声骸属于 A 还是 B")
        self.mode_combo.addItems(["5", "3+2"])
        self.cost4_combo.addItems(["A", "B"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)   # 控件都建好后再接信号
        for w in (self.mode_combo, self.set_a_combo, self.set_b_combo, self.cost4_combo):
            self.mode_card.hBoxLayout.addWidget(w, 0, Qt.AlignRight)
            self.mode_card.hBoxLayout.addSpacing(8)
        self.mode_card.hBoxLayout.addSpacing(16)

        self.inv_card = SettingCard(FIF.FOLDER, "声骸库存",
                                    "从 logs/eval_debug 素材目录或评估 JSON 导入(含图标识别套装); "
                                    "导入即视为 5★(评估数据无稀有度字段)", self.view)
        self.import_btn = PushButton(FIF.DOWNLOAD, "导入最新素材")
        self.import_btn.clicked.connect(lambda: self._import(""))
        self.pick_btn = PushButton(FIF.FOLDER, "选择…")
        self.pick_btn.clicked.connect(self._pick_inventory)
        self.inv_label = CaptionLabel("尚未导入库存")
        self.inv_card.hBoxLayout.addWidget(self.inv_label, 0, Qt.AlignRight)
        self.inv_card.hBoxLayout.addSpacing(12)
        self.inv_card.hBoxLayout.addWidget(self.import_btn)
        self.inv_card.hBoxLayout.addSpacing(8)
        self.inv_card.hBoxLayout.addWidget(self.pick_btn)
        self.inv_card.hBoxLayout.addSpacing(16)

        g.addSettingCards([self.goal_card, self.mode_card, self.inv_card])
        return g

    # ── 战斗环境 ──
    def _group_battle(self) -> SettingCardGroup:
        g = SettingCardGroup("战斗环境(排序里是常数, 只影响展示的「伤害」列)", self.view)
        self.env_card = SettingCard(FIF.SPEED_HIGH, "等级 / 防御 / 抗性",
                                    "防御区 = (100+角色等级) / ((100+角色等级) + (99+怪物等级)×(1−无视防御)); "
                                    "抗性区 = 1 − 抗性%", self.view)

        def spin(rng, val, decimals=0, suffix=""):
            w = DoubleSpinBox() if decimals else SpinBox()
            w.setRange(*rng)
            if decimals:
                w.setDecimals(decimals)
            w.setValue(val)
            w.setSuffix(suffix)
            w.setFixedWidth(132)
            return w

        self.char_level_spin = spin((1, 90), 90, 0, " 级")
        self.monster_level_spin = spin((1, 120), 100, 0, " 级")
        self.def_ignore_spin = spin((0, 100), 0, 1, " %")
        self.resist_spin = spin((-100, 100), 10, 1, " %")
        for w, label in ((self.char_level_spin, "角色"), (self.monster_level_spin, "怪物"),
                         (self.def_ignore_spin, "无视防御"), (self.resist_spin, "抗性")):
            cap = CaptionLabel(label)
            self.env_card.hBoxLayout.addWidget(cap, 0, Qt.AlignRight)
            self.env_card.hBoxLayout.addSpacing(4)
            self.env_card.hBoxLayout.addWidget(w)
            self.env_card.hBoxLayout.addSpacing(10)
        self.env_card.hBoxLayout.addSpacing(8)
        g.addSettingCard(self.env_card)
        return g

    # ── 裸面板 + 补正 ──
    def _card_panel(self) -> HeaderCardWidget:
        card = HeaderCardWidget("裸面板 + 逐词条补正", self.view)
        vb = _card_body(card)
        tip = CaptionLabel()
        tip.setWordWrap(True)
        tip.setText("「攻击/生命/防御」填**基础值**(角色 + 武器, 不含声骸): 面板 = 基础值 × (1 + 百分比/100) "
                    "+ 固定值(calculator 口径, 固定值不吃百分比)。补正可多条、一律视为生效; "
                    "来源只用于追溯(套装 2/3/5 件套、共鸣链、天赋、队伍增伤…) —— 套装效果不自动解析。")
        vb.addWidget(tip)

        self.panel_table = TableWidget()
        self.panel_table.setColumnCount(4)
        self.panel_table.setHorizontalHeaderLabels(["词条", "裸面板", "补正(合计)", "最终值"])
        hh = self.panel_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.panel_table.setColumnWidth(0, 150)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.panel_table.setColumnWidth(1, 150)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.panel_table.setColumnWidth(3, 130)
        self.panel_table.verticalHeader().setVisible(False)
        self.panel_table.setBorderVisible(True)
        self.panel_table.setBorderRadius(8)
        self.panel_table.setRowCount(len(PANEL_ROWS))
        self._bare_spins = {}
        for row, key in enumerate(PANEL_ROWS):
            item = QTableWidgetItem(key)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.panel_table.setItem(row, 0, item)
            spin = DoubleSpinBox()
            spin.setRange(0, 999999)
            spin.setDecimals(1)
            spin.setSingleStep(1)
            spin.setFixedWidth(130)
            spin.valueChanged.connect(self._refresh_panel)
            self.panel_table.setCellWidget(row, 1, spin)
            self._bare_spins[key] = spin
            for col in (2, 3):
                cell = QTableWidgetItem("")
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.panel_table.setItem(row, col, cell)
        vb.addWidget(self.panel_table)

        # 补正录入行 + 明细表
        add_row = QHBoxLayout()
        self.corr_key_combo = ComboBox()
        self.corr_key_combo.addItems(list(PANEL_ROWS))
        self.corr_key_combo.setMinimumWidth(170)
        self.corr_value_spin = DoubleSpinBox()
        self.corr_value_spin.setRange(-99999, 99999)
        self.corr_value_spin.setDecimals(1)
        self.corr_value_spin.setValue(10.0)
        self.corr_value_spin.setFixedWidth(110)
        self.corr_source_combo = EditableComboBox()          # 库里的 ComboBox 没有 setEditable
        self.corr_source_combo.addItems(list(CORRECTION_SOURCES))
        self.corr_source_combo.setMinimumWidth(150)
        add_btn = PushButton(FIF.ADD, "添加补正")
        add_btn.clicked.connect(self._add_correction)
        del_btn = PushButton(FIF.DELETE, "删除选中")
        del_btn.clicked.connect(self._del_correction)
        for w in (CaptionLabel("键"), self.corr_key_combo, CaptionLabel("值"), self.corr_value_spin,
                  CaptionLabel("来源"), self.corr_source_combo, add_btn, del_btn):
            add_row.addWidget(w)
        add_row.addStretch(1)
        vb.addLayout(add_row)

        self.corr_table = TableWidget()
        self.corr_table.setColumnCount(3)
        self.corr_table.setHorizontalHeaderLabels(["补正键", "值", "来源"])
        self.corr_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.corr_table.setColumnWidth(0, 170)
        self.corr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.corr_table.setColumnWidth(1, 100)
        self.corr_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.corr_table.verticalHeader().setVisible(False)
        self.corr_table.setBorderVisible(True)
        self.corr_table.setBorderRadius(8)
        self.corr_table.setFixedHeight(170)         # 约 3 条补正可见, 更多时表内滚动
        vb.addWidget(self.corr_table)
        return card

    # ── 结果排名 ──
    def _card_result(self) -> HeaderCardWidget:
        card = HeaderCardWidget("结果排名", self.view)
        vb = _card_body(card)
        bar = QHBoxLayout()
        self.run_btn = PushButton(FIF.PLAY, "开始穷举")
        self.run_btn.clicked.connect(self._start)
        self.cancel_btn = PushButton(FIF.CANCEL, "取消")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setVisible(False)
        self.csv_btn = PushButton(FIF.SAVE, "导出 CSV")
        self.csv_btn.clicked.connect(self._export_csv)
        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        self.status = CaptionLabel("未导入库存: 先点上方「导入最新素材」或「选择…」")
        for w in (self.run_btn, self.cancel_btn, self.csv_btn, self.progress, self.status):
            bar.addWidget(w)
        bar.addStretch(1)
        vb.addLayout(bar)

        self.result_table = TableWidget()
        self.result_table.setColumnCount(9)
        self.result_table.setHorizontalHeaderLabels(
            ["名次", "5 只声骸(名·COST)", "套装只数", "ΣCOST", "缩放属性总值", "暴击/爆伤",
             "加成区(属+专+通)", "排序分 E", "伤害(防御/抗性)"])
        hh = self.result_table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5, 6, 7, 8):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
        for col, width in ((0, 52), (2, 140), (3, 64), (4, 100), (5, 110), (6, 120), (7, 92), (8, 124)):
            self.result_table.setColumnWidth(col, width)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setBorderVisible(True)
        self.result_table.setBorderRadius(8)
        self.result_table.setMinimumHeight(240)
        self.result_table.setToolTip("双击一行看该组合 5 只声骸的词条明细")
        self.result_table.cellDoubleClicked.connect(self._show_combo)
        vb.addWidget(self.result_table, 1)

        note = CaptionLabel()
        note.setWordWrap(True)
        note.setText("排序分 E = 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区); "
                     "加成区 = 属伤 + 专伤合计(各类型直接相加) + 通用增伤, 共效不计。"
                     "技能倍率/加深/防御/抗性在方案内是常数(排序不受影响), 「伤害」列只把防御区×抗性区折进去。")
        vb.addWidget(note)
        return card

    # ══════════════════ 输入装配 ══════════════════
    def _load_sets(self):
        names = get_all_set_names()
        for combo in (self.set_a_combo, self.set_b_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.blockSignals(False)
        if names:
            self.set_b_combo.setCurrentIndex(min(1, len(names) - 1))
        self._on_mode_changed(self.mode_combo.currentText())

    def _on_mode_changed(self, mode):
        two = mode == "3+2"
        self.set_b_combo.setEnabled(two)
        self.cost4_combo.setEnabled(two)

    def _pick_inventory(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择评估 JSON(image_report.md 所在目录也可)", "",
            "评估 JSON (*.json);;详情转录 (*.md);;所有文件 (*)")
        if path:
            self._import(path)

    def _import(self, path):
        try:
            items = load_inventory(path)
        except Exception as e:                                   # noqa: BLE001 - 直接反馈给用户
            self._info(False, "导入失败", str(e))
            return
        self._items = items
        s = summarize(items)
        self.inv_label.setText(f"{s['total']} 只 / {s['names']} 个名字 | "
                               f"套装 {len(s['by_set'])} 个")
        self._info(True, "已导入库存", f"{s['total']} 只(COST {s['by_cost']})"
                                       + (f", 含「{next(iter(s['by_set']))}」等 {len(s['by_set'])} 套"
                                          if s['by_set'] else ""))
        self.status.setText(f"库存 {s['total']} 只(已按 5★ 处理); 选好套装后点「开始穷举」")

    def _collect_inputs(self):
        bare = {k: spin.value() for k, spin in self._bare_spins.items() if spin.value()}
        return bare, list(self._corrections)

    def _build_request(self) -> PlanRequest:
        return PlanRequest(scaling=self.scaling_combo.currentText(),
                           mode=self.mode_combo.currentText(),
                           set_a=self.set_a_combo.currentText(),
                           set_b=self.set_b_combo.currentText(),
                           cost4_owner=self.cost4_combo.currentText(),
                           crit_mode=dict((t, k) for t, k in CRIT_MODES)[self.crit_combo.currentText()],
                           top_k=50)

    # ══════════════════ 裸面板/补正 ══════════════════
    def _add_correction(self):
        key = self.corr_key_combo.currentText()
        value = self.corr_value_spin.value()
        source = self.corr_source_combo.currentText().strip() or "未标来源"
        self._corrections.append(Correction(key, value, source))
        self._refresh_corrections()

    def _del_correction(self):
        row = self.corr_table.currentRow()
        if 0 <= row < len(self._corrections):
            self._corrections.pop(row)
            self._refresh_corrections()

    def _refresh_corrections(self):
        self.corr_table.setRowCount(len(self._corrections))
        for row, c in enumerate(self._corrections):
            for col, text in enumerate((c.key, f"{c.value:g}", c.source)):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.corr_table.setItem(row, col, cell)
        self._refresh_panel()

    def _refresh_panel(self):
        """重算「补正合计 / 最终值」两列(攻击/生命/防御显示 calculator 口径的总值)。"""
        bare, corrections = self._collect_inputs()
        panel = aggregate(bare, corrections)
        for row, key in enumerate(PANEL_ROWS):
            per_key = [c.value for c in corrections if c.key == key]
            self.panel_table.item(row, 2).setText(
                f"{sum(per_key):g}" if per_key else "—")
            self.panel_table.item(row, 3).setText(self._final_text(panel, key))
        self.panel_table.item(0, 3).setToolTip("基础值 × (1+百分比/100) + 固定值")

    @staticmethod
    def _final_text(panel, key: str) -> str:
        if key in BASE_KEYS:
            return f"{panel.scaling_total(key):.1f}"
        if key in panel.pct:
            return f"{panel.pct[key]:g}"
        if key == "暴击":
            return f"{panel.crit_rate:g}"
        if key == "暴击伤害":
            return f"{panel.crit_dmg:g}"
        if key == "共鸣效率":
            return f"{panel.energy:g}"
        if key == "治疗效果加成":
            return f"{panel.heal:g}"
        return f"{panel.bonus.get(key, 0.0):g}"

    # ══════════════════ 穷举 ══════════════════
    def _start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._items:
            self._info(False, "没有库存", "先点「导入最新素材」或「选择…」导入评估数据")
            return
        req = self._build_request()
        try:
            pool = candidate_pool(self._items, req)
        except ValueError as e:
            self._info(False, "参数不合法", str(e))
            return
        if not pool:
            self._info(False, "没有候选", f"库存里没有「{req.set_a}」"
                                          + (f"/「{req.set_b}」" if req.mode == "3+2" else "") + " 的声骸")
            return
        bare, corrections = self._collect_inputs()
        self._set_running(True)
        self.status.setText(f"穷举中…(候选 {len(pool)} 只)")
        self._worker = _PlanWorker(self._items, req, bare, corrections, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("已请求取消(结果只覆盖已评估的部分)…")

    def _set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.csv_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.progress.setVisible(running)
        if running:
            self.progress.start()
        else:
            self.progress.stop()

    def _on_done(self, res):
        self._set_running(False)
        self._render(res)
        tail = "(已取消, 结果为部分)" if res.cancelled else ""
        self.status.setText(f"候选 {res.candidates} 只 / {res.names} 个名字 | 评估 {res.evaluated} 组 | "
                            f"耗时 {res.elapsed:.3f}s{tail}")
        if not res.combos:
            self._info(False, "没有合法组合",
                       f"候选 {res.candidates} 只: 检查「{self._build_request().set_a}」里是否有足够的"
                       f" 4C/3C/1C 声骸, 以及 ΣCOST ≤ 12 与 4C 归属")

    def _on_failed(self, message):
        self._set_running(False)
        self._info(False, "穷举失败", message)

    def _render(self, res):
        self._combos = res.combos
        self.result_table.setRowCount(len(res.combos))
        zb, rb = self._zone_factors()
        top = res.combos[0].score if res.combos else 0.0
        for row, c in enumerate(res.combos):
            zone = c.panel.bonus_split()
            sets = " + ".join(f"{k}×{v}" for k, v in sorted(c.set_counts.items()))
            combo_text = " ".join(f"{i.name}·{i.cost}C" for i in c.items)
            cells = (str(row + 1), combo_text, sets, str(c.total_cost),
                     f"{c.panel.scaling_total(self._scaling()):.1f}",
                     f"{c.panel.crit_rate:.1f}% / {c.panel.crit_dmg:.1f}%",
                     f"{zone['属伤']:.0f}+{zone['专伤']:.0f}+{zone['通用']:.0f}",
                     f"{c.score:.1f}", f"{c.score * zb * rb:.1f}")
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == 1 and row > 0:
                    cell.setToolTip(f"与第 1 名相差 −{(1 - c.score / top) * 100:.1f}%(排序分)")
                self.result_table.setItem(row, col, cell)

    def _scaling(self) -> str:
        return self.scaling_combo.currentText()

    def _zone_factors(self) -> tuple:
        return (defense_zone(self.char_level_spin.value(), self.monster_level_spin.value(),
                             self.def_ignore_spin.value()),
                resist_zone(self.resist_spin.value()))

    def _show_combo(self, row, _col):
        if not (0 <= row < len(self._combos)):
            return
        combo = self._combos[row]
        lines = [f"第 {row + 1} 名 · 排序分 E {combo.score:.1f} · ΣCOST {combo.total_cost} "
                 f"· {' + '.join(f'{k}×{v}' for k, v in sorted(combo.set_counts.items()))}", ""]
        for i, item in enumerate(combo.items, 1):
            main = "、".join(f"{k} {v:g}" for k, v in item.main) or "—"
            subs = "、".join(f"{k} {v:g}" for k, v in item.stats[len(item.main):]) or "—"
            lines.append(f"{i}. {item.name}  {item.cost}C  [{item.set_name}]")
            lines.append(f"    主属性: {main}")
            lines.append(f"    词条: {subs}")
        MessageBox("组合详情", "\n".join(lines), self).exec()

    def _export_csv(self):
        if not self._combos:
            self._info(False, "没有结果", "先点「开始穷举」")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出排名", "echo_plan.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["名次", "组合", "套装只数", "ΣCOST", "缩放属性总值", "暴击率%", "暴击伤害%",
                            "属伤%", "专伤%", "通用%", "排序分E", "伤害"])
                zb, rb = self._zone_factors()
                for rank, c in enumerate(self._combos, 1):
                    zone = c.panel.bonus_split()
                    w.writerow([rank, " ".join(f"{i.name}·{i.cost}C" for i in c.items),
                                " + ".join(f"{k}×{v}" for k, v in sorted(c.set_counts.items())),
                                c.total_cost, f"{c.panel.scaling_total(self._scaling()):.1f}",
                                f"{c.panel.crit_rate:.1f}", f"{c.panel.crit_dmg:.1f}",
                                f"{zone['属伤']:.1f}", f"{zone['专伤']:.1f}", f"{zone['通用']:.1f}",
                                f"{c.score:.1f}", f"{c.score * zb * rb:.1f}"])
            self._info(True, "已导出", path)
        except OSError as e:
            self._info(False, "导出失败", str(e))

    def _info(self, ok: bool, title: str, content: str):
        (InfoBar.success if ok else InfoBar.error)(title, content, duration=3000,
                                                   position=InfoBarPosition.TOP_RIGHT, parent=self)
