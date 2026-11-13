"""运行模式的**分辨率口径**守卫：窗口模式（本地/云）都不设 `supported_resolution.ratio`。

为什么：`supported_resolution.ratio` 不是"校验通过与否"，而是**坐标映射的参考比例** ——
`BaseTask.out_of_ratio()` 为真时，`box_of_screen` / `click_relative` 会按
`should_width = ratio × height` 把坐标等比缩放后居中映射。
2026-11-14 真机实测：窗口 1254x889（1.41）配 `'16:9'` 时，相对 y=0.381 被算成 269px 而不是 338px
（**纵向偏上 ~69px ≈ 半行**，会点到上一行；4:3 窗口偏得更多）。窗口化运行没有黑边，
正确映射是**按帧宽高线性缩放**，因此两种模式都必须 `ratio=None`；只有"全屏且画面带黑边"才需要手动设回。

对应文档：`CLAUDE.md` 运行模式节、`docs/SESSION_2026-11-13.md` §6.5、CHANGELOG 补记 30。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import config, apply_run_mode, MODE_LOCAL, MODE_CLOUD  # noqa: E402


class TestRunModeResolution(unittest.TestCase):

    def setUp(self):
        self._windows = dict(config['windows'])
        self._ratio = config['supported_resolution']['ratio']
        self._min_size = config['supported_resolution']['min_size']

    def tearDown(self):
        config['windows'].clear()
        config['windows'].update(self._windows)
        config['supported_resolution']['ratio'] = self._ratio
        config['supported_resolution']['min_size'] = self._min_size

    def test_local_window_mode_has_no_reference_ratio(self):
        """本地窗口模式：ratio=None（线性映射），且最小尺寸不卡 1024x768。"""
        win = apply_run_mode(MODE_LOCAL)
        self.assertIsNone(config['supported_resolution']['ratio'],
                          msg="本地窗口模式不得设参考比例：非该比例的窗口会点偏（实测 1254x889 偏 ~46px）")
        self.assertEqual(win['exe'], 'Client-Win64-Shipping.exe')
        self.assertEqual(win['hwnd_class'], 'UnrealWindow')
        self.assertEqual(win['interaction'], 'PostMessage')
        min_w, min_h = config['supported_resolution']['min_size']
        self.assertLessEqual(min_w, 1024, msg="用户实际会用 1024x768 窗口")
        self.assertLessEqual(min_h, 768, msg="用户实际会用 1024x768 窗口")

    def test_cloud_mode_also_has_no_reference_ratio(self):
        """云游戏窗口尺寸不受控（16:9/16:10 都有），同样不得设参考比例。"""
        win = apply_run_mode(MODE_CLOUD)
        self.assertIsNone(config['supported_resolution']['ratio'])
        self.assertEqual(win['interaction'], 'Pynput')
        self.assertEqual(win['capture_method'], ['BitBlt_RenderFull'])
        self.assertIsNone(win['exe'])
        self.assertIsNone(win['hwnd_class'])
        self.assertIn('鸣潮', win['title'].pattern)


if __name__ == '__main__':
    unittest.main(verbosity=2)
