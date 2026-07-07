"""
套装词条&权重配置面板 — 直接读写 JSON, 绕过 ok-script config 系统。
"""

import json
import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QDoubleSpinBox,
                               QComboBox, QFileDialog, QMessageBox, QCheckBox,
                               QLabel, QFrame)
from qfluentwidgets import PushButton, FluentIcon, BodyLabel, StrongBodyLabel

from ok import Logger, og
from ok.gui.widget.CustomTab import CustomTab

logger = Logger.get_logger(__name__)

TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

# 所有 13 个合法词条
ALL_STATS = [
    "暴击", "暴击伤害",
    "攻击百分比", "攻击",
    "生命百分比", "生命",
    "防御百分比", "防御",
    "共鸣效率",
    "普攻伤害加成", "重击伤害加成",
    "共鸣解放伤害加成", "共鸣技能伤害加成",
]


class EchoConfigTab(CustomTab):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self._loading = False
        self._setup_ui()
        self._load_sets()

    @property
    def name(self):
        return "套装配置 | Sets"

    @property
    def icon(self):
        return FluentIcon.SAVE

    def _setup_ui(self):
        # ── 顶部: 套装选择 ──
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 8)

        top_layout.addWidget(StrongBodyLabel("当前套装 | Set:"))
        self.set_combo = QComboBox()
        self.set_combo.currentTextChanged.connect(self._on_set_changed)
        top_layout.addWidget(self.set_combo, 1)

        top_layout.addStretch()

        self.import_btn = PushButton(FluentIcon.FOLDER, "导入 | Import")
        self.import_btn.clicked.connect(self._import_json)
        top_layout.addWidget(self.import_btn)

        self.export_btn = PushButton(FluentIcon.SAVE, "导出 | Export")
        self.export_btn.clicked.connect(self._export_json)
        top_layout.addWidget(self.export_btn)

        top_layout.addStretch(1)
        self.add_widget(top)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        self.add_widget(sep)

        # ── 表格: 勾选 + 词条名 + 权重 ──
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["有效", "词条", "权重"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 100)
        self.table.setRowCount(len(ALL_STATS))
        self.table.verticalHeader().setVisible(False)

        for row, stat_name in enumerate(ALL_STATS):
            # 复选框
            cb = QCheckBox()
            cb.stateChanged.connect(lambda state, r=row: self._on_check_changed(r, state))
            self.table.setCellWidget(row, 0, cb)

            # 词条名 (只读)
            item = QTableWidgetItem(stat_name)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, item)

            # 权重输入
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 10.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.valueChanged.connect(lambda v, r=row: self._on_weight_changed(r, v))
            self.table.setCellWidget(row, 2, spin)

        self.add_widget(self.table, 1)

        # ── 底部操作 ──
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 8, 0, 0)

        self.save_btn = PushButton(FluentIcon.ACCEPT, "保存当前套装 | Save")
        self.save_btn.clicked.connect(self._save_current)
        bottom_layout.addWidget(self.save_btn)

        self.reset_btn = PushButton(FluentIcon.CANCEL, "恢复默认 | Reset")
        self.reset_btn.clicked.connect(self._reset_default)
        bottom_layout.addWidget(self.reset_btn)

        bottom_layout.addStretch()
        self.add_widget(bottom)

        # ── 提示 ──
        hint = BodyLabel("勾选 = 有效词条, 权重 = 评分系数。修改后点保存或切换套装自动保存。\nJSON 文件: assets/echo_set_templates.json")
        hint.setWordWrap(True)
        self.add_widget(hint)

    # ── JSON 读写 ──

    def _read_json(self) -> dict:
        try:
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"version": 1, "sets": {}}

    def _write_json(self, data: dict):
        os.makedirs(os.path.dirname(TEMPLATE_PATH) or ".", exist_ok=True)
        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── UI 交互 ──

    def _load_sets(self):
        data = self._read_json()
        sets = list(data.get("sets", {}).keys())
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItems(sets)
        self.set_combo.blockSignals(False)
        if sets:
            self._load_set_to_table(sets[0])

    def _on_set_changed(self, name):
        if name and not self._loading:
            self._load_set_to_table(name)

    def _load_set_to_table(self, set_name):
        self._loading = True
        data = self._read_json()
        stats = data.get("sets", {}).get(set_name, {})

        for row, stat_name in enumerate(ALL_STATS):
            weight = stats.get(stat_name, 0.0)

            cb = self.table.cellWidget(row, 0)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(weight > 0)
                cb.blockSignals(False)

            spin = self.table.cellWidget(row, 2)
            if spin:
                spin.blockSignals(True)
                spin.setValue(weight)
                spin.blockSignals(False)

        self._loading = False

    def _on_check_changed(self, row, state):
        if self._loading:
            return
        spin = self.table.cellWidget(row, 2)
        if state == Qt.Checked and spin and spin.value() == 0:
            spin.setValue(1.0)

    def _on_weight_changed(self, row, value):
        if self._loading:
            return
        cb = self.table.cellWidget(row, 0)
        if cb:
            cb.blockSignals(True)
            cb.setChecked(value > 0)
            cb.blockSignals(False)

    def _collect_current(self) -> dict:
        stats = {}
        for row, stat_name in enumerate(ALL_STATS):
            spin = self.table.cellWidget(row, 2)
            if spin and spin.value() > 0:
                stats[stat_name] = round(spin.value(), 1)
        return stats

    def _save_current(self):
        set_name = self.set_combo.currentText()
        if not set_name:
            return
        data = self._read_json()
        data["sets"][set_name] = self._collect_current()
        self._write_json(data)
        if og and og.executor:
            from src.echo_set_templates import load_templates
            load_templates(force=True)
        logger.info(f"已保存套装 '{set_name}'")

    # ── 导入导出 ──

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self.window(), "导出 | Export", "echo_set_templates.json",
            "JSON (*.json)"
        )
        if path:
            shutil.copy(TEMPLATE_PATH, path)

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "导入 | Import", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r") as f:
                json.load(f)
        except Exception as e:
            QMessageBox.warning(self.window(), "错误", f"JSON 格式错误: {e}")
            return

        if QMessageBox.question(self.window(), "确认",
                                f"替换当前模板?\n{path}",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        if os.path.exists(TEMPLATE_PATH):
            shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")
        shutil.copy(path, TEMPLATE_PATH)
        from src.echo_set_templates import load_templates
        load_templates(force=True)
        self._load_sets()

    def _reset_default(self):
        if QMessageBox.question(self.window(), "确认",
                                "恢复为项目默认模板?\n当前模板将备份为 .bak",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if os.path.exists(TEMPLATE_PATH):
            shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")
        self._load_sets()
