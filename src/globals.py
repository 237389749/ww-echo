from PySide6.QtCore import QObject

from ok import Logger, og

logger = Logger.get_logger(__name__)


class Globals(QObject):
    """ok-script 全局对象占位(注册于 config['my_app'])。声骸功能不需要额外全局状态。"""

    def __init__(self, exit_event):
        super().__init__()
