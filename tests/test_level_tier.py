"""`_tier_from_level` / `parse_level` / 满级但词条漏读的判定守卫。

背景(2026-11-19 用户发现): 报告 #1「共鸣回响·鸣式·虚造神型」是 **+25 满级**,
却显示「不建议强化」。根因是等级一直按**词条条数**反推(`tier = len(stats)`),
而这一只只读到 4 条(漏了 `暴击 7.5`) → 被当成 +20, 走了未满级分支。
上一轮同一只读到 5 条时是 27.29 分「达标」, 这一轮 17.29 分「不建议强化」—— 同一次 OCR 抖动
就能把结论从"毕业"翻成"别练"。

这里锁住三件事:
  ① 等级 `+NN` 从面板固定表头读, 与词条数**取大**(词条数只是下界; 读到的不能凭空丢)
  ② 等级 > 词条数 = 漏读: 记录 `stats_missing`, 判定压成「保留(词条缺失)」且**不给重铸方案**
     (少一条时 reforge_plan 会把它当空孔, 方案是错的; 也不该判"不合格"—— 漏的那条可能正好让它达标)
  ③ **不传 level 时行为完全不变**(离线重放 `--from-json` 与旧报告不受影响)

跑法(项目根目录):
    python -m unittest tests.test_level_tier -v
"""
import os
import sys
import unittest
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.task.EnhanceEchoTask import (EnhanceEchoTask, _tier_from_level,  # noqa: E402
                                      LEVEL_RE)

Box = namedtuple('Box', 'name x y width confidence')


def _task():
    t = EnhanceEchoTask.__new__(EnhanceEchoTask)    # 只要纯计算方法, 不跑 __init__
    t.config = {'当前套装': '通用'}
    return t


# 报告 #1 实际读到的 4 条(漏了 `暴击 7.5`); 套装 = 雪落无声之愿, COST 4
STATS_4 = [('共鸣效率', 8.4), ('共鸣解放伤害加成', 10.1), ('防御', 50.0), ('攻击百分比', 10.9)]
STATS_5 = STATS_4 + [('暴击', 7.5)]


class TestTierFromLevel(unittest.TestCase):

    def test_table(self):
        cases = [(25, 4, 5), (25, 5, 5), (20, 4, 4), (20, 5, 5), (15, 3, 3),
                 (10, 2, 2), (5, 1, 1), (0, 0, 0), (None, 4, 4), (None, 5, 5)]
        for level, n, want in cases:
            with self.subTest(level=level, n=n):
                self.assertEqual(_tier_from_level(level, n), want)


class TestParseLevel(unittest.TestCase):

    def test_reads_header(self):
        # 实测形态: 名字 + `+25`(conf .99) + 一个孤立 `+`(conf .74, 不匹配数字) + COST
        texts = [Box('鸣钟之龟', 996, 91, 111, 0.991),
                 Box('+25', 999, 148, 46, 0.992),
                 Box('+', 1049, 148, 23, 0.743),
                 Box('COST', 1000, 189, 57, 0.997)]
        self.assertEqual(EnhanceEchoTask.parse_level(texts), 25)

    def test_other_levels(self):
        for text, want in (('+5', 5), ('+10', 10), ('+0', 0), ('+ 25', 25)):
            with self.subTest(text=text):
                texts = [Box(text, 999, 148, 46, 0.95)]
                self.assertEqual(EnhanceEchoTask.parse_level(texts), want)

    def test_topmost_wins(self):
        texts = [Box('+20', 999, 300, 46, 0.9), Box('+25', 999, 148, 46, 0.9)]
        self.assertEqual(EnhanceEchoTask.parse_level(texts), 25)

    def test_rejects_low_confidence_and_non_levels(self):
        self.assertIsNone(EnhanceEchoTask.parse_level([]))
        self.assertIsNone(EnhanceEchoTask.parse_level([Box('+25', 999, 148, 46, 0.3)]))
        # 词条数值/主属性数值不该被当成等级(它们没有 `+`)
        self.assertIsNone(EnhanceEchoTask.parse_level([Box('10.0%', 1317, 347, 72, 0.999),
                                                       Box('150', 1300, 700, 40, 0.99)]))

    def test_regex_anchored(self):
        self.assertIsNotNone(LEVEL_RE.match('+25'))
        self.assertIsNone(LEVEL_RE.match('25'))          # 没有 `+` 不认(COST 的数字框就不能被误当等级)
        self.assertIsNone(LEVEL_RE.match('+25%'))


class TestMissingStatsGuard(unittest.TestCase):
    """等级说满级、词条却少读了 → 不许判"不合格"、不许给重铸方案。"""

    def test_maxed_with_missing_stat_is_hold(self):
        rec = _task().evaluate_one('共鸣回响・鸣式・虚造神型', STATS_4, '雪落无声之愿', 'name',
                                   level=25)
        self.assertEqual(rec['tier'], 5)
        self.assertEqual(rec['stats_missing'], 1)
        self.assertEqual(rec['level'], 25)
        self.assertEqual((rec['verdict'], rec['verdict_cn']), ('hold', '保留(词条缺失)'))
        self.assertIsNone(rec['reforge'])
        self.assertIsNone(rec['prospect'])

    def test_same_echo_with_all_five_stats_passes(self):
        rec = _task().evaluate_one('共鸣回响・鸣式・虚造神型', STATS_5, '雪落无声之愿', 'name',
                                   level=25)
        self.assertEqual(rec['tier'], 5)
        self.assertNotIn('stats_missing', rec)
        self.assertEqual(rec['verdict'], 'pass')
        self.assertGreater(rec['score'], 20)

    def test_level_absent_keeps_old_behaviour(self):
        """不传 level → 老行为(tier=词条数, 未满级分支)。离线重放没有等级字段, 必须原样。"""
        rec = _task().evaluate_one('共鸣回响・鸣式・虚造神型', STATS_4, '雪落无声之愿', 'name')
        self.assertEqual(rec['tier'], 4)
        self.assertNotIn('level', rec)
        self.assertNotIn('stats_missing', rec)
        self.assertEqual((rec['verdict'], rec['verdict_cn']), ('fail', '不建议强化'))

    def test_level_below_count_does_not_demote(self):
        """等级读成 +20(或 +10)但确实读到 4 条 → 不能被降级: 读到的词条是事实。"""
        for level in (20, 10, 0):
            with self.subTest(level=level):
                self.assertEqual(_tier_from_level(level, 4), 4)


class TestBlankPanelClassification(unittest.TestCase):
    """读到面板却一条词条没配上: 分清"真 0 级"和"这一格没读干净"。

    前提(用户口径): **列表按等级排序**, 0 级件只会在尾部 → 中途的"0 词条"基本都是没读干净。
    旧代码一律当 0 级, 于是"连续 N 格 0 词条 = 到底"在列表中间误触发(2026-11-19 只扫到 43 条)。
    """

    def test_level_says_has_stats(self):
        # +25 面板: 有主属性/等级, 却一条词条没配出来 = 读失败, 不能当 0 级
        for level in (5, 10, 20, 25):
            with self.subTest(level=level):
                self.assertFalse(EnhanceEchoTask._blank_panel_is_zero_level(
                    level, [('暴击伤害', '44.0%'), ('攻击', '150'), ('共鸣效率', '8.4')]))

    def test_plus_zero_panel_is_zero_level(self):
        # +0 面板没有主属性行: 第一行是 `持有数量：N` → 真 0 级
        self.assertTrue(EnhanceEchoTask._blank_panel_is_zero_level(
            0, [('持有数量：1', '1'), ('声骸技能', '0')]))

    def test_level_missing_falls_back_to_main_props(self):
        # 等级没读到: 有真主属性 → 至少 +5, 算失败; 没主属性 → 按 0 级
        self.assertFalse(EnhanceEchoTask._blank_panel_is_zero_level(
            None, [('暴击', '22.0%'), ('攻击', '150')]))
        self.assertTrue(EnhanceEchoTask._blank_panel_is_zero_level(
            None, [('持有数量：1', '1')]))

    def test_no_panel_at_all_is_zero_level(self):
        self.assertTrue(EnhanceEchoTask._blank_panel_is_zero_level(None, []))


if __name__ == '__main__':
    unittest.main()
