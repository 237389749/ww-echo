"""`tools/analysis/replay_panel_scroll.py` 的重放逻辑守卫。

重放的全部意义是"**离线跑一遍就能代表线上**"，所以这里锁住它与线上同一套判据：
  ① 套装名**独占一行**（或已见到「合鸣效果」标题）才算；
  ② 名字只出现在长行里、又没见标题 → 不能用名字硬认（会误判技能描述里的偶然命中）；
  ③ 名字读不到时走**效果原文**反查；
  ④ 都没读到 → `(None, '', -1, '')`，由调用方回退环色/名字。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools', 'analysis'))

import replay_panel_scroll as rp  # noqa: E402
from src.echo_set_templates import set_effect_texts  # noqa: E402

CANDS = ['不绝余音', '幽夜隐匿之帷', '隐世回光']


def _step(i, *lines):
    return {'kind': 'step', 'tag': 't', 'step': i, 'notches': 8 * (i + 1),
            'texts': [{'name': n, 'x': 10, 'y': 20 * k, 'w': 80, 'h': 18, 'conf': 0.99}
                      for k, n in enumerate(lines)]}


class TestReplay(unittest.TestCase):

    def test_name_own_line(self):
        steps = [_step(0, '声骸技能', '造成伤害'),
                 _step(1, '合鸣效果', '隐世回光', '治疗效果提升10%')]
        self.assertEqual(rp.replay(steps, CANDS)[:3], ('隐世回光', 'text', 1))

    def test_name_inside_long_line_needs_heading(self):
        """名字只在一行长文本里、也没见到标题 → 不能认（技能描述里也可能出现套装名）。"""
        steps = [_step(0, '隐世回光 已装备于该声骸')]
        self.assertEqual(rp.replay(steps, CANDS)[:3], (None, '', -1))

    def test_heading_then_name_in_line(self):
        steps = [_step(0, '合鸣效果'), _step(1, '隐世回光 2件套: 治疗效果提升10%')]
        self.assertEqual(rp.replay(steps, CANDS)[:3], ('隐世回光', 'text', 1))

    def test_effect_text_fallback(self):
        """面板上只有效果原文（没有套装名行）→ 走 match_set_effect。"""
        eff = ' '.join(set_effect_texts('隐世回光'))
        steps = [_step(0, '合鸣效果'), _step(1, eff)]
        name, src, step, _ = rp.replay(steps, ['隐世回光'])
        self.assertEqual((name, src, step), ('隐世回光', 'effect', 1))

    def test_nothing(self):
        steps = [_step(0, '声骸技能', '造成伤害'), _step(1, '冷却时间 15 秒')]
        self.assertEqual(rp.replay(steps, CANDS)[:3], (None, '', -1))

    def test_empty_steps(self):
        self.assertEqual(rp.replay([], CANDS)[:3], (None, '', -1))

    def test_open_candidates_when_name_unknown(self):
        """名字没认出来（候选为空）时放开到 37 套 —— 与线上 `match_set_text(texts)` 一致。"""
        steps = [_step(0, '合鸣效果'), _step(1, '雪落无声之愿', '暴击伤害提升10%')]
        self.assertEqual(rp.replay(steps, [])[:3], ('雪落无声之愿', 'text', 1))


if __name__ == '__main__':
    unittest.main()
