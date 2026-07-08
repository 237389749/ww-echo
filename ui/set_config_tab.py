"""
套装配置面板 — 直接读写 echo_set_templates.json, 表格UI。
"""
import json
import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QDoubleSpinBox,
                               QComboBox, QFileDialog, QMessageBox, QCheckBox,
                               QLabel, QFrame, QPushButton, QSizePolicy)

TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

ALL_STATS = [
    "暴击", "暴击伤害",
    "攻击百分比", "攻击",
    "生命百分比", "生命",
    "防御百分比", "防御",
    "共鸣效率",
    "普攻伤害加成", "重击伤害加成",
    "共鸣解放伤害加成", "共鸣技能伤害加成",
]


class SetConfigTab(QWidget):
    saved = Signal()  # 保存后通知外部

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._setup_ui()
        self._load_sets()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 顶部工具栏 ──
        top = QHBoxLayout()
        top.addWidget(QLabel("当前套装:"))
        self.set_combo = QComboBox()
        self.set_combo.setMinimumWidth(160)
        self.set_combo.currentTextChanged.connect(self._on_set_changed)
        top.addWidget(self.set_combo)
        top.addStretch()

        for text, slot in [("导出", self._export), ("导入", self._import), ("恢复默认", self._reset)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            top.addWidget(btn)

        layout.addLayout(top)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # ── 表格 ──
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["有效", "词条", "权重"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 80)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(ALL_STATS))

        for row, name in enumerate(ALL_STATS):
            cb = QCheckBox()
            cb.stateChanged.connect(lambda s, r=row: self._on_check(r, s))
            self.table.setCellWidget(row, 0, cb)

            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, item)

            spin = QDoubleSpinBox()
            spin.setRange(0, 10)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.valueChanged.connect(lambda v, r=row: self._on_weight(r, v))
            self.table.setCellWidget(row, 2, spin)

        layout.addWidget(self.table, 1)

        # ── 底部 ──
        bot = QHBoxLayout()
        save_btn = QPushButton("保存当前套装")
        save_btn.clicked.connect(self._save)
        bot.addWidget(save_btn)
        bot.addStretch()
        bot.addWidget(QLabel("JSON: " + TEMPLATE_PATH))
        layout.addLayout(bot)

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
        self._loading = False

    # ── UI → 数据 ──
    def _on_check(self, row, state):
        if self._loading:
            return
        spin = self.table.cellWidget(row, 2)
        if state == Qt.Checked and spin.value() == 0:
            spin.setValue(1.0)
        elif state == Qt.Unchecked:
            spin.setValue(0.0)

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
            v = round(self.table.cellWidget(row, 2).value(), 1)
            if v > 0:
                stats[name] = v
        return stats

    def _save(self):
        name = self.set_combo.currentText()
        if not name:
            return
        data = self._read()
        data["sets"][name] = self._collect()
        self._write(data)
        self.saved.emit()

    # ── 导入/导出 ──
    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出", "echo_set_templates.json", "JSON (*.json)")
        if p:
            shutil.copy(TEMPLATE_PATH, p)

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入", "", "JSON (*.json)")
        if not p:
            return
        try:
            json.load(open(p, "r"))
        except Exception as e:
            QMessageBox.warning(self, "错误", f"JSON 格式错误: {e}")
            return
        if QMessageBox.question(self, "确认", f"替换当前模板?\n{p}") != QMessageBox.Yes:
            return
        if os.path.exists(TEMPLATE_PATH):
            shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")
        shutil.copy(p, TEMPLATE_PATH)
        self._load_sets()
        self.saved.emit()

    def _reset(self):
        if QMessageBox.question(self, "确认", "恢复默认模板?") != QMessageBox.Yes:
            return
        if os.path.exists(TEMPLATE_PATH):
            shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")
        self._load_sets()
        self.saved.emit()
