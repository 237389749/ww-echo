"""
自定义 UI 入口 — ok-script 做引擎, PySide6 自建界面。
"""
import sys
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from config import config
from ok import OK, og


class LogBridge(logging.Handler, QObject):
    """将 ok-script 的 log 转发到 UI。"""
    log_signal = Signal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        ))

    def emit(self, record):
        self.log_signal.emit(self.format(record))


def main():
    # 1. ok-script 初始化 (内部创建 QApplication)
    config['debug'] = True
    config['use_gui'] = True
    ok_engine = OK(config)

    # 2. 复用 ok-script 的 QApplication
    app = QApplication.instance()

    # 3. 日志桥接
    log_bridge = LogBridge()
    logging.getLogger('ok').addHandler(log_bridge)
    logging.getLogger('src').addHandler(log_bridge)
    logging.getLogger('ok').setLevel(logging.INFO)
    logging.getLogger('src').setLevel(logging.INFO)

    # 4. 自定义窗口
    from ui.main_window import MainWindow
    window = MainWindow(ok_engine, log_bridge)
    window.show()

    # 5. 启动 ok-script (显示原窗口 + 启动截图)
    ok_engine.start()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
