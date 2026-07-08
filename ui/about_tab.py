"""
关于 — 版本信息, 链接。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from ok import og


class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        logo = QLabel("OK-Echo")
        logo.setStyleSheet("font-size: 28px; font-weight: bold;")
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        ver = QLabel(f"版本: {og.config.get('version', 'dev')}")
        ver.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver)

        layout.addSpacing(12)

        desc = QLabel(
            "鸣潮声骸强化自动化工具\n"
            "基于 ok-script 框架\n\n"
            "仅供学习交流使用, 请勿用于商业用途\n"
            "使用本软件产生的一切后果由使用者承担"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(16)

        links = QLabel(
            '<a href="https://github.com/237389749/ww-echo">GitHub: 237389749/ww-echo</a><br>'
            '<a href="https://github.com/ok-oldking/ok-wuthering-waves">原始项目: ok-oldking/ok-wuthering-waves</a><br>'
            '<a href="https://github.com/ok-oldking/ok-script">框架: ok-oldking/ok-script</a>'
        )
        links.setAlignment(Qt.AlignCenter)
        links.setOpenExternalLinks(True)
        layout.addWidget(links)
