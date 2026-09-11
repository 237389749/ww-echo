from qfluentwidgets import FluentIcon

from ok import Logger, BaseScene

logger = Logger.get_logger(__name__)


class WWScene(BaseScene):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def reset(self):
        pass
