from qfluentwidgets import FluentIcon

from ok import Logger, BaseScene

logger = Logger.get_logger(__name__)


class WWScene(BaseScene):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._echo_enhance_btn = None

    def reset(self):
        self._echo_enhance_btn = None

    def echo_enhance_btn(self, fun):
        if self._echo_enhance_btn is None:
            self._echo_enhance_btn = fun()
        return self._echo_enhance_btn
