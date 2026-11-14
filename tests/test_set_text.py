"""详情面板「套装名文字」匹配（2026-11-14 六次：把套装从"图片识别"换成"文字 + 候选约束"）。

背景：3.x 详情面板没有套装图标（`ICON_BOX` 落到绿色「+」按钮）；网格卡片徽章只有 28px，
灰度匹配不可用、环色能解决 85%，剩下 15% 是同色环的两套（如 高天共奏之曲 / 羽落空尘之歌）。
用户实测：**详情面板的副词条区域可以下滑，往下能看到套装名文字** —— 文本信号。

这里只测纯函数（不需要游戏）：把 OCR 出来的行 → 套装名，并且优先在"声骸名给出的候选"里挑，
相当于把 37 选 1 压成 2~4 选 1。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.echo_set_templates import get_all_set_names, match_set_text  # noqa: E402

# 真机实测: 该声骸名对应的三个候选（名字兜底会错选第一个）
XIANFENG = ['不绝余音', '幽夜隐匿之帷', '隐世回光']


class TestMatchSetText(unittest.TestCase):

    def test_exact_name_line(self):
        self.assertEqual(match_set_text(['隐世回光']), ('隐世回光', 'text'))

    def test_name_inside_a_longer_line(self):
        """真实面板里是「隐世回光 2件套：…」这类整行 → 精确子串要能命中。"""
        self.assertEqual(match_set_text(['隐世回光 2件套：攻击力提升 10%'], XIANFENG),
                         ('隐世回光', 'text'))

    def test_candidates_constrain_the_choice(self):
        """整屏文本里有多个套装名时, 候选约束能挑出唯一那个。"""
        lines = ['隐世回光 2件套：攻击力提升 10%', '不绝余音 2件套：攻击力提升 10%']
        self.assertEqual(match_set_text(lines, ['隐世回光']), ('隐世回光', 'text'))

    def test_ocr_typo_falls_back_to_lcs(self):
        """OCR 掉字/错字（隐世回先）→ LCS 唯一最高分才认。"""
        name, how = match_set_text(['隐世回先 2件套'], XIANFENG)
        self.assertEqual(name, '隐世回光')
        self.assertEqual(how, 'text-lcs')

    def test_no_guess_when_tie(self):
        """两个候选同分时不猜（宁可回退其它信号）。"""
        # 两行分别命中不同候选 → 精确命中并列, 且长度相同 → 返回 None
        self.assertEqual(match_set_text(['不绝余音', '隐世回光'], ['不绝余音', '隐世回光']), (None, ''))

    def test_empty_or_noise(self):
        self.assertEqual(match_set_text([]), (None, ''))
        self.assertEqual(match_set_text(['COST 1', '+25', '生命 2280']), (None, ''))

    def test_accepts_ocr_boxes(self):
        """引擎的 Box 对象（带 .name）也要能用。"""

        class _Box:
            def __init__(self, name):
                self.name = name

        self.assertEqual(match_set_text([_Box('隐世回光')], XIANFENG), ('隐世回光', 'text'))

    def test_all_set_names_are_self_consistent(self):
        """每个套装名都能在"只有它自己"的文本里被认出来（防止名字里含全角/空格等）。"""
        for name in get_all_set_names():
            got, _ = match_set_text([name])
            self.assertEqual(got, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
