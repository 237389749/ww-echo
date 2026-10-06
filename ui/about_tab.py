"""
关于 — 品牌 / 免责声明 / 链接 / 致谢(Fluent 卡片式)。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, FluentIcon as FIF, HeaderCardWidget, HyperlinkLabel,
                            ImageLabel, SingleDirectionScrollArea, TitleLabel)

from ok import og

REPO = "https://github.com/237389749/ww-echo"
LINKS = (
    ("本项目 ww-echo", REPO),
    ("上游 ok-wuthering-waves", "https://github.com/ok-oldking/ok-wuthering-waves"),
    ("框架 ok-script", "https://github.com/ok-oldking/ok-script"),
    ("界面 qfluentwidgets", "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"),
)

DISCLAIMER = (
    "本软件开源、免费, 仅供个人学习与交流使用, 请勿用于商业用途。\n"
    "通过 Windows 接口模拟用户操作(截图/OCR/键鼠), 无内存读取、无文件修改。\n"
    "游戏版本更新后数据可能滞后(套装/图标/档位), 使用前请确认数据版本; 使用本软件产生的一切后果由使用者承担。"
)


def _body(card: HeaderCardWidget) -> QVBoxLayout:
    """HeaderCardWidget 的 viewLayout 是横向的, 正文要自己套一层纵向容器。"""
    body = QWidget()
    vb = QVBoxLayout(body)
    vb.setContentsMargins(0, 0, 0, 0)
    vb.setSpacing(10)
    card.viewLayout.addWidget(body)
    card.vBoxLayout.setStretchFactor(card.view, 1)
    return vb


class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        view = QWidget()
        view.setObjectName("aboutView")
        vbox = QVBoxLayout(view)
        vbox.setContentsMargins(24, 20, 24, 24)
        vbox.setSpacing(16)

        vbox.addWidget(self._brand_card())
        vbox.addWidget(self._text_card("免责声明", DISCLAIMER))
        vbox.addWidget(self._links_card())
        vbox.addStretch(1)

        scroll = SingleDirectionScrollArea(orient=Qt.Vertical)
        scroll.setWidgetResizable(True)
        scroll.setWidget(view)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _brand_card(self) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle("OK-Echo")
        body = _body(card)
        icon_path = os.path.join(os.getcwd(), "icon.png")
        if os.path.exists(icon_path):
            try:
                logo = ImageLabel()
                logo.setImage(icon_path)
                logo.setFixedSize(84, 84)
                logo.setBorderRadius(12)
                body.addWidget(logo)
            except Exception:
                pass
        name = TitleLabel()
        name.setText("声骸强化 / 评估")
        ver = CaptionLabel()
        ver.setText(f"版本 {og.config.get('version', 'dev')} · 引擎 ok-script · 界面 qfluentwidgets")
        body.addWidget(name)
        body.addWidget(ver)
        return card

    @staticmethod
    def _text_card(title: str, text: str) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle(title)
        body = _body(card)
        lbl = CaptionLabel()
        lbl.setText(text)
        lbl.setWordWrap(True)
        body.addWidget(lbl)
        return card

    @staticmethod
    def _links_card() -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle("链接与致谢")
        body = _body(card)
        for text, url in LINKS:
            link = HyperlinkLabel()
            link.setText(text)
            link.setUrl(url)
            body.addWidget(link)
        tip = CaptionLabel()
        tip.setText("图标与配置数据来自游戏客户端(pak/binData)与官方公示, 版权归库洛游戏所有。")
        tip.setWordWrap(True)
        body.addWidget(tip)
        return card
