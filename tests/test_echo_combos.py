"""`src/echo_combos.py` 单测: 组合过滤(互异 / ΣCOST≤12 / 套装只数 / 4C 归属) + 排名。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_combos.py

手工枚举口径: 名字组合数 = `C(A 名字数, 3) × C(B 名字数, 2)`(3+2) 或 `C(名字数, 5)`(5),
再乘以各名字的实例数(同名多只 = 同一只的多个词条版本, **只算 1 只套装数**)。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.echo_combos import (EchoItem, PlanRequest, candidate_pool, is_max_level, plan,   # noqa: E402
                             set_bonus_keys)

A, B = "套装A", "套装B"


def it(name, cost, set_name, **stats):
    return EchoItem(name=name, cost=cost, set_name=set_name,
                    stats=tuple((k.replace("_", ""), v) for k, v in stats.items()))


def full(name, cost, set_name, **stats):
    """满级件(= 5 词条 + 2 主属性): 契约默认只收满级件, 组合用例需要它。"""
    base = {"暴击": 6.3, "暴击伤害": 12.6, "攻击百分比": 6.4, "攻击": 30.0,
            "共鸣效率": 6.8, "重击伤害加成": 6.4}
    base.update(stats)
    return EchoItem(name=name, cost=cost, set_name=set_name,
                    stats=(("暴击", 22.0),) + tuple(base.items()),
                    main=(("暴击", 22.0),))


def req(**kw):
    """组合用例的请求: 合成件只有 1~2 条词条, 显式关掉"只用满级件"才进得了候选池。"""
    kw.setdefault("max_level_only", False)
    return PlanRequest(**kw)


class TestBonusFilter(unittest.TestCase):
    """声骸副词条的专伤按**套装模板的有效词条**过滤(3+2 取并集); 补正不受影响。"""

    def test_set_bonus_keys_from_template(self):
        self.assertEqual(set_bonus_keys(["雪落无声之愿"]), ("共鸣解放伤害加成",))
        self.assertEqual(set_bonus_keys(["长路启航之星"]), ("共鸣解放伤害加成",))
        self.assertEqual(set_bonus_keys(["息界同调之律"]), ("重击伤害加成",))
        # 3+2 = 两套并集; 模板缺失的套装 → None(不过滤)
        self.assertEqual(set_bonus_keys(["息界同调之律", "听唤语义之愿"]), ("重击伤害加成",))
        self.assertIsNone(set_bonus_keys(["不存在的套装"]))
        self.assertIsNone(set_bonus_keys([]))

    def test_all_bonus_switch_changes_score(self):
        """模板不认的专伤: 过滤后不算分, `allowed_bonus=None` 才全算。"""
        pool = [full(f"n{i}", 1, A, 共鸣解放伤害加成=8.0, 普攻伤害加成=9.0) for i in range(5)]
        off = plan(pool, req(mode="5", set_a=A, top_k=1)).combos[0]
        # 「套装A」不在模板里 → set_bonus_keys 返回 None → 不过滤(老行为)
        on = plan(pool, req(mode="5", set_a=A, top_k=1, allowed_bonus=None)).combos[0]
        self.assertAlmostEqual(off.score, on.score)
        # 显式给一个只认共解的集合 → 普攻 9 被忽略, 分数下降
        only_burst = plan(pool, req(mode="5", set_a=A, top_k=1,
                                    allowed_bonus=("共鸣解放伤害加成",))).combos[0]
        self.assertLess(only_burst.score, on.score)
        # 5 只各带 普攻 9.0 → 合计被忽略 45.0
        self.assertAlmostEqual(only_burst.panel.ignored_bonus["普攻伤害加成"], 45.0)


class TestMaxLevelFilter(unittest.TestCase):
    """默认只用满级件(5 词条); 关掉才把未满级件放进候选池。"""

    def test_default_excludes_incomplete(self):
        pool = [full("满级A", 1, A), full("满级B", 1, A), it("半成品", 1, A, 暴击=6.3)]
        self.assertTrue(is_max_level(full("x", 1, A)))
        self.assertFalse(is_max_level(it("y", 1, A, 暴击=6.3)))
        self.assertEqual([i.name for i in candidate_pool(pool, PlanRequest(mode="5", set_a=A))],
                         ["满级A", "满级B"])
        self.assertEqual([i.name for i in candidate_pool(pool, req(mode="5", set_a=A))],
                         ["满级A", "满级B", "半成品"])


class TestPoolAndValidation(unittest.TestCase):

    def test_pool_filters_set_and_cost(self):
        items = [it("a1", 4, A), it("b1", 4, B), it("c1", 4, "套装C"), it("a2", 2, A)]
        pool = candidate_pool(items, req(mode="5", set_a=A))
        self.assertEqual([i.name for i in pool], ["a1"])

    def test_requires_sets(self):
        with self.assertRaises(ValueError):
            candidate_pool([], PlanRequest(mode="5", set_a=""))
        with self.assertRaises(ValueError):
            candidate_pool([], req(mode="3+2", set_a=A, set_b=""))
        with self.assertRaises(ValueError):
            candidate_pool([], req(mode="3+2", set_a=A, set_b=A))
        with self.assertRaises(ValueError):
            candidate_pool([], req(mode="4+1", set_a=A))

    def test_same_name_inconsistent_data_raises(self):
        pool = [it("同只", 4, A), it("同只", 3, A)]
        with self.assertRaises(ValueError):
            plan(pool, req(mode="5", set_a=A))


class TestMode5Enumeration(unittest.TestCase):

    def test_name_combos_match_hand_count(self):
        costs = [4, 3, 3, 1, 1, 1]
        pool = [it(f"e{i}", c, A) for i, c in enumerate(costs)]
        res = plan(pool, req(mode="5", set_a=A, top_k=100))
        self.assertEqual((res.candidates, res.names, res.evaluated), (6, 6, 6))   # C(6,5)=6
        self.assertEqual(res.combos[0].total_cost, 12)

    def test_total_cost_cap_excludes_dear_combos(self):
        costs = [4, 4, 4, 1, 1, 1]                     # 丢一个 1C → 4+4+4+1+1 = 14 > 12
        pool = [it(f"e{i}", c, A) for i, c in enumerate(costs)]
        res = plan(pool, req(mode="5", set_a=A, top_k=100))
        self.assertEqual(res.evaluated, 3)
        self.assertTrue(all(c.total_cost <= 12 for c in res.combos))

    def test_duplicate_names_count_once_for_set(self):
        """**同名重复不计入套装数量**: 同名 3 只只是 3 个词条版本, 永远算 1 只。"""
        pool = [it("同名", 4, A, 暴击=6.3), it("同名", 4, A, 暴击=10.5), it("同名", 4, A, 暴击=8.1),
                it("e1", 3, A), it("e2", 3, A), it("e3", 1, A), it("e4", 1, A)]
        bare = {"攻击": 1000, "暴击伤害": 150.0}
        res = plan(pool, req(mode="5", set_a=A, top_k=100), bare=bare)
        self.assertEqual((res.names, res.evaluated), (5, 3))                      # 1 个名字组合 × 3 个实例
        for c in res.combos:
            self.assertEqual(c.set_counts, {A: 5})
            self.assertEqual(len({i.name for i in c.items}), 5)
        # 三个版本里暴击最高的一版必定在第一名(其余 4 只相同)
        self.assertEqual(res.combos[0].panel.crit_rate, 10.5)

    def test_never_five_of_two_sets(self):
        pool = [it(f"a{i}", 1, A) for i in range(3)] + [it(f"b{i}", 1, B) for i in range(3)]
        res = plan(pool, req(mode="5", set_a=A, top_k=100))
        self.assertTrue(all(set(c.set_counts) == {A} for c in res.combos))


class TestMode32(unittest.TestCase):

    def test_exact_three_and_two(self):
        pool = ([it(f"a{i}", 1, A) for i in range(4)] + [it(f"b{i}", 1, B) for i in range(2)])
        res = plan(pool, req(mode="3+2", set_a=A, set_b=B, top_k=100))
        self.assertEqual(res.evaluated, 4)                       # C(4,3) × C(2,2)
        for c in res.combos:
            self.assertEqual(c.set_counts, {A: 3, B: 2})

    def test_cost_cap_applies(self):
        pool = ([it("a4", 4, A), it("a3", 3, A), it("a1", 1, A)] + [it("b4", 4, B), it("b1", 1, B)])
        res = plan(pool, req(mode="3+2", set_a=A, set_b=B, top_k=100))
        self.assertEqual(res.evaluated, 0)                       # 4+3+1 + 4+1 = 13 → 无解
        pool2 = ([it("a4", 4, A), it("a3", 3, A), it("a1", 1, A)] + [it("b1", 1, B), it("b2", 1, B)])
        res2 = plan(pool2, req(mode="3+2", set_a=A, set_b=B, top_k=100))
        self.assertEqual(res2.evaluated, 1)                      # 4+3+1 + 1+1 = 10 → 1 组
        self.assertEqual(res2.combos[0].total_cost, 10)

    def test_cost4_owner(self):
        pool = ([it("a4", 4, A), it("a3", 3, A), it("a1", 1, A)] + [it("b1", 1, B), it("b2", 1, B)])
        ok = plan(pool, req(mode="3+2", set_a=A, set_b=B, cost4_owner="A", top_k=100))
        self.assertEqual(ok.evaluated, 1)
        bad = plan(pool, req(mode="3+2", set_a=A, set_b=B, cost4_owner="B", top_k=100))
        self.assertEqual(bad.evaluated, 0)                       # 唯一的 4C 属于 A → B 归属无解

    def test_two_cost4_echoes_must_both_go_to_owner(self):
        # A: a4(4)+a1+a2, B: b4(4)+b1+b2 → 3+2 必取 A 全部(含 4C a4), B 取 2 只(3 选 2)
        pool = ([it("a4", 4, A), it("a1", 1, A), it("a2", 1, A)]
                + [it("b4", 4, B), it("b1", 1, B), it("b2", 1, B)])
        r_a = plan(pool, req(mode="3+2", set_a=A, set_b=B, cost4_owner="A", top_k=100))
        self.assertEqual(r_a.evaluated, 1)          # 带 b4 的两种组合被否(其 4C 属 B)
        self.assertEqual(r_a.combos[0].total_cost, 8)
        r_b = plan(pool, req(mode="3+2", set_a=A, set_b=B, cost4_owner="B", top_k=100))
        self.assertEqual(r_b.evaluated, 0)          # A 必带 a4 → 归属 B 无解


class TestRanking(unittest.TestCase):

    def _pool(self):
        # 6 个名字(cost 4+3+1+1+1+1=11): C(6,5)=6 个名字组合, 每个组合 = 丢掉其中一只
        return [
            it("n4", 4, A, 攻击=150.0), it("n3", 3, A, 生命=580.0), it("n1a", 1, A, 攻击=60.0),
            it("n1b", 1, A, 生命=470.0), it("n1c", 1, A, 防御=50.0), it("n1d", 1, A, 共鸣效率=12.4),
        ]

    def test_topk_and_sorted(self):
        res = plan(self._pool(), req(mode="5", set_a=A, top_k=3))
        self.assertEqual(len(res.combos), 3)
        self.assertEqual([c.score for c in res.combos], sorted((c.score for c in res.combos), reverse=True))
        self.assertEqual(res.evaluated, 6)

    def test_scaling_switch_changes_best(self):
        bare = {"攻击": 1000, "生命": 20000, "防御": 800}
        atk = plan(self._pool(), req(mode="5", set_a=A, scaling="攻击", top_k=1), bare=bare)
        hp = plan(self._pool(), req(mode="5", set_a=A, scaling="生命", top_k=1), bare=bare)
        self.assertIn("n1a", [i.name for i in atk.combos[0].items])     # 攻击：固定攻击 60 那条
        self.assertIn("n1b", [i.name for i in hp.combos[0].items])      # 生命：固定生命 470 那条

    def test_should_stop_returns_partial_ranking(self):
        pool = [it(f"e{i}", 1, A) for i in range(9)]              # C(9,5) = 126 组
        res = plan(pool, req(mode="5", set_a=A, top_k=5), should_stop=lambda: True)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.evaluated, 1)                        # 第一组就查一次取消

    def test_corrections_enter_ranking(self):
        pool = [it("A4", 4, A), it("A3", 3, A), it("A1", 1, A), it("A2", 1, A), it("A5", 1, A)]
        bare = {"攻击": 1000, "暴击": 5.0, "暴击伤害": 150.0}
        flat = plan(pool, req(mode="5", set_a=A, top_k=1), bare=bare)
        boosted = plan(pool, req(mode="5", set_a=A, top_k=1), bare=bare,
                       corrections=[("重击伤害加成", 30.0, "套装 3 件套")])
        self.assertAlmostEqual(boosted.combos[0].score / flat.combos[0].score, 1.30, places=6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
