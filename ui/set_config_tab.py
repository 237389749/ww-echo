"""
套装配置面板 — 直接读写 echo_set_templates.json, 表格UI。
"""
import json
import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, CheckBox, ComboBox, DoubleSpinBox, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, MessageBox, PushButton, PushSettingCard, SettingCard,
                            SettingCardGroup, TableWidget, TitleLabel)

from src.echo_set_templates import STAT_ORDER
from src.echo_stats import DEFAULT_WEIGHTS

TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

# 词条表(含展示顺序)的唯一来源 = echo_set_templates.STAT_ORDER(以前这里另抄了一份)
ALL_STATS = list(STAT_ORDER)


class SetConfigTab(QWidget):
    saved = Signal()  # 保存后通知外部

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._setup_ui()
        self._load_sets()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        title = TitleLabel()
        title.setText("套装配置")
        sub = CaptionLabel()
        sub.setText("每个套装独立配置有效词条与权重; 勾选=有效(自动带出通用默认权重), 「首核」= Lv5 首条必须命中的核心词条。")
        layout.addWidget(title)
        layout.addWidget(sub)

        # ── 顶部: 选择 + 保存/导入/导出 ──
        g_top = SettingCardGroup("模板", self)
        self.pick_card = SettingCard(FIF.LIBRARY, "当前套装",
                                     "保存后评估/强化立即使用该套装权重(评估仍优先按面板图标映射)", self)
        self.set_combo = ComboBox()
        self.set_combo.setMinimumWidth(180)
        self.set_combo.currentTextChanged.connect(self._on_set_changed)
        self.save_btn = PushButton(FIF.SAVE, "保存当前套装")
        self.save_btn.clicked.connect(self._save)
        self.pick_card.hBoxLayout.addWidget(self.set_combo, 0, Qt.AlignRight)
        self.pick_card.hBoxLayout.addSpacing(12)
        self.pick_card.hBoxLayout.addWidget(self.save_btn)
        self.pick_card.hBoxLayout.addSpacing(16)

        self.io_card = SettingCard(FIF.SYNC, "导入 / 导出 / 重新加载",
                                   "导入会覆盖当前模板(自动备份为 .bak); 重新加载会丢弃未保存的修改", self)
        for text, icon, slot in (("导出", FIF.SAVE, self._export),
                                 ("导入", FIF.FOLDER, self._import),
                                 ("重新加载", FIF.SYNC, self._reload)):
            btn = PushButton(icon, text)
            btn.clicked.connect(slot)
            self.io_card.hBoxLayout.addWidget(btn)
            self.io_card.hBoxLayout.addSpacing(8)
        self.io_card.hBoxLayout.addSpacing(8)
        g_top.addSettingCards([self.pick_card, self.io_card])
        layout.addWidget(g_top)

        # ── 表格(Fluent TableWidget) ──
        self.table = TableWidget()          # 注意: Fluent TableWidget 构造只收 parent, 行列要单独设
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["有效", "词条", "权重", "首核"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 130)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 60)
        self.table.setToolTip("首核 = Lv5 首条必须命中的核心词条; 全部勾选(=缺省)表示所有有效词条都可作首条")
        self.table.verticalHeader().setVisible(False)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setRowCount(len(ALL_STATS))

        for row, name in enumerate(ALL_STATS):
            cb = CheckBox()
            cb.stateChanged.connect(lambda s, r=row: self._on_check(r, s))
            self.table.setCellWidget(row, 0, cb)

            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, item)

            spin = DoubleSpinBox()
            spin.setFixedWidth(120)
            spin.setRange(0, 10)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)          # 0.85/0.5 等两位小数不失真
            spin.valueChanged.connect(lambda v, r=row: self._on_weight(r, v))
            self.table.setCellWidget(row, 2, spin)

            cb_core = CheckBox()
            cb_core.stateChanged.connect(lambda s, r=row: self._on_core_check(r, s))
            self.table.setCellWidget(row, 3, cb_core)

        layout.addWidget(self.table, 1)

        # ── 底部: 规则说明(可折叠) + JSON 路径 ──
        self.rules_toggle = PushButton(FIF.INFO, "权重与两条线怎么用")
        self.rules_toggle.clicked.connect(self._toggle_rules)
        layout.addWidget(self.rules_toggle)
        self.rules_box = QWidget()
        rb = QVBoxLayout(self.rules_box)
        rb.setContentsMargins(4, 0, 4, 0)
        rb.setSpacing(4)
        for text in (
                "权重决定「该词条算多少分」, 也决定达标线取哪些词条(权重越低越先被算进锚线); 未勾选的词条记 0 分。",
                "达标线 A = 10 × 本只出现的有效词条权重之和; 基准线 B = 该套装有效键最低 (tier-1) 条之和 ×10",
                "(未定制的套装 B 即通用线 6.5 / 11.5 / 17.5; 用低权重「占位键」压 B 是刻意取向, 不被通用标准覆盖)",
                "满级: A≥B 且 总分≥A → 达标; 总分≥B → 保留; 未过线但「锁 N 刷 M 后达标概率≥60%」 → 建议重铸; 否则不合格",
                "未满级: 总分≥B(满级) 或 (前瞻概率≥60% 且 总分≥A) → 建议强化; 否则不建议强化",
                "「首核」只影响 Lv5/Lv10 的结构判定(有首核词条即过, 不限分); 全部勾选表示缺省=所有有效词条。",
                f"存档文件: {TEMPLATE_PATH}(改完记得点「保存当前套装」)"):
            lbl = CaptionLabel()
            lbl.setText(text)
            lbl.setWordWrap(True)
            rb.addWidget(lbl)
        self.rules_box.setVisible(False)
        layout.addWidget(self.rules_box)

    def _toggle_rules(self):
        show = not self.rules_box.isVisible()
        self.rules_box.setVisible(show)
        self.rules_toggle.setText("权重与两条线怎么用（收起）" if show else "权重与两条线怎么用")

    @staticmethod
    def _info(ok: bool, title: str, content: str, parent):
        (InfoBar.success if ok else InfoBar.error)(title, content, duration=3000,
                                                   position=InfoBarPosition.TOP_RIGHT, parent=parent)

    # ── JSON IO ──
    def _read(self):
        try:
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"version": 1, "sets": {}}

    def _write(self, data):
        os.makedirs(os.path.dirname(TEMPLATE_PATH) or ".", exist_ok=True)
        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 数据 → UI ──
    def _load_sets(self):
        data = self._read()
        names = list(data.get("sets", {}).keys())
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItems(names)
        self.set_combo.blockSignals(False)
        if names:
            self._load_set_to_table(names[0])

    def _on_set_changed(self, name):
        if name and not self._loading:
            self._load_set_to_table(name)

    def _load_set_to_table(self, set_name):
        self._loading = True
        stats = self._read().get("sets", {}).get(set_name, {})
        for row, name in enumerate(ALL_STATS):
            w = stats.get(name, 0.0)
            self.table.cellWidget(row, 0).blockSignals(True)
            self.table.cellWidget(row, 0).setChecked(w > 0)
            self.table.cellWidget(row, 0).blockSignals(False)
            self.table.cellWidget(row, 2).blockSignals(True)
            self.table.cellWidget(row, 2).setValue(w)
            self.table.cellWidget(row, 2).blockSignals(False)
        # 首核列: _core_first 缺省(未配置)=全部有效词条; 显式配置则按列表勾选
        core = stats.get('_core_first') if isinstance(stats, dict) else None
        for row, name in enumerate(ALL_STATS):
            cb_core = self.table.cellWidget(row, 3)
            cb_core.blockSignals(True)
            if core is None:
                cb_core.setChecked(stats.get(name, 0.0) > 0)   # 缺省 → 全部有效为首核
            else:
                cb_core.setChecked(name in core)
            cb_core.blockSignals(False)
        self._loading = False

    # ── UI → 数据 ──
    def _on_check(self, row, state):
        if self._loading:
            return
        spin = self.table.cellWidget(row, 2)
        if state == Qt.Checked and spin.value() == 0:
            # 勾选 → 带出该词条的通用默认权重(如 暴击1.0 / 爆伤0.9 / 专伤0.6 / 固定攻0.5),
            # 与 DEFAULT_WEIGHTS 一致, 用户可再微调
            spin.setValue(DEFAULT_WEIGHTS.get(ALL_STATS[row], 1.0))
        elif state == Qt.Unchecked:
            spin.setValue(0.0)
            cb_core = self.table.cellWidget(row, 3)
            cb_core.blockSignals(True)
            cb_core.setChecked(False)     # 取消有效 → 同步取消首核
            cb_core.blockSignals(False)

    def _on_core_check(self, row, state):
        if self._loading:
            return
        if state == Qt.Checked:
            # 首核必须先是有效词条 → 自动勾上有效并带出默认权重
            self._on_check(row, Qt.Checked)
            cb = self.table.cellWidget(row, 0)
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)

    def _on_weight(self, row, value):
        if self._loading:
            return
        cb = self.table.cellWidget(row, 0)
        cb.blockSignals(True)
        cb.setChecked(value > 0)
        cb.blockSignals(False)

    def _collect(self):
        stats = {}
        for row, name in enumerate(ALL_STATS):
            v = round(self.table.cellWidget(row, 2).value(), 2)
            if v > 0:
                stats[name] = v
        # 首核列: 勾选集合 == 全部有效词条 → 不写字段(缺省语义=全部有效为首核); 否则显式写
        core = [ALL_STATS[row] for row in range(len(ALL_STATS))
                if self.table.cellWidget(row, 3).isChecked() and ALL_STATS[row] in stats]
        if core and len(core) < len(stats):
            stats['_core_first'] = core
        # 透传声骸清单 _echoes(4c/3c/1c), 防止 UI 保存覆盖时丢失
        cur = self._read().get("sets", {}).get(self.set_combo.currentText(), {})
        if isinstance(cur, dict) and isinstance(cur.get('_echoes'), dict):
            stats['_echoes'] = cur['_echoes']
        return stats

    def _save(self):
        name = self.set_combo.currentText()
        if not name:
            return

        # 兜底校验: 勾选了但权重=0 → 带出通用默认权重; 权重>0但未勾选 → 勾上
        fixed = 0
        for row in range(len(ALL_STATS)):
            cb = self.table.cellWidget(row, 0)
            spin = self.table.cellWidget(row, 2)
            if cb.isChecked() and spin.value() == 0:
                spin.setValue(DEFAULT_WEIGHTS.get(ALL_STATS[row], 1.0))
                fixed += 1
            if not cb.isChecked() and spin.value() > 0:
                cb.setChecked(True)
                fixed += 1
        if fixed:
            self._log(f"自动修正 {fixed} 处不一致 (勾选↔权重)")

        data = self._read()
        data["sets"][name] = self._collect()
        self._write(data)
        self.saved.emit()
        self._info(True, "已保存", f"{name}: {len(self._collect())} 个有效词条", self)

    def _log(self, msg):
        """简单的控制台日志。"""
        try:
            from ok import Logger
            Logger.get_logger(__name__).info(msg)
        except Exception:
            pass

    # ── 导入/导出 ──
    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出", "echo_set_templates.json", "JSON (*.json)")
        if not p:
            return
        try:
            shutil.copy(TEMPLATE_PATH, p)
            self._info(True, "已导出", p, self)
        except OSError as e:
            self._info(False, "导出失败", str(e), self)

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            self._info(False, "JSON 格式错误", str(e), self)
            return
        if not MessageBox("导入模板", f"替换当前模板？\n{p}\n\n原文件会备份为 .bak", self).exec():
            return
        try:
            if os.path.exists(TEMPLATE_PATH):
                shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")
            shutil.copy(p, TEMPLATE_PATH)
            self._load_sets()
            self.saved.emit()
            self._info(True, "已导入", p, self)
        except OSError as e:
            self._info(False, "导入失败", str(e), self)

    def _reload(self):
        """从磁盘重新加载模板文件。"""
        if not MessageBox("重新加载", "重新加载模板文件？\n将丢弃当前未保存的修改", self).exec():
            return
        self._load_sets()
        self.saved.emit()
        self._info(True, "已重新加载", TEMPLATE_PATH, self)
