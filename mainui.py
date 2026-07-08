"""
自定义 UI 入口 — 基于 ok-script 的截图/OCR/键鼠能力, 自建 PySide6 界面。

阶段: 搭框架, 先跑起来一个空白窗口。
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OK-Echo")
        self.resize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        placeholder = QLabel("OK-Echo 自定义 UI\n开发中...")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("font-size: 24px; color: #888;")
        layout.addWidget(placeholder)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
