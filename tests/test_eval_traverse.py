"""评估遍历终止条件的静态守卫（不需要游戏）。

2026-11-14：改为**不识别「声骸N/3000」**，直接遍历，直到「连续两行 0 词条」或「网格为空」。
这里钉住两件事：①代码里不再有 count OCR / 步数上限；②存在 0 级尾部早停。
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


class TestEvalTraverseEnd(unittest.TestCase):

    def test_no_count_ocr(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        for token in ('read_count(', 'count_box', 'total_limit', 'anchor_ok'):
            self.assertNotIn(token, src, msg=f'评估不应再依赖声骸数量: 发现 {token}')

    def test_zero_tail_stop(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('ZERO_TAIL_STOP', src)
        self.assertIn('zero_run', src)
        self.assertIn('视为 0 级尾部', src)

    def test_empty_grid_error_has_no_anchor_hint(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('未在背包界面检测到声骸网格', src)
        self.assertNotIn('页面锚点也未识别到', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
