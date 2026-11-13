"""
声骸任务轻量基类 — 仅保留 EnhanceEchoTask 实际使用的方法。

  - click() 重写: 为 OCR 检测框设置合适的点击持续时间

注: ok-ww 的 `key_config`(游戏内技能键) 与 `game_lang`(按窗口标题猜语言) 已随
自动战斗/刷图能力一起移除 —— 本工具只模拟背包/详情面板里的点击与 esc/z/c。
"""

from ww_engine import BaseTask


class BaseEchoTask(BaseTask):

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
