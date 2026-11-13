"""引擎侧的通知 helper（**无 QtWidgets 依赖**）。

`alert_info` / `alert_error` 只是把消息发到 `communicate.notification` 信号上（UI 层负责展示/托盘）。
真正弹 `QMessageBox` 的 `show_alert` 属应用外壳，已移到 `ww_app_shell/alert.py`
（2026-11-13 第三阶段拆分；engine 因此不再直接 import QtWidgets）。
"""

from ww_engine.gui.Communicate import communicate


def alert_info(message, tray=False, show_tab=None):
    communicate.notification.emit(message, None, False, tray, show_tab, None)


def alert_error(message, tray=False, show_tab=None):
    communicate.notification.emit(message, None, True, tray, show_tab, None)
