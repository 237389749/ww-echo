"""套装徽章环色消歧（2026-11-14 二次，新 UI 下唯一的套装信号）。

背景：新版 UI(3.x) 详情面板不再显示套装图标 —— `ICON_BOX` 落到绿色「+」按钮上，
实测 155 条评估记录 **icon 命中 0 次**，套装全部来自"名字候选取首个"，于是
`先锋幼岩`(候选 不绝余音/幽夜隐匿之帷/隐世回光) 被错判成 `不绝余音`(实际 `隐世回光`)。

网格卡片**左下角 28px 徽章**是仅存的套装信号：灰度 ZNCC 在这么小的图上不可用(0.2~0.3)，
但**环色**稳定 —— 37 个模板聚成 8 个色组 + 无彩色组，可过滤名字候选。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - 无 cv2 的环境跳过
    cv2 = None
    np = None


@unittest.skipUnless(cv2 is not None, '需要 cv2')
class TestSetHueFilter(unittest.TestCase):

    def test_user_case_xianfeng_youyan(self):
        """真机实测用例: 三个候选色环互不相同 → 环色唯一定位 `隐世回光`。

        名字兜底会取声明顺序首个(不绝余音) —— 这正是用户报的那条错误(报告 #129)。
        """
        from src.echo_icon_match import filter_by_set_hue, set_hue_map
        cands = ['不绝余音', '幽夜隐匿之帷', '隐世回光']
        hue = set_hue_map()['隐世回光']
        self.assertIsNotNone(hue)
        self.assertEqual(filter_by_set_hue(cands, hue), ['隐世回光'])

    def test_candidates_are_distinct_hue_groups(self):
        from src.echo_icon_match import hue_group, set_hue_map
        hues = set_hue_map()
        groups = {hue_group(hues[c]) for c in ('不绝余音', '幽夜隐匿之帷', '隐世回光')}
        self.assertEqual(len(groups), 3, msg=f'三个候选应在不同色组: {groups}')

    def test_unreadable_badge_does_not_drop_candidates(self):
        """环色读不到(ok=False)时必须**原样返回** —— 不能因为读失败而丢候选。"""
        from src.echo_icon_match import filter_by_set_hue
        cands = ['不绝余音', '幽夜隐匿之帷', '隐世回光']
        self.assertEqual(filter_by_set_hue(cands, None, ok=False), cands)

    def test_no_match_falls_back_to_all(self):
        """环色与所有候选都不沾边(读错/新套装)时也不能丢候选。"""
        from src.echo_icon_match import filter_by_set_hue
        cands = ['不绝余音', '幽夜隐匿之帷']
        self.assertEqual(filter_by_set_hue(cands, 60.0, ok=True), cands)

    def test_single_candidate_untouched(self):
        from src.echo_icon_match import filter_by_set_hue
        self.assertEqual(filter_by_set_hue(['隐世回光'], 41.0), ['隐世回光'])


@unittest.skipUnless(cv2 is not None, '需要 cv2')
class TestBadgeHue(unittest.TestCase):
    """从帧上截圆形徽章读环色：彩色环 → hue；灰/白环 → (None, True)；越界 → ok=False。"""

    @staticmethod
    def _badge(bgr, size=40, r=14):
        img = np.full((size, size, 3), 25, np.uint8)
        c = size // 2
        cv2.circle(img, (c, c), r, bgr, 3)          # 只画环，内部留暗底
        return img

    def test_green_ring(self):
        from src.echo_icon_match import badge_hue
        hue, ok = badge_hue(self._badge((0, 200, 0)), 20, 20, 14)
        self.assertTrue(ok)
        self.assertAlmostEqual(hue, 60.0, delta=6.0)

    def test_gray_ring_is_achromatic(self):
        from src.echo_icon_match import badge_hue
        hue, ok = badge_hue(self._badge((150, 150, 150)), 20, 20, 14)
        self.assertTrue(ok)
        self.assertIsNone(hue)

    def test_out_of_frame_is_not_readable(self):
        from src.echo_icon_match import badge_hue
        _, ok = badge_hue(self._badge((0, 200, 0)), 2, 2, 14)
        self.assertFalse(ok)


class TestEvalWiring(unittest.TestCase):
    """评估循环必须把徽章环色传给 resolve_set_name（否则新 UI 下又退化成纯名字猜测）。"""

    def test_eval_passes_badge_hue(self):
        path = os.path.join(ROOT, 'src', 'task', 'EnhanceEchoTask.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('badge_hue_at(', src)
        self.assertIn('resolve_set_name(echo_name, badge_hue_at(', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
