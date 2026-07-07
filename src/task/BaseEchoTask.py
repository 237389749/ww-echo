"""
声骸任务轻量基类 — 仅保留 EnhanceEchoTask / ChangeEchoTask 实际使用的方法。

仅保留 EnhanceEchoTask / ChangeEchoTask 实际使用的方法:
  - click() 重写: 为 OCR 检测框设置合适的点击持续时间
  - game_lang: 从窗口标题检测游戏语言
"""

from ok import BaseTask, Logger

logger = Logger.get_logger(__name__)


class BaseEchoTask(BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key_config = self.get_global_config('Game Hotkey')
        self.scene = None

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1,
              move=False, down_time=0.01, after_sleep=0, key="left"):
        """重写点击: 屏幕坐标用 0.2s 按下时间, 无坐标(默认屏幕中心)用 0.01s。"""
        if x == -1 and y == -1:
            x = self.width_of_screen(0.5)
            y = self.height_of_screen(0.5)
            move = False
            down_time = 0.01
        else:
            down_time = 0.2
        return super().click(x, y, move_back, name, interval,
                             move=move, down_time=down_time,
                             after_sleep=after_sleep, key=key)

    @property
    def game_lang(self):
        if '鸣潮' in self.hwnd_title or self.is_browser():
            return 'zh_CN'
        elif 'Wuthering' in self.hwnd_title:
            return 'en_US'
        elif '鳴潮' in self.hwnd_title:
            return 'zh_TW'
        return 'unknown_lang'
