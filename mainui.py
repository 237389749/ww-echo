"""
自定义 UI 入口 — 基于 ok-script 的截图/OCR/键鼠能力, 自建 PySide6 界面。
"""
import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
