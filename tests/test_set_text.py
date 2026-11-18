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

from src.echo_set_templates import (get_all_set_names, match_set_effect,  # noqa: E402
                                    match_set_text, set_effect_texts)

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


class TestMatchSetEffect(unittest.TestCase):
    """面板滑到底只有**合鸣效果描述**（没有套装名），用效果文本反查套装。"""

    def test_exact_effect_text(self):
        text = ' '.join(set_effect_texts('隐世回光'))
        self.assertTrue(text)
        self.assertEqual(match_set_effect([text], XIANFENG)[0], '隐世回光')

    def test_survives_ocr_char_loss(self):
        import random
        rng = random.Random(1)
        text = ' '.join(set_effect_texts('隐世回光'))
        noisy = ''.join(ch for ch in text if rng.random() > 0.15)   # 掉 15% 字符
        self.assertEqual(match_set_effect([noisy], XIANFENG)[0], '隐世回光')

    def test_works_without_candidates(self):
        text = ' '.join(set_effect_texts('高天共奏之曲'))
        self.assertEqual(match_set_effect([text])[0], '高天共奏之曲')

    def test_wrong_candidates_do_not_force_a_guess(self):
        """喂进来的文本属于候选之外的套装 → 必须不猜（交给环色/名字）。"""
        text = ' '.join(set_effect_texts('隐世回光'))
        self.assertIsNone(match_set_effect([text], ['不绝余音', '幽夜隐匿之帷'])[0])

    def test_empty_and_noise(self):
        self.assertEqual(match_set_effect([''])[0], None)
        self.assertEqual(match_set_effect(['+25', 'COST 1', '生命 2280'])[0], None)


class TestEvalWiring(unittest.TestCase):
    """评估循环必须把「合鸣效果」文本信号接进 resolve_set_name（否则新 UI 下又退化成猜名字）。"""

    def test_read_set_by_effect_is_wired(self):
        path = os.path.join(ROOT, 'src', 'task', 'EnhanceEchoTask.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('read_set_by_effect(', src)
        self.assertIn('match_set_effect(texts, cands)', src)
        self.assertIn('resolve_set_name(echo_name, badge, effect_set', src)

    def test_panel_name_source_is_propagated(self):
        """读到套装名明文时 `set_src` 必须是 `text`（不是一律 `effect`）。

        2026-11-19 发现：`match_set_text` 的命中方式（text/text-lcs/all）在 `read_set_by_effect`
        里被丢掉，`resolve_set_name` 一律返回 'effect' → 报告/日志里**永远出不了** `set_src=text`，
        验收条「text 占多数」无从判断，报告悬停也说不清是"读到名字"还是"猜的效果原文"。
        """
        path = os.path.join(ROOT, 'src', 'task', 'EnhanceEchoTask.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("best = (named, 1.0, 0.0, 'text')", src)
        self.assertIn("best = (cand, s1, s2, 'effect')", src)
        self.assertIn('effect_set, _s1, _s2, effect_src = read_set_by_effect('
                      'cand_list)', src)

    def test_resolver_returns_panel_source(self):
        """`resolve_set_name(..., effect_src='text')` 原样回传，缺省仍回落 'effect'。"""
        from src.echo_set_templates import get_sets_by_echo
        from src.task.EnhanceEchoTask import EnhanceEchoTask       # 需要 ww_engine 依赖
        task = EnhanceEchoTask.__new__(EnhanceEchoTask)            # 只调纯函数, 不初始化引擎
        task.config = {'当前套装': '通用'}
        task.log_debug = lambda *a, **k: None
        name = '无归的谬误'
        self.assertIn('隐世回光', get_sets_by_echo(name))          # 前提: 目标是名字候选之一
        self.assertEqual(task.resolve_set_name(name, None, '隐世回光', 'text'),
                         ('隐世回光', 'text'))
        self.assertEqual(task.resolve_set_name(name, None, '隐世回光'),
                         ('隐世回光', 'effect'))


class TestEffectStructure(unittest.TestCase):
    """官方「合鸣效果」只有两种形态（用户口径，2026-11-18）：

    - 2+5 件套：两条效果 → 面板里**套装名出现两次**
    - 单条目（1 件或 3 件）：一条效果 → **只出现一次**

    所以"靠套装名定位"不能假设出现次数；一次命中就够，但要求它**独占一行**。
    """

    def test_each_set_has_one_or_two_effect_entries(self):
        counts = {}
        for name in get_all_set_names():
            counts[name] = len(set_effect_texts(name))
        self.assertTrue(all(n in (1, 2) for n in counts.values()),
                        msg=f'出现非 1/2 条的套装: {[(k, v) for k, v in counts.items() if v not in (1, 2)]}')
        self.assertGreaterEqual(sum(1 for n in counts.values() if n == 2), 1, msg='应有 2+5 件套')


if __name__ == '__main__':
    unittest.main(verbosity=2)
