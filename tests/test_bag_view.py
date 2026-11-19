"""开局复位(按两次 B) + 点击点夹进网格区 —— 2026-11-19 用户现场的两条要求。

背景:
  ① 背包的列表滚动位置**跨轮保留** → 上一轮停在下面, 这一轮就从中间开始扫。用户口径:
     开局按两次 B(关掉再打开), 列表自然回顶, 不用去猜"滚了多少格"。
  ② 边缘格/重试点可能落到网格框外 → 点到背包两侧或底部的"整理·筛选·培养"按钮,
     游戏会跳去别的功能界面(用户现场: "好像按错了, 进入游戏其他功能界面")。

跑法(项目根目录):
    python -m unittest tests.test_bag_view -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.task.EnhanceEchoTask import (GRID_BOX, CLICK_INSET,  # noqa: E402
                                      EnhanceEchoTask, clamp_to_grid)


class _FakeTask:
    """只要 send_key/log_info: 直接借用真类的方法, 但不跑 __init__。"""

    def __init__(self):
        self.keys = []
        self.logs = []

    def send_key(self, key, **k):
        self.keys.append((str(key), k.get('after_sleep')))

    def log_info(self, msg, notify=False):
        self.logs.append(str(msg))


class TestResetBagView(unittest.TestCase):

    def test_presses_b_twice(self):
        t = _FakeTask()
        EnhanceEchoTask.reset_bag_view(t)
        self.assertEqual([k for k, _ in t.keys], ['b', 'b'],
                         msg='两次 B = 关掉再打开, 列表回顶部')
        self.assertEqual(t.keys[0][1], t.keys[1][1], msg='两次按键都要留停稳时间')
        self.assertTrue(any('复位背包' in m for m in t.logs))

    def test_presses_override(self):
        t = _FakeTask()
        EnhanceEchoTask.reset_bag_view(t, presses=1)
        self.assertEqual([k for k, _ in t.keys], ['b'])


class TestClampToGrid(unittest.TestCase):

    def test_inside_untouched(self):
        self.assertEqual(clamp_to_grid(0.3, 0.4), (0.3, 0.4))

    def test_outside_clamped_with_inset(self):
        x0, y0, x1, y1 = GRID_BOX
        self.assertEqual(clamp_to_grid(0.0, 0.0), (x0 + CLICK_INSET, y0 + CLICK_INSET))
        self.assertEqual(clamp_to_grid(1.0, 1.0), (x1 - CLICK_INSET, y1 - CLICK_INSET))

    def test_edges_never_outside_box(self):
        """网格四角 + 极值都必须落在框内(留边), 否则会点到背包的按钮区。"""
        x0, y0, x1, y1 = GRID_BOX
        for x, y in ((x0, y0), (x1, y1), (x0 - 0.05, 0.5), (0.5, y1 + 0.05), (-1, 2)):
            cx, cy = clamp_to_grid(x, y)
            with self.subTest(x=x, y=y):
                self.assertGreaterEqual(cx, x0)
                self.assertLessEqual(cx, x1)
                self.assertGreaterEqual(cy, y0)
                self.assertLessEqual(cy, y1)


if __name__ == '__main__':
    unittest.main()
