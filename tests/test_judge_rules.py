"""判定规则的单元测试 —— `_tier_threshold` / `_legacy_threshold` / `judge_echo` / `reforge_plan`。

把 `eval_rules.md` §3 的分类矩阵与 §2 的三道门固化为可执行断言。
用 `unittest.mock` 固定套装权重 → **不依赖 `assets/echo_set_templates.json` 与游戏数据**（模板随时会被用户改）。

跑法（项目根目录）:
    python -m unittest discover -s tests -v
    python tests/test_judge_rules.py
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.echo_stats import _TIERS, DEFAULT_WEIGHTS, get_mean          # noqa: E402
from src.task.EnhanceEchoTask import (                                # noqa: E402
    EnhanceEchoTask, _legacy_threshold, _tier_threshold)

# 测试套装(模拟"5 键套装"): 暴击 1.0 / 爆伤 0.7 / 攻% 0.5 / 共效 0.6 / 小攻 0.25, 其余词条不认
SET = {'暴击': 1.0, '暴击伤害': 0.7, '攻击百分比': 0.5, '共鸣效率': 0.6, '攻击': 0.25}
SET_NAME = '测试套'
B5 = 20.5                      # 该套装 Lv25 的基准线 B = 最低 4 键之和 ×10
WASTE = [('生命', 320), ('防御', 20), ('生命百分比', 6.4), ('防御百分比', 6.4)]   # 该套装不认的填位


def _task():
    t = EnhanceEchoTask.__new__(EnhanceEchoTask)      # 只要纯计算方法, 不跑 __init__
    t.config = {'当前套装': '通用'}
    return t


def _val(name, r):
    """按档位水平 r(相对期望值) 取该词条最接近的档位值, 用于构造测试样本。"""
    return min(_TIERS[name], key=lambda t: abs(t - get_mean(name) * r))


def _stats(names, r=1.0):
    """构造一只 5 词条的样本: 前 len(names) 条按档位水平 r, 其余填该套装不认的词条。"""
    out = [(n, _val(n, r)) for n in names]
    return out + WASTE[:5 - len(names)]


class TestThresholds(unittest.TestCase):

    def test_general_baseline_is_lowest_n_minus_1(self):
        """通用基准线 = 代表集(1.0/0.7/0.6/0.5/0.4/0.25) 最低 (n−1) 条之和 ×10。"""
        self.assertAlmostEqual(_legacy_threshold('通用', 5), 17.5)    # (0.25+0.4+0.5+0.6)×10
        self.assertAlmostEqual(_legacy_threshold('通用', 4), 11.5)    # (0.25+0.4+0.5)×10
        self.assertAlmostEqual(_legacy_threshold('通用', 3), 6.5)     # (0.25+0.4)×10
        self.assertAlmostEqual(_legacy_threshold('通用', 2), 0.0)     # tier≤2 走结构判定

    def test_set_baseline_uses_that_set_weights(self):
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            self.assertAlmostEqual(_legacy_threshold(SET_NAME, 5), B5)          # 0.25+0.5+0.6+0.7
            self.assertAlmostEqual(_legacy_threshold(SET_NAME, 3), 10 * 0.75)   # 最低 2 键: 0.25+0.5

    def test_aim_is_ten_times_sum_of_appeared_valid_weights(self):
        """达标线 A = 10 × Σ(出现且该套装认的)权重 —— 与"套装配置"无关, 只看这只出了什么。"""
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            # 只出 暴击 + 爆伤
            self.assertAlmostEqual(_tier_threshold(SET_NAME, 5, _stats(['暴击', '暴击伤害'])), 17.0)
            # 出 暴击 + 爆伤 + 攻% + 共效
            self.assertAlmostEqual(
                _tier_threshold(SET_NAME, 5, _stats(['暴击', '暴击伤害', '攻击百分比', '共鸣效率'])), 28.0)
            # 一条都不认(前 4 条全是该套装不认的词条) → A = 0
            self.assertAlmostEqual(_tier_threshold(SET_NAME, 5, WASTE), 0.0)

    def test_aim_never_takes_max_with_base(self):
        """A 返回**纯值**, 不取 max(A, B) —— A 与 B 的关系交给 judge_echo 判。"""
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            aim = _tier_threshold(SET_NAME, 5, _stats(['暴击', '暴击伤害']))    # 17.0 < B(20.5)
            self.assertAlmostEqual(aim, 17.0)
            self.assertLess(aim, B5)


class TestJudgeFiveGrades(unittest.TestCase):
    """eval_rules.md §3 的分类矩阵: k(有效条数) × 档位水平 → 判定。"""

    def _judge(self, names, score_delta=0.0, r=1.0):
        t = _task()
        stats = _stats(names, r)
        # 注意: score 必须与判定用**同一套装口径**(SET_NAME) —— 用通用口径会把填位词条也算分
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            score, _ = t.compute_weighted_score([(n, str(v)) for n, v in stats], set_name=SET_NAME)
            # 第三项 = 「建议重铸」的方案(本用例只关心 verdict)
            (v, cn), thr, _ = t.judge_echo(SET_NAME, len(stats), score + score_delta, stats)
        return v, cn, score, thr

    def test_k1_or_k2_cannot_pass_because_aim_below_base(self):
        """k≤2(Σw < B/10) → A < B → 无论多好都不能"达标"。"""
        for names in (['暴击'], ['暴击', '暴击伤害']):
            with self.subTest(names=names):
                v, cn, score, thr = self._judge(names, r=1.4)      # 全满档
                self.assertNotEqual(v, 'pass')
                self.assertLess(_tier_threshold(SET_NAME, 5, _stats(names)), B5)

    def test_k3_high_tier_passes(self):
        """k=3 且全满档 → 达标(A=23 ≥ B=20.5, score ≥ A)。"""
        v, cn, score, thr = self._judge(['暴击', '暴击伤害', '共鸣效率'], r=1.4)
        self.assertEqual(v, 'pass')

    def test_below_base_is_not_hold(self):
        """score < B → 不可能是"保留"。"""
        v, cn, score, thr = self._judge(['暴击', '暴击伤害'], r=0.7)
        self.assertNotEqual(v, 'hold')

    def test_tier_le_2_is_structural(self):
        """Lv5/Lv10 → 结构判定(首条在首核内即"建议强化"), 且文案与其余档统一为"不建议强化"。"""
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET), \
             patch('src.task.EnhanceEchoTask.get_set_core_first', return_value=['暴击']):
            (v1, cn1), _, _ = t.judge_echo(SET_NAME, 2, 12.0, [('暴击', 8.1), ('生命', 320)])
            (v2, cn2), _, _ = t.judge_echo(SET_NAME, 2, 0.0, [('生命', 320), ('防御', 20)])
        self.assertEqual((v1, cn1), ('pending', '建议强化'))
        self.assertEqual((v2, cn2), ('fail', '不建议强化'))

    def test_tier_le_2_only_checks_first_entry(self):
        """语义 1: 只看 stats[0] —— 首条无效时, 第二条是核心词条也不兜底(旧 any 语义会过)。"""
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET), \
             patch('src.task.EnhanceEchoTask.get_set_core_first', return_value=['暴击']):
            (v, cn), _, _ = t.judge_echo(SET_NAME, 2, 12.0, [('生命', 320), ('暴击', 8.7)])
        self.assertEqual((v, cn), ('fail', '不建议强化'))

    def test_low_first_gate_requires_top_tiers(self):
        """低权重首条: 权重 ≤ below 时, 必须落在该词条档位表的前 top 档。"""
        weights = dict(SET, **{'普攻伤害加成': 0.1})
        t = _task()
        low = {'below': 0.1, 'top': 2}
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=weights), \
             patch('src.task.EnhanceEchoTask.get_set_core_first', return_value=['暴击']), \
             patch('src.task.EnhanceEchoTask.get_set_low_first', return_value=low):
            top = t.judge_echo(SET_NAME, 1, 0.0, [('普攻伤害加成', 11.6)])[0][0]
            mid = t.judge_echo(SET_NAME, 1, 0.0, [('普攻伤害加成', 10.9)])[0][0]
            low_tier = t.judge_echo(SET_NAME, 1, 0.0, [('普攻伤害加成', 10.1)])[0][0]
        self.assertEqual((top, mid, low_tier), ('pending', 'pending', 'fail'))

    def test_low_first_gate_threshold_is_adjustable(self):
        """阈值可调: below=0.25 时, 0.25 的小攻击也受"前 2 档"约束; below=0.10 时它走首核。"""
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET), \
             patch('src.task.EnhanceEchoTask.get_set_core_first', return_value=['攻击']):
            with patch('src.task.EnhanceEchoTask.get_set_low_first', return_value={'below': 0.25, 'top': 2}):
                gated_low = t.judge_echo(SET_NAME, 1, 0.0, [('攻击', 40)])[0][0]
                gated_top = t.judge_echo(SET_NAME, 1, 0.0, [('攻击', 60)])[0][0]
            with patch('src.task.EnhanceEchoTask.get_set_low_first', return_value={'below': 0.10, 'top': 2}):
                ungated_low = t.judge_echo(SET_NAME, 1, 0.0, [('攻击', 40)])[0][0]
        self.assertEqual((gated_low, gated_top, ungated_low), ('fail', 'pending', 'pending'))

    def test_low_first_absent_keeps_old_behavior(self):
        """未配置 _low_first 的套装不受影响: 低权重核心词条仍按"首核"直接过。"""
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET), \
             patch('src.task.EnhanceEchoTask.get_set_core_first', return_value=['攻击']), \
             patch('src.task.EnhanceEchoTask.get_set_low_first', return_value=None):
            (v, _), _, _ = t.judge_echo(SET_NAME, 1, 0.0, [('攻击', 30)])
        self.assertEqual(v, 'pending')


class TestLowFirstRealTemplate(unittest.TestCase):
    """轻云出月的真实模板: `_low_first = {below: 0.1, top: 2}`（不 mock 模板，防配置被改坏）。"""

    def test_light_cloud_gate(self):
        from src.echo_set_templates import get_set_low_first
        if get_set_low_first('轻云出月') is None:
            self.skipTest('轻云出月未配置 _low_first')
        t = _task()
        # 0.1 占位键: 前 2 档(11.6/10.9)过; 第 3 档(10.1)不过
        v_top = t.judge_echo('轻云出月', 1, 0.0, [('普攻伤害加成', 11.6)])[0][0]
        v_low = t.judge_echo('轻云出月', 1, 0.0, [('普攻伤害加成', 10.1)])[0][0]
        # 0.25 的小攻击在首核内, 且 0.25 > below → 不受门槛约束(任意档位)
        v_core = t.judge_echo('轻云出月', 1, 0.0, [('攻击', 30)])[0][0]
        self.assertEqual((v_top, v_low, v_core), ('pending', 'fail', 'pending'))


class TestReforgePlan(unittest.TestCase):

    def test_none_when_fewer_than_two_stats(self):
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            self.assertIsNone(t.reforge_plan(SET_NAME, [('暴击', 8.1)]))
            self.assertIsNone(t.reforge_plan(SET_NAME, []))

    def test_plan_meets_probability_threshold_and_cost(self):
        """返回的方案必须满足: 达标概率 ≥ REFORGE_MIN_PROB; 成本 = max(1, L−1) × 30。"""
        t = _task()
        stats = _stats(['暴击', '暴击伤害'], r=1.4)            # 锁住双暴、还剩 3 条填位
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            plan = t.reforge_plan(SET_NAME, stats)
        if plan is None:
            self.skipTest('该样本无满足概率阈值的方案(阈值/权重调整后可能变化)')
        self.assertGreaterEqual(plan['p_pass'], EnhanceEchoTask.REFORGE_MIN_PROB)
        self.assertEqual(plan['cost'], max(1, len(plan['lock']) - 1) * EnhanceEchoTask.REFORGE_PRICE)
        self.assertEqual(plan['units'], max(1, len(plan['lock']) - 1))
        self.assertEqual(plan['refresh'], 5 - len(plan['lock']))
        self.assertLessEqual(len(plan['lock']), EnhanceEchoTask.REFORGE_LOCK_MAX)
        # 期望频整器 = units / p_pass(几何近似), 只做展示; p_pass 存的是 3 位小数, 用 delta 容错
        self.assertGreaterEqual(plan['expected_units'], plan['units'])
        self.assertAlmostEqual(plan['expected_units'] * plan['p_pass'], plan['units'], delta=0.02)
        self.assertAlmostEqual(plan['expected_cost'] * plan['p_pass'], plan['cost'], delta=0.02 * EnhanceEchoTask.REFORGE_PRICE / plan['units'])

    def test_locking_low_weight_entries_is_rejected(self):
        """① 代数粗筛: "锁低权重词条 + 刷 4 条" 不可行(A_after 站不住) → 方案里不会锁权重 0 的词条。"""
        t = _task()
        stats = [('生命', 320), ('防御', 20), ('暴击', 8.1), ('暴击伤害', 15.0), ('共鸣效率', 10.0)]
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            plan = t.reforge_plan(SET_NAME, stats)
        if plan is None:
            self.skipTest('无可行方案')
        for name in plan['lock']:
            self.assertGreater(SET.get(name, 0.0), 0.0, f'锁定了该套装不认的词条: {name}')

    def test_probability_is_below_expected_heuristic(self):
        """③ 概率门严于"期望"(r̄ ≥ 1.0): 通过粗筛的方案实际概率可能低于 50%, 被概率门挡掉。"""
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            low = t.REFORGE_MIN_PROB
            t.REFORGE_MIN_PROB = 0.0                     # 放开概率门, 观察粗筛通过者的真实概率
            try:
                plans = []
                for r in (0.7, 1.0, 1.4):
                    for names in (['暴击', '暴击伤害'], ['共鸣效率', '攻击'], ['暴击', '攻击百分比']):
                        p = t.reforge_plan(SET_NAME, _stats(names, r))
                        if p:
                            plans.append(p['p_pass'])
            finally:
                t.REFORGE_MIN_PROB = low
        self.assertTrue(plans, '粗筛应至少通过一个方案(否则该用例无意义)')
        self.assertTrue(all(p <= 1.0 for p in plans))


class TestEnchantProspect(unittest.TestCase):
    """未满级前瞻: Lv15/Lv20 用**满级**保留线 B(5) 判"继续开完能不能留"。"""

    def test_none_when_already_full_level(self):
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            self.assertIsNone(t.enchant_prospect(SET_NAME, 5, _stats(['暴击', '暴击伤害', '攻击百分比'])))

    @staticmethod
    def _partial(names, r=1.0):
        """未满级样本: **只有已开的 len(names) 条**(不要补满 5 条, 否则 need=0)。"""
        return [(n, _val(n, r)) for n in names]

    def test_probability_in_range(self):
        t = _task()
        for names in (['暴击'], ['暴击', '暴击伤害'], ['暴击', '暴击伤害', '攻击百分比']):
            with self.subTest(names=names), patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
                p = t.enchant_prospect(SET_NAME, len(names), self._partial(names, r=1.0))
                self.assertIsNotNone(p)
                self.assertGreaterEqual(p, 0.0)
                self.assertLessEqual(p, 1.0)

    def test_high_current_score_is_near_certain(self):
        t = _task()
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            hi = t.enchant_prospect(SET_NAME, 4, self._partial(['暴击', '暴击伤害', '攻击百分比', '共鸣效率'], r=1.4))
            lo = t.enchant_prospect(SET_NAME, 4, self._partial(['暴击'], r=0.7))
        self.assertGreater(hi, lo)

    def test_full_baseline_shortcut_beats_tier_level_check(self):
        """已过满级保留线 → 直接"建议强化"(不因"现有档位未达平均档"被误杀)。"""
        t = _task()
        stats = self._partial(['暴击', '生命', '防御', '生命百分比'], r=1.0)   # 只有 1 条有效 → A(4)=10
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            b5 = _legacy_threshold(SET_NAME, 5)
            (v, cn), _, _ = t.judge_echo(SET_NAME, 4, b5 + 1.0, stats)
        self.assertEqual((v, cn), ('pending', '建议强化'))

    def test_needs_both_prospect_and_tier_level(self):
        """未过满级线 且 前瞻/档位不达标 → 不建议强化。"""
        t = _task()
        stats = self._partial(['暴击', '生命', '防御', '生命百分比'], r=0.7)
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            b5 = _legacy_threshold(SET_NAME, 5)
            (v, cn), _, _ = t.judge_echo(SET_NAME, 4, b5 - 2.0, stats)
        self.assertEqual((v, cn), ('fail', '不建议强化'))

    def test_below_full_baseline_needs_prospect_to_stay_pending(self):
        """未过满级保留线时: 前瞻达阈值 → 待强化; 否则 → 不合格。"""
        t = _task()
        stats = self._partial(['暴击', '生命', '防御', '生命百分比'], r=1.0)   # Lv20 样本, 肯定够不到满级线
        with patch('src.task.EnhanceEchoTask.get_set_weights', return_value=SET):
            p = t.enchant_prospect(SET_NAME, 4, stats)
            (v, cn), thr, _ = t.judge_echo(SET_NAME, 4, 5.0, stats)
            b5 = _legacy_threshold(SET_NAME, 5)      # 必须在 patch 块内取(该套装是 mock 的)
        self.assertEqual(v, 'pending' if (p or 0) >= EnhanceEchoTask.ENCHANT_MIN_PROB else 'fail')
        self.assertEqual(thr, b5)                    # 未满级返回的是**满级**保留线


if __name__ == '__main__':
    unittest.main(verbosity=2)
