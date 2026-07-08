"""
开发者工具 — Run Code + Templates + Script。
"""
import os
import subprocess
import sys
import io

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTextEdit, QLabel, QFrame, QTabWidget,
                               QListWidget, QListWidgetItem)
from PySide6.QtCore import Qt, Signal, QObject

from ok import og


class _StdoutRedirect(QObject):
    """捕获 stdout/stderr 到信号。"""
    text_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._buffer = io.StringIO()

    def write(self, text):
        self._buffer.write(text)
        self.text_signal.emit(text)

    def flush(self):
        pass

    def getvalue(self):
        return self._buffer.getvalue()


class DevTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        inner = QTabWidget()

        # ── Run Code ──
        inner.addTab(self._make_run_code_tab(), "Run Code")
        # ── Templates ──
        inner.addTab(self._make_templates_tab(), "Templates")

        layout.addWidget(inner)

    # ═══════ Run Code ═══════
    def _make_run_code_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("输入 Python 代码, 点击 Run 执行 (有 self=task 可用):"))

        self.code_edit = QTextEdit()
        self.code_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        self.code_edit.setPlaceholderText("# 示例:\n# task = og.executor.get_all_tasks()[0]\n# print(task.ocr(log=True))")
        layout.addWidget(self.code_edit, 1)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("▶ Run")
        run_btn.clicked.connect(self._run_code)
        btn_row.addWidget(run_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self.output_area.clear())
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setStyleSheet("font-family: Consolas, monospace; font-size: 12px; background: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.output_area, 1)

        return w

    def _run_code(self):
        code = self.code_edit.toPlainText()
        if not code.strip():
            return

        self.output_area.clear()
        redirect = _StdoutRedirect()
        redirect.text_signal.connect(self.output_area.insertPlainText)

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = redirect
        sys.stderr = redirect

        try:
            # 注入常用变量
            namespace = {
                'og': og,
                'os': os,
                'subprocess': subprocess,
            }
            try:
                tasks = og.executor.get_all_tasks()
                if tasks:
                    namespace['task'] = tasks[0]
            except Exception:
                pass

            exec(code, namespace)
            self.output_area.insertPlainText("\n--- 执行完毕 ---\n")
        except Exception as e:
            self.output_area.insertPlainText(f"\n[ERROR] {e}\n")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    # ═══════ Templates ═══════
    def _make_templates_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("模板匹配特征 — assets/coco_annotations.json"))
        layout.addWidget(QLabel("此功能需要 ok-script 原版 TemplateTab, 这里仅展示基本信息。"))

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)

        # 列出模板图片
        layout.addWidget(QLabel("模板图片列表:"))
        self.template_list = QListWidget()
        layout.addWidget(self.template_list, 1)

        # 加载
        import json
        path = os.path.join("assets", "coco_annotations.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                coco = json.load(f)
            cats = {c['id']: c['name'] for c in coco.get('categories', [])}
            images = {i['id']: i['file_name'] for i in coco.get('images', [])}
            for ann in coco.get('annotations', []):
                img_name = images.get(ann['image_id'], '?')
                cat_name = cats.get(ann['category_id'], '?')
                self.template_list.addItem(f"{cat_name} → {img_name}")
        except Exception:
            self.template_list.addItem("加载失败")

        btn_row = QHBoxLayout()
        open_btn = QPushButton("打开模板文件夹")
        open_btn.clicked.connect(lambda: subprocess.Popen(f'explorer "{os.path.join(os.getcwd(), "assets", "images")}"'))
        btn_row.addWidget(open_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w
