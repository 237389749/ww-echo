"""
关于 — 品牌 / 版本 / 诊断入口 / 免责声明 / 链接(Fluent 卡片式)。

U-17: 原来品牌卡是「HeaderCardWidget 标题 OK-Echo + 20px 大标题 + 一行版本」, 48px 头部与正文标题
重复占位、大片留白; 版本号也只有引擎版本。现在收成**一行横排**(logo + 名称 + 两行版本)并补上
**数据版本**(官方配置表 3.7.0 / 37 套 / 229 声骸)与**诊断入口**(打开日志目录 / 复制诊断信息)。
"""
import json
import os
import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, FluentIcon as FIF, HeaderCardWidget, HyperlinkLabel,
                            ImageLabel, InfoBar, InfoBarPosition, PushButton, SettingCardGroup,
                            SimpleCardWidget, SingleDirectionScrollArea, StrongBodyLabel)

from ww_engine import og

from ui.widgets import flow_row, make_scroll_transparent

GAMEDATA = os.path.join("assets", "gamedata", "echo_data.json")


def _version() -> str:
    """程序版本。`og.config` 在引擎没初始化时是 None（单测/离屏）—— 关于页不该因此崩。"""
    try:
        return (og.config or {}).get("version", "dev")
    except Exception:                                   # noqa: BLE001
        return "dev"


def gamedata_summary() -> str:
    """官方配置表版本摘要（给关于页与诊断信息用）。读不到就老实说"未知"。"""
    try:
        with open(GAMEDATA, "r", encoding="utf-8") as f:
            src = (json.load(f) or {}).get("_source") or {}
        ver = src.get("version") or "?"
        return f"数据 {ver} · {src.get('sets', '?')} 套 / {src.get('echoes', '?')} 声骸"
    except Exception:                                   # noqa: BLE001 - 关于页不该因缺文件报错
        return "数据版本未知(缺 assets/gamedata/echo_data.json)"

REPO = "https://github.com/237389749/ww-echo"
LINKS = (
    ("本项目 ww-echo", REPO),
    ("上游 ok-wuthering-waves", "https://github.com/ok-oldking/ok-wuthering-waves"),
    ("引擎 ww_engine（源自 ok-script）", "https://github.com/ok-oldking/ok-script"),
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

        scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
        scroll.setWidgetResizable(True)
        scroll.setWidget(view)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _brand_card(self) -> SimpleCardWidget:
        """品牌 + 版本: 一行横排(logo 左、文字右), 不再套 48px 卡片头(U-17)。"""
        card = SimpleCardWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)

        icon_path = os.path.join(os.getcwd(), "icon.png")
        if os.path.exists(icon_path):
            try:
                logo = ImageLabel()
                logo.setImage(icon_path)
                logo.setFixedSize(64, 64)
                logo.setBorderRadius(10)
                row.addWidget(logo, 0, Qt.AlignTop)
            except Exception:
                pass

        col = QVBoxLayout()
        col.setSpacing(4)
        name = StrongBodyLabel()
        name.setText("OK-Echo · 声骸强化 / 评估")
        ver = CaptionLabel()
        ver.setText(f"版本 {_version()} · 引擎 ww_engine · 界面 qfluentwidgets")
        data_ver = CaptionLabel()
        data_ver.setText(gamedata_summary())
        for w in (name, ver, data_ver):
            col.addWidget(w)
        col.addSpacing(6)
        # 诊断入口(U-17): 反馈问题时可直接粘版本/数据/环境, 不用手抄
        open_logs = PushButton(FIF.FOLDER, "打开日志目录")
        open_logs.clicked.connect(self._open_logs)
        copy_diag = PushButton(FIF.COPY, "复制诊断信息")
        copy_diag.clicked.connect(self._copy_diag)
        col.addWidget(flow_row([open_logs, copy_diag]))
        row.addLayout(col, 1)
        return card

    # ── 诊断入口 ──
    def _open_logs(self):
        import subprocess
        folder = os.path.join(os.getcwd(), "logs")
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')

    def _diag_text(self) -> str:
        return "\n".join([
            f"OK-Echo {_version()}",
            gamedata_summary(),
            f"Python {sys.version.split()[0]} / Qt {getattr(sys.modules.get('PySide6'), '__version__', '?')}",
            f"OS {platform.platform()}",
            f"cwd {os.getcwd()}",
        ])

    def _copy_diag(self):
        QGuiApplication.clipboard().setText(self._diag_text())
        InfoBar.success("已复制", "诊断信息已复制到剪贴板", duration=2000,
                        position=InfoBarPosition.TOP_RIGHT, parent=self)

    @staticmethod
    def _text_card(title: str, text: str) -> HeaderCardWidget:
        card = HeaderCardWidget()
        card.setTitle(title)
        card.viewLayout.setContentsMargins(24, 8, 24, 16)     # U-17: 收紧上边距, 去掉大片留白
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
        card.viewLayout.setContentsMargins(24, 6, 24, 16)
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
