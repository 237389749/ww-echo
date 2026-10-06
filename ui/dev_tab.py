"""
开发者工具 — Run Code(已禁用) / 模板信息(Fluent 分栏卡片, 主题统一)。

说明: 自建 UI 出于安全**禁用了 exec**, 所以 Run Code 只作为"占位 + 说明"存在; 这里把它呈现清楚,
而不是留一个可编辑却执行不了的深色框。模板页展示 coco_annotations.json 的特征清单。
"""
import json
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, FluentIcon as FIF, HeaderCardWidget, InfoBar, InfoBarPosition,
                            ListWidget, PlainTextEdit, PushButton, PushSettingCard, SegmentedWidget,
                            SettingCardGroup)

RUN_CODE_HINT = (
    "出于安全考虑, 自建 UI 禁用了 exec() 执行任意代码。\n"
    "需要调试请直接改源码后用 ok-script 原版 RunCodeTab, 或在「调试工具」页跑 OCR / 截图自检。"
)


def _card_body(card: HeaderCardWidget) -> QVBoxLayout:
    """HeaderCardWidget 的 viewLayout 是横向的, 正文要自己套一层纵向容器。"""
    body = QWidget()
    vb = QVBoxLayout(body)
    vb.setContentsMargins(0, 0, 0, 0)
    vb.setSpacing(10)
    card.viewLayout.addWidget(body)
    card.vBoxLayout.setStretchFactor(card.view, 1)
    return vb


class DevTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        self.segmented = SegmentedWidget()
        self.stack = QStackedWidget()
        pages = (("code", "Run Code", self._page_code()),
                 ("templates", "模板特征", self._page_templates()))
        self._routes = [k for k, _, _ in pages]
        for key, text, page in pages:
            self.segmented.addItem(key, text)
            self.stack.addWidget(page)
        self.segmented.setCurrentItem(self._routes[0])
        self.segmented.currentItemChanged.connect(
            lambda k: self.stack.setCurrentIndex(self._routes.index(k)))
        layout.addWidget(self.segmented)
        layout.addWidget(self.stack, 1)

    # ══════════════════ Run Code ══════════════════
    def _page_code(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        card = HeaderCardWidget()
        card.setTitle("Run Code")
        body = _card_body(card)
        hint = CaptionLabel()
        hint.setText(RUN_CODE_HINT)
        hint.setWordWrap(True)
        body.addWidget(hint)

        self.code_edit = PlainTextEdit()
        self.code_edit.setPlaceholderText(
            "# 仅供查看/记录片段(不会执行)\n"
            "# task = og.executor.get_all_tasks()[0]\n"
            "# print(task.ocr(log=True))")
        self.code_edit.setMinimumHeight(150)
        body.addWidget(self.code_edit, 1)

        row = QWidget()
        btn = PushButton(FIF.PLAY, "Run(已禁用)")
        btn.clicked.connect(self._run_code)
        clear = PushButton(FIF.DELETE, "清空")
        clear.clicked.connect(lambda: self.output_area.clear())
        # 简化布局: 直接塞进两个按钮的横排容器
        from PySide6.QtWidgets import QHBoxLayout
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(btn)
        hb.addWidget(clear)
        hb.addStretch()
        body.addWidget(row)

        self.output_area = PlainTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setMinimumHeight(120)
        body.addWidget(self.output_area, 1)
        v.addWidget(card, 1)
        return page

    def _run_code(self):
        self.output_area.setPlainText(
            "Run Code 已禁用 (安全原因)。\n请使用 ok-script 原版 RunCodeTab 或直接修改源码。\n")
        InfoBar.warning("已禁用", "自建 UI 不执行任意代码; 详见本页说明", duration=3000,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ══════════════════ 模板特征 ══════════════════
    def _page_templates(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        card = HeaderCardWidget()
        card.setTitle("模板匹配特征")
        body = _card_body(card)
        caption = CaptionLabel()
        caption.setText("来源 assets/coco_annotations.json(ok-script 特征库), 图片在 assets/images/")
        caption.setWordWrap(True)
        body.addWidget(caption)

        self.template_list = ListWidget()
        body.addWidget(self.template_list, 1)
        v.addWidget(card, 1)

        open_card = PushSettingCard("打开模板文件夹", FIF.FOLDER, "assets/images",
                                    "查看特征库用到的模板图片", page)
        open_card.clicked.connect(
            lambda: subprocess.Popen(f'explorer "{os.path.join(os.getcwd(), "assets", "images")}"'))
        v.addWidget(open_card)

        # 加载(保持原有解析逻辑)
        path = os.path.join("assets", "coco_annotations.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                coco = json.load(f)
            cats = {c['id']: c['name'] for c in coco.get('categories', [])}
            images = {i['id']: i['file_name'] for i in coco.get('images', [])}
            for ann in coco.get('annotations', []):
                self.template_list.addItem(
                    f"{cats.get(ann['category_id'], '?')} → {images.get(ann['image_id'], '?')}")
        except Exception as e:                                   # noqa: BLE001
            self.template_list.addItem(f"加载失败: {e}")
        return page
