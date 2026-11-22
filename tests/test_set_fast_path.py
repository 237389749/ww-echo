"""「图标优先」快速套装判定 + 精确模式开关的守卫（2026-11-20）。

依据：report6 的 139 张真机面板回归 —— 图标 top-1 **99.3%**、置信闸内 **100%**（123/123），
而滚面板读「合鸣效果」明文实测 1.41s/步、139 只共 395 步 ≈ 9.3 分钟（整轮 20.2 分钟的 46%）。
所以评估默认改成「图标（固定表头）→ 环色 → 低置信才滚面板」，精确模式（总是读明文）保留为可选。
见 `tools/analysis/icon_accuracy_report.py` / `panel_scroll_time.py`。

跑法：
    python -m unittest tests.test_set_fast_path -v
"""
import glob
import os
import sys
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.echo_icon_match as M  # noqa: E402
from src.task.EnhanceEchoTask import EnhanceEchoTask  # noqa: E402


def template_path(name):
    for p in sorted(glob.glob(os.path.join(M.icons_dir(), '*.png'))):
        if os.path.splitext(os.path.basename(p))[0] == name:
            return p
    return ''


def synth_frame(tpl_path, size=(1200, 1920)):
    """把模板贴到详情面板的图标区（合成整帧，不需要游戏截图）。"""
    h, w = size
    frame = np.zeros((h, w, 3), np.uint8)
    x1, y1 = int(M.ICON_BOX[0] * w), int(M.ICON_BOX[1] * h)
    x2, y2 = int(M.ICON_BOX[2] * w), int(M.ICON_BOX[3] * h)
    patch = cv2.resize(M._template_gray(tpl_path), (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
    return frame


class TestQuickSetFromHeader(unittest.TestCase):
    """`quick_set_from_header` 是"不滚面板"的唯一入口：图标 → 环色，都不行才返回 None。"""

    def setUp(self):
        self.task = EnhanceEchoTask.__new__(EnhanceEchoTask)   # 只用纯逻辑, 不跑 __init__
        self.task.config = {'当前套装': '通用'}
        self.task._executor = SimpleNamespace(frame=np.zeros((1200, 1920, 3), np.uint8))
        self.task.log_info = lambda *a, **k: None
        self.task.log_debug = lambda *a, **k: None

    @staticmethod
    def _box(w=1920, h=1200):
        return (M.ICON_BOX[0] * w, M.ICON_BOX[1] * h, M.ICON_BOX[2] * w, M.ICON_BOX[3] * h)

    def test_icon_hit_returns_without_panel(self):
        path = template_path('轻云出月')
        if not path:
            self.skipTest('assets/echo_icons 缺失')
        self.task._executor.frame = synth_frame(path)
        # 名字候选故意给错的两套：图标可以纠正（report6 的绿熔蜥就是这个形态）
        got = self.task.quick_set_from_header('格洛犸图', None, ['长路启航之星', '雪落无声之愿'],
                                              self._box())
        self.assertEqual(got, ('轻云出月', 'icon'))

    def test_blank_frame_falls_back_to_panel(self):
        self.task._executor.frame = np.zeros((1200, 1920, 3), np.uint8)
        got = self.task.quick_set_from_header('格洛犸图', None, ['长路启航之星', '雪落无声之愿'],
                                              self._box())
        self.assertIsNone(got, msg='没有图标时必须返回 None, 让调用方去滚面板读明文')

    def test_hue_narrows_to_unique(self):
        hues = M.set_hue_map()
        names = [n for n, v in hues.items() if v is not None]
        if len(names) < 2:
            self.skipTest('模板环色不足')
        a = b = None
        for x in names:
            for y in names:
                if x != y and M.hue_group(hues[x]) != M.hue_group(hues[y]):
                    a, b = x, y
                    break
            if a:
                break
        self.assertIsNotNone(a, '模板环色没有两组不同色组?')
        self.task._executor.frame = np.zeros((1200, 1920, 3), np.uint8)    # 图标不可用
        got = self.task.quick_set_from_header('甲', (hues[a], True), [b, a], self._box())
        self.assertEqual(got, (a, 'hue'))


class TestWiring(unittest.TestCase):
    """静态接线守卫：快速路径必须在滚面板之前；精确模式必须保留旧的明文链路。"""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'src', 'task', 'EnhanceEchoTask.py'), encoding='utf-8') as f:
            cls.src = f.read()
        with open(os.path.join(ROOT, 'ui', 'run_tab.py'), encoding='utf-8') as f:
            cls.ui = f.read()

    def test_fast_path_wired_before_scroll(self):
        self.assertIn('quick = self.quick_set_from_header(', self.src)
        self.assertIn('if quick:', self.src)
        self.assertIn("self.config.get('套装精确模式')", self.src)
        self.assertIn('use_icon=True, icon_box=icon_box', self.src)      # 精确模式仍是明文→图标

    def test_ui_switch_wired(self):
        self.assertIn("task.config['套装精确模式']", self.ui)
        self.assertIn('opt_precise', self.ui)
        self.assertIn('precise_set', self.ui)                            # QSettings 持久化


if __name__ == '__main__':
    unittest.main()
