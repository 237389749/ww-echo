"""`src/echo_panel.py` 单测: 面板聚合(calculator 口径) + 加成区拆分 + 伤害公式。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_panel.py

口径依据: `panel_plan.md` 采用 wuwa-calculator 的分区与公式, 其「共鸣者基础属性」分区原文是
`基础值 × (1 + 百分比提升) + 固定值；攻击额外包含武器基础攻击`(源码里作为 formula 字符串) ——
**固定值在括号外**, 本测试用这个形状做手算锚点。契约里的样例(仇远 3+2: 重击+30 / 声骸技能+16 /
气动+10 → 专伤 46、属伤 10)也在这里钉住。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.echo_panel import (BASE_KEYS, ELEMENT_KEYS, SPECIALTY_KEYS, Correction,          # noqa: E402
                            DerivedBonus, SPECIALTY_ALIASES, aggregate, damage, defense_zone,
                            is_bonus_key, normalize_bonus_key, resist_zone)
from src.echo_set_templates import load_gamedata                                    # noqa: E402


class TestPanelAggregate(unittest.TestCase):

    def test_flat_is_outside_percent(self):
        """攻击 = 基础 × (1+百分比) + 固定: 固定值**不吃**百分比(calculator 口径)。"""
        p = aggregate(
            {"攻击": 1000, "暴击": 5.0, "暴击伤害": 150.0},
            corrections=[("攻击百分比", 40.0, "武器副属性"), ("攻击", 100.0, "天赋")],
            echo_stats=[("攻击", 150.0), ("攻击百分比", 10.0)],
        )
        # 1000 × 1.50 + (100+150) = 1750 (若固定值吃百分比会得到 1875)
        self.assertAlmostEqual(p.scaling_total("攻击"), 1750.0)
        self.assertEqual(p.base["攻击"], 1000.0)
        self.assertEqual(p.flat["攻击"], 250.0)
        self.assertEqual(p.pct["攻击"], 50.0)

    def test_life_and_def_same_shape(self):
        p = aggregate({"生命": 20000, "防御": 800},
                      corrections=[("生命百分比", 20.0), ("防御百分比", 10.0)],
                      echo_stats=[("生命", 470.0), ("防御", 50.0)])
        self.assertAlmostEqual(p.scaling_total("生命"), 20000 * 1.2 + 470)
        self.assertAlmostEqual(p.scaling_total("防御"), 800 * 1.1 + 50)

    def test_correction_dataclass_and_tuple_are_equivalent(self):
        a = aggregate({"攻击": 500}, corrections=[Correction("攻击百分比", 12.5, "套装 3 件套")])
        b = aggregate({"攻击": 500}, corrections=[("攻击百分比", 12.5)])
        self.assertEqual(a.pct, b.pct)

    def test_bonus_split_sample(self):
        """契约样例: 重击 +30(专伤) / 声骸技能 +16(专伤) / 气动 +10(属伤) → 专伤合计 46、属伤 10。"""
        p = aggregate({"攻击": 1000},
                      corrections=[("重击伤害加成", 30.0, "套装 3 件套"),
                                   ("声骸技能伤害加成", 16.0, "套装 2 件套(4%×4层)"),
                                   ("气动伤害加成", 10.0, "天赋")])
        split = p.bonus_split()
        self.assertAlmostEqual(split["专伤"], 46.0)
        self.assertAlmostEqual(split["属伤"], 10.0)
        self.assertAlmostEqual(split["通用"], 0.0)
        self.assertAlmostEqual(p.bonus_zone(), 56.0)

    def test_energy_and_heal_not_in_bonus(self):
        p = aggregate({"共鸣效率": 20.0, "治疗效果加成": 26.4}, echo_stats=[("共鸣效率", 10.0)])
        self.assertAlmostEqual(p.energy, 30.0)
        self.assertAlmostEqual(p.heal, 26.4)
        self.assertEqual(p.bonus_zone(), 0.0)

    def test_unknown_key_is_reported_not_swallowed(self):
        p = aggregate({"X攻击": 1.0, "攻击": 100.0})
        self.assertEqual(p.unknown, ["X攻击"])
        self.assertAlmostEqual(p.scaling_total("攻击"), 100.0)

    def test_allowed_bonus_filters_echo_substats_only(self):
        """`allowed_bonus`: **声骸副词条**里不属于有效词条的专伤不计(补正一律计入)。

        实测动机: 雪落无声之愿的有效词条里专伤只有「共鸣解放伤害加成」, 刷到的
        普攻/重击副词条等于白给 —— 无差别相加会把它们当收益(用户 2026-10-09 指出)。
        """
        p = aggregate({"攻击": 1000},
                      corrections=[("普攻伤害加成", 12.0, "队伍增伤")],
                      echo_stats=[("共鸣解放伤害加成", 20.0), ("普攻伤害加成", 8.6),
                                  ("重击伤害加成", 7.1), ("热熔伤害加成", 30.0)],
                      allowed_bonus=("共鸣解放伤害加成",))
        self.assertAlmostEqual(p.bonus.get("共鸣解放伤害加成", 0), 20.0)
        self.assertAlmostEqual(p.bonus.get("普攻伤害加成", 0), 12.0)      # 补正保留
        self.assertNotIn("重击伤害加成", p.bonus)
        self.assertAlmostEqual(p.ignored_bonus["普攻伤害加成"], 8.6)
        self.assertAlmostEqual(p.ignored_bonus["重击伤害加成"], 7.1)
        self.assertAlmostEqual(p.bonus_zone(), 20 + 12 + 30)             # 属伤 30 不受过滤
        # **不能被挡的键**: 基础/百分比/双暴/共效都不是"专伤"
        # (曾少写一层 is_bonus_key → 它们全被挡掉, 面板只剩裸值: 实测踩过)
        q = aggregate({"攻击": 1000},
                      echo_stats=[("攻击百分比", 9.4), ("暴击", 6.9), ("共鸣效率", 10.0),
                                  ("普攻伤害加成", 8.6)],
                      allowed_bonus=("共鸣解放伤害加成",))
        self.assertAlmostEqual(q.pct["攻击"], 9.4)
        self.assertAlmostEqual(q.crit_rate, 6.9)
        self.assertAlmostEqual(q.energy, 10.0)
        self.assertEqual(set(q.ignored_bonus), {"普攻伤害加成"})
        # 不过滤(None)/空集 的两种边界
        all_on = aggregate(echo_stats=[("普攻伤害加成", 8.6)], allowed_bonus=None)
        self.assertAlmostEqual(all_on.bonus_zone(), 8.6)
        none_on = aggregate(echo_stats=[("普攻伤害加成", 8.6)], allowed_bonus=())
        self.assertAlmostEqual(none_on.bonus_zone(), 0.0)
        self.assertAlmostEqual(none_on.ignored_bonus["普攻伤害加成"], 8.6)

    def test_derived_bonus_from_panel_value(self):
        """`DerivedBonus`: 天赋类"由面板属性推导"的补正(共效 > 125 每点 +2% 增伤, 上限 50%)。

        要点: ①读**最终**属性值(含声骸副词条给的共效) ②阈值以下为 0 ③封顶 ④记进 `Panel.derived`
        ⑤共效本身不进加成区, 不会自我循环。
        """
        talent = DerivedBonus(source="共鸣效率", threshold=125, per_point=2, cap=50,
                              key="通用增伤", label="天赋")
        p = aggregate({"共鸣效率": 100, "攻击": 1000}, echo_stats=[("共鸣效率", 30.0)],
                      derived=[talent])
        self.assertAlmostEqual(p.energy, 130.0)
        self.assertAlmostEqual(p.derived["天赋"], 10.0)
        self.assertAlmostEqual(p.bonus.get("通用增伤", 0), 10.0)
        self.assertAlmostEqual(p.bonus_zone(), 10.0)
        low = aggregate({"共鸣效率": 120}, derived=[talent])          # 阈值以下 → 0
        self.assertEqual(low.derived, {})
        self.assertAlmostEqual(low.bonus_zone(), 0.0)
        high = aggregate({"共鸣效率": 200}, derived=[talent])         # 封顶
        self.assertAlmostEqual(high.derived["天赋"], 50.0)
        e = aggregate({"攻击": 1000, "攻击百分比": 50},               # 三系总值可作触发属性 + 加到属伤
                      derived=[DerivedBonus(source="攻击", threshold=1400, per_point=0.1,
                                            cap=5, key="热熔伤害加成", label="按攻击力")])
        self.assertAlmostEqual(e.scaling_total("攻击"), 1500.0)
        self.assertAlmostEqual(e.bonus.get("热熔伤害加成", 0), 5.0)

    def test_normalize_bonus_key(self):
        """专伤简写 → 标准键(`--specialty 重击` / UI 勾选框 / 未来的角色预设都用它)。"""
        self.assertEqual(normalize_bonus_key("重击"), "重击伤害加成")
        self.assertEqual(normalize_bonus_key("共解"), "共鸣解放伤害加成")
        self.assertEqual(normalize_bonus_key("共技"), "共鸣技能伤害加成")
        self.assertEqual(normalize_bonus_key(" 声骸技能 "), "声骸技能伤害加成")
        self.assertEqual(normalize_bonus_key("普攻伤害加成"), "普攻伤害加成")   # 全名原样
        self.assertEqual(normalize_bonus_key("热熔伤害加成"), "热熔伤害加成")   # 属伤不受影响
        for short, full in SPECIALTY_ALIASES.items():                         # 全部简写都能归一
            self.assertEqual(normalize_bonus_key(short), full, short)
            self.assertIn(full, SPECIALTY_KEYS)

    def test_is_bonus_key(self):
        for key in ("普攻伤害加成", "共鸣解放伤害加成", "气动伤害加成", "声骸技能伤害加成", "通用增伤"):
            self.assertTrue(is_bonus_key(key), key)
        for key in ("攻击", "攻击百分比", "暴击", "暴击伤害", "共鸣效率", "治疗效果加成"):
            self.assertFalse(is_bonus_key(key), key)

    def test_scaling_total_rejects_unknown_stat(self):
        p = aggregate({"攻击": 1})
        with self.assertRaises(KeyError):
            p.scaling_total("共鸣效率")
        for key in BASE_KEYS:                      # 三系都必须能算(缺省 0 也不报错)
            self.assertTrue(p.scaling_total(key) >= 0)

    def test_element_keys_match_gamedata(self):
        gd = load_gamedata()
        if gd is None:
            self.skipTest("无 assets/gamedata/echo_data.json")
        names = set((gd.get("main_prop_names") or {}).keys())
        self.assertTrue(set(ELEMENT_KEYS) <= names, set(ELEMENT_KEYS) - names)


class TestDamage(unittest.TestCase):

    def _panel(self):
        return aggregate({"攻击": 1000, "暴击": 60.0, "暴击伤害": 200.0},
                         corrections=[("重击伤害加成", 30.0), ("气动伤害加成", 10.0)])

    def test_expect_mode_hand_calc(self):
        # 1000 × (1 + 0.6×2.0) × (1 + 0.40) = 1000 × 2.2 × 1.4 = 3080
        self.assertAlmostEqual(damage(self._panel(), "攻击"), 3080.0)

    def test_crit_rate_capped_at_100(self):
        """暴击率按 100% 封顶: 溢出部分不产生收益(真实组合里会出现 112%~119% 暴击)。"""
        base = aggregate({"攻击": 1000, "暴击": 62.3, "暴击伤害": 220.0})
        over = aggregate({"攻击": 1000, "暴击": 112.3, "暴击伤害": 220.0})
        self.assertAlmostEqual(base.crit_zone(), 1 + 0.623 * 2.2)
        self.assertAlmostEqual(over.crit_zone(), 1 + 1.0 * 2.2)        # 与"刚好 100%"同分
        self.assertAlmostEqual(over.crit_wasted(), 12.3)
        self.assertEqual(base.crit_wasted(), 0.0)
        self.assertAlmostEqual(damage(over, "攻击") / damage(base, "攻击"),
                               (1 + 2.2) / (1 + 0.623 * 2.2))

    def test_single_hit_modes(self):
        p = self._panel()
        self.assertAlmostEqual(damage(p, "攻击", crit_mode="crit"), 1000 * 3.0 * 1.4)
        self.assertAlmostEqual(damage(p, "攻击", crit_mode="non_crit"), 1000 * 1.0 * 1.4)

    def test_constants_are_folded_only_when_passed(self):
        p = self._panel()
        self.assertAlmostEqual(damage(p, "攻击"), 3080.0)                       # 默认全 1 → 倍率省略
        self.assertAlmostEqual(damage(p, "攻击", skill_mult=2.5, amplify=1.2), 3080.0 * 3.0)

    def test_defense_and_resist_zone(self):
        # calculator: (100+90) / ((100+90) + (99+100)) = 190/389
        self.assertAlmostEqual(defense_zone(90, 100), 190 / 389)
        self.assertAlmostEqual(defense_zone(90, 100, 0), 190 / 389)
        self.assertAlmostEqual(defense_zone(90, 100, 100), 1.0)
        self.assertAlmostEqual(resist_zone(10), 0.9)
        self.assertAlmostEqual(resist_zone(0), 1.0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self._panel().crit_zone("???")
        with self.assertRaises(KeyError):
            damage(self._panel(), "共鸣效率")


if __name__ == '__main__':
    unittest.main(verbosity=2)
