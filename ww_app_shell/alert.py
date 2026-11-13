"""`show_alert`：QtWidgets 模态框（应用外壳的一部分）。

引擎侧只需要“发通知”的 `alert_info/alert_error`（纯 `communicate` 信号，无 QtWidgets），
它们留在 `ww_engine/gui/util/Alert.py`；真正弹 `QMessageBox` 的代码放这里，避免 engine 依赖 QtWidgets。
"""

from PySide6.QtWidgets import QMessageBox


def show_alert(title, message):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)

    from ww_engine.locator import og
    msg.setWindowIcon(og.app.icon)

    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec()
