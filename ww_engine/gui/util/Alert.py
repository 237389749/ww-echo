from ww_engine.gui.Communicate import communicate


def show_alert(title, message):
    # QMessageBox 是 QtWidgets(重)；只在真要弹框时导入，让 alert_info/alert_error 保持 QtCore 级
    from PySide6.QtWidgets import QMessageBox

    # Create a QMessageBox
    msg = QMessageBox()

    # Set the title and message
    msg.setWindowTitle(title)
    msg.setText(message)

    from ww_engine import og
    msg.setWindowIcon(og.app.icon)

    # Add a confirm button
    msg.setStandardButtons(QMessageBox.Ok)

    # Show the message box
    msg.exec()


def alert_info(message, tray=False, show_tab=None):
    communicate.notification.emit(message, None, False, tray, show_tab, None)


def alert_error(message, tray=False, show_tab=None):
    communicate.notification.emit(message, None, True, tray, show_tab, None)
