# -*- coding: utf-8 -*-
"""测试: 主属性数值校验(src/echo_main_prop.py) —— 用游戏内已知数值当锚点。"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.echo_main_prop import check_main_values, levels_for_tier, value_grid  # noqa: E402


class TestMainPropValues(unittest.TestCase):
    def test_known_5star_values(self):
        """5★ 满级主属性的公开已知值 —— 官方表推出来的必须与游戏一致。"""
        cases = {
            "暴击": [22.0],          # COST4 5★ +25
            "暴击伤害": [44.0],
            "攻击": [150.0, 33.0],   # 固定值 150 / 百分比 33.0
            "生命": [2280.0, 33.0],
            "共鸣效率": [32.0],
        }
        for name, expect in cases.items():
            grid = value_grid(name)
            with self.subTest(prop=name):
                self.assertTrue(grid, f"{name} 网格为空")
                for v in expect:
                    self.assertLessEqual(min(abs(g - v) for g in grid), 0.11,
                                         f"{name} 的 {v} 不在网格上(最接近 {min(grid, key=lambda g: abs(g - v))})")

    def test_curve_is_linear_and_capped(self):
        from src.echo_main_prop import _table
        t = _table()
        curve = t["growth"]["1"]
        self.assertEqual(t["level_cap"], 25)
        self.assertEqual(len(curve), 26)
        self.assertEqual(curve[0], 10000)
        self.assertEqual(curve[-1], 50000)
        self.assertEqual(curve[1] - curve[0], curve[2] - curve[1], "成长曲线应为等差")

    def test_tier_window(self):
        """词条数只给**下界**(第 n 条词条在 +5n 开), 上界恒为满级 25。"""
        self.assertEqual(levels_for_tier(0), list(range(0, 26)))
        self.assertEqual(levels_for_tier(1), list(range(5, 26)))
        self.assertEqual(levels_for_tier(5), list(range(25, 26)))

    def test_real_panel_plus22(self):
        """真实面板回归(0174): `+22` 却已有 5 条词条 → 主属性按 +22 的曲线取值。

        修正前用 tier=5 把窗口卡成 [25,25] 并拿"第一个变体"的百分比容差去比固定值 → 把合法的
        `攻击 135`(= 30 × 45200/10000 ≈ 135.6, +22 的固定攻击)误判成 OCR 误读。
        """
        self.assertIs(check_main_values([("攻击", "135")], tier=4)[0]["ok"], True)
        self.assertIs(check_main_values([("攻击", "136")], tier=4)[0]["ok"], True)
        # 但满级(tier=5, 只可能是 +25)读到 135 就是真错了(+25 的固定攻击是 150)
        self.assertIs(check_main_values([("攻击", "135")], tier=5)[0]["ok"], False)

    def test_wrong_value_flagged(self):
        """OCR 把 150 读成 1500 → 必须被判非法(5★ 攻击的合法值最大 150)。"""
        res = check_main_values([("攻击", "1500")], tier=5)
        self.assertEqual(len(res), 1)
        self.assertIs(res[0]["ok"], False)
        self.assertIn(res[0]["expect"], (150.0, 100.0))

    def test_value_valid_only_in_right_tier(self):
        """`攻击 20` 只在 +0~+4 合法(下界 25 起就没有它了); tier=5 读到 20 说明读错了。

        注: 不是任意值都能这样卡 —— 例如 `攻击 30` 在满级也合法, 因为它正是"攻击 **30.0%**"那个变体
        (面板的 `%` 在 parse_number 时被剥掉, 单看数值无法区分固定值/百分比)。
        """
        self.assertIs(check_main_values([("攻击", "20")], tier=0)[0]["ok"], True)
        self.assertIs(check_main_values([("攻击", "20")], tier=5)[0]["ok"], False)

    def test_unknown_prop_is_neutral(self):
        res = check_main_values([("这不是属性", "123")], tier=5)
        self.assertIsNone(res[0]["ok"], "不认识的属性名不应表态")

    def test_percent_tolerance(self):
        """百分比属性容差 0.11(显示 1 位小数), 固定值容差 1.0。"""
        self.assertIs(check_main_values([("暴击", "22.0")], tier=5)[0]["ok"], True)
        self.assertIs(check_main_values([("暴击", "22.5")], tier=5)[0]["ok"], False)


if __name__ == "__main__":
    unittest.main()
