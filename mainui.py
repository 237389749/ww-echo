"""
OK-Echo 主入口 — 自建 PySide6 界面, ok-script 做后台引擎。
"""
import sys
import logging

from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtWidgets import QApplication

from config import config, apply_run_mode, MODE_LOCAL, MODE_CLOUD
from ok import OK, og


class LogBridge(logging.Handler, QObject):
    log_signal = Signal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        self.log_signal.emit(self.format(record))


def main():
    # 0. 应用运行模式(本地/云游戏) — 须在 OK 引擎初始化前生效
    run_mode = QSettings("OK-Echo", "OK-Echo").value("run_mode", MODE_LOCAL)
    apply_run_mode(MODE_CLOUD if run_mode == MODE_CLOUD else MODE_LOCAL)
    logging.getLogger('ok').info(f"运行模式: {'云游戏(自动锁定鸣潮窗口/前台)' if run_mode == MODE_CLOUD else '本地客户端'}")

    # 1. ok-script 后端初始化 (不创建旧 UI)
    config['debug'] = False
    config['use_gui'] = True
    ok_engine = OK(config)

    # 2. 日志桥接
    log_bridge = LogBridge()
    logging.getLogger('ok').addHandler(log_bridge)
    logging.getLogger('src').addHandler(log_bridge)
    logging.getLogger('ok').setLevel(logging.INFO)
    logging.getLogger('src').setLevel(logging.INFO)

    # 3. 自定义窗口
    from ui.main_window import MainWindow
    window = MainWindow(ok_engine, log_bridge)
    window.show()

    # 4. 启动后端引擎 (不创建旧窗口, 只启动截图/设备)
    og.app.start_controller.start()

    sys.exit(QApplication.instance().exec())


if __name__ == '__main__':
    main()
