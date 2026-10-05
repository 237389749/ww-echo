"""`src/echo_stats` 档位表 ↔ 官方公示概率表的一致性断言 —— 把"运行期静默回退"变成"构建期失败"。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_stats_consistency.py

为什么要这个测试(`eval_rules.md` §7 已把"漂移是静默的"列为风险)：
`echo_stats.get_mean` 在**档位值与概率键对不上时会静默回退算术平均** —— 分数语义随之改变，
而报告里看不出来。所以这里把三件事锁死：档位集合 == 概率键集合、期望值确实来自概率、
分位可用；外加**防御百分比**那一行的取证(官方公示原文 + 真实面板)。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import echo_stats as S  # noqa: E402


class TestTierTableConsistency(unittest.TestCase):

    def test_probability_table_covers_every_tier(self):
        probs = S._load_tier_probs()
        self.assertTrue(probs, '官方档位概率表缺失/不可用')
        for name, tiers in S._TIERS.items():
            with self.subTest(stat=name):
                self.assertIn(name, probs)
                self.assertEqual(len(probs[name]), len(tiers))
                self.assertEqual({round(v, 4) for v in probs[name]},
                                 {round(t, 4) for t in tiers})

    def test_mean_comes_from_probability_not_arithmetic(self):
        """`_expected_tier` 返回 None 会静默换成算术平均(平均档不再是 10.0 分) —— 这里禁止它发生。"""
        probs = S._load_tier_probs()
        for name, tiers in S._TIERS.items():
            with self.subTest(stat=name):
                self.assertIsNotNone(S._expected_tier(name, tiers, probs),
                                     f'{name}: 档位与概率键对不上, 会静默回退算术平均')
                self.assertNotAlmostEqual(S.get_mean(name), sum(tiers) / len(tiers), places=2,
                                          msg=f'{name}: 期望值等于算术平均, 说明概率没被用上')

    def test_tier_percentile_available_for_every_stat(self):
        for name, tiers in S._TIERS.items():
            with self.subTest(stat=name):
                top, bottom = S.tier_percentile(name, max(tiers)), S.tier_percentile(name, min(tiers))
                self.assertIsNotNone(top)
                self.assertIsNotNone(bottom)
                self.assertLess(top, bottom, '越高档分位应越小')

    def test_defense_percent_matches_official_disclosure(self):
        """★ 防御百分比: 以官方公示原文为准, 不是服务端模拟实现的取整口径。

        两条独立证据：
        1. 官方公示页(韩文 product_info, 本机保存为 `logic.htm`)「방어력 보너스」一行:
           `8.1 / 9.0 / 10.0 / 10.9 / 11.8 / 12.8 / 13.8 / 14.7`；
           全页 `9.1 / 11.0 / 11.9 / 12.9 / 14.8` 出现 **0** 次。
        2. 真实面板 18 张(`logs/eval_debug/20260911_110817`；`tools/offline_eval_report.py`
           存的是 OCR 原始值, 不吸附档位): 只出现上面那 8 个值。
        zigrika 服务端 `(std*mult+5000)//10000*10` 会多出 +0.1 的 5 个档 → 那是服务端口径。
        """
        expected = [14.7, 13.8, 12.8, 11.8, 10.9, 10.0, 9.0, 8.1]
        self.assertEqual(S._TIERS['防御百分比'], expected)
        for wrong in (14.8, 12.9, 11.9, 11.0, 9.1):
            self.assertNotIn(wrong, S._TIERS['防御百分比'], '服务端取整口径的值不能进表')
        self.assertEqual(set(S._load_tier_probs()['防御百分比']), set(expected))


if __name__ == '__main__':
    unittest.main(verbosity=2)
