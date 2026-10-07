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

from src.echo_panel import (BASE_KEYS, ELEMENT_KEYS, Correction, aggregate,          # noqa: E402
                            damage, defense_zone, is_bonus_key, resist_zone)
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
