from PySide6.QtCore import QObject

from ok import Logger, og

logger = Logger.get_logger(__name__)


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()
        self.mini_map_arrow = None
        self.logged_in = False
