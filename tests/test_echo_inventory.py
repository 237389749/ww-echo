"""`src/echo_inventory.py` 单测: 主属性/词条名归一(固定 vs 百分比) + 报告与 JSON 两条导入路径。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_inventory.py

口径依据(实测 219 张真实面板):
- 第 1 行 = 声骸主属性, 第 2 行 = **COST 固有属性**(1C 生命 2280 / 3C 攻击 100 / 4C 攻击 150, 满级);
- `攻击/生命/防御` 同名两变体(固定值 / 百分比), 报告路径按 `%` 判, JSON 路径按官方取值网格判。
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.echo_inventory import (load_inventory, latest_debug_dir, normalize_main_prop,   # noqa: E402
                                parse_level, resolve_set, split_rows, substat_key, summarize)

LINES = """共鸣回响·鸣式·虚造神型
+25
COST 4
Z | C
暴击 | 22.0%
攻击 | 150
暴击 | 6.9%
共鸣解放伤害加成 | 8.6%
攻击 | 9.4%
共鸣技能伤害加成 | 10.1%
共鸣效率 | 10.0%""".split("\n")


class TestNormalize(unittest.TestCase):

    def test_report_style_values(self):
        cases = [("暴击", "22.0%", 25, 4, "暴击"),
                 ("暴击伤害", "44.0%", 25, 4, "暴击伤害"),
                 ("气动伤害加成", "30.0%", 25, 3, "气动伤害加成"),
                 ("共鸣效率", "32.0%", 25, 3, "共鸣效率"),
                 ("治疗效果加成", "26.4%", 25, 4, "治疗效果加成"),
                 ("攻击", "18.0%", 25, 1, "攻击百分比"),      # 1C 主属性是攻击%
                 ("攻击", "30.0%", 25, 3, "攻击百分比"),
                 ("攻击", "150", 25, 4, "攻击"),              # 4C 固有属性
                 ("攻击", "100", 25, 3, "攻击"),              # 3C 固有属性
                 ("生命", "2280", 25, 1, "生命"),             # 1C 固有属性
                 ("X攻击", "150", 25, 4, "攻击"),             # OCR 前缀污染不影响
                 ("不存在属性", "1", 25, 1, "不存在属性")]     # 认不出 → 原文(交给 unknown 记录)
        for raw, val, lv, cost, want in cases:
            with self.subTest(raw=raw, val=val, cost=cost):
                self.assertEqual(normalize_main_prop(raw, val, lv, cost), want)

    def test_json_style_floats_use_official_grid(self):
        # JSON 里数值已丢 %, 只能靠官方网格: 18.0 只可能是百分比变体(+25), 150.0 只可能是固定变体
        self.assertEqual(normalize_main_prop("攻击", 18.0, 25), "攻击百分比")
        self.assertEqual(normalize_main_prop("攻击", 150.0, 25), "攻击")
        self.assertEqual(normalize_main_prop("生命", 2280.0, 25), "生命")

    def test_substat_key_splits_flat_and_percent(self):
        for name, val, want in (("攻击", 30.0, "攻击"), ("攻击", 9.4, "攻击百分比"),
                                ("生命", 470.0, "生命"), ("生命", 8.6, "生命百分比"),
                                ("防御", 60.0, "防御"), ("防御", 13.8, "防御百分比"),
                                ("暴击", 6.9, "暴击"), ("共鸣效率", 9.2, "共鸣效率")):
            with self.subTest(name=name, val=val):
                self.assertEqual(substat_key(name, val), want)


class TestParsing(unittest.TestCase):

    def test_split_rows_and_level(self):
        name, props, cost = split_rows(LINES)
        self.assertEqual((name, cost, len(props)), ("共鸣回响·鸣式·虚造神型", 4, 7))
        self.assertEqual(props[0], ("暴击", "22.0%"))
        self.assertEqual(parse_level(LINES), 25)

    def test_resolve_set_returns_triple(self):
        set_name, src, score = resolve_set("鸣钟之龟")          # 无整帧 → 名字候选
        self.assertTrue(set_name)
        self.assertIn(src, ("name", "default"))
        self.assertIsNone(score)


class TestItemBuilding(unittest.TestCase):

    def test_report_item_has_two_mains_and_subs(self):
        from src.echo_inventory import item_from_report
        item = item_from_report("0001_x", LINES)
        self.assertIsNotNone(item)
        self.assertEqual(item.cost, 4)
        self.assertEqual(item.level, 25)
        self.assertEqual(item.main, (("暴击", 22.0), ("攻击", 150.0)))
        self.assertEqual(len(item.stats) - len(item.main), 5)
        self.assertEqual(item.stats[2], ("暴击", 6.9))

    def test_zero_level_item_skipped(self):
        from src.echo_inventory import item_from_report
        lines = ["某声骸", "+0", "COST 3", "攻击 | 30.0%", "攻击 | 100"]
        self.assertIsNone(item_from_report("0002", lines))

    def test_json_record(self):
        from src.echo_inventory import item_from_record
        rec = {"index": 1, "name": "晶螯蝎", "set": "不绝余音", "cost": 1,
               "main_props": [{"name": "攻击", "value": 18.0}, {"name": "生命", "value": 2280.0}],
               "stats": [{"name": "暴击", "value": 6.9}, {"name": "攻击", "value": 9.4}]}
        item = item_from_record(rec)
        self.assertEqual(item.set_name, "不绝余音")
        self.assertEqual(item.main, (("攻击百分比", 18.0), ("生命", 2280.0)))
        self.assertEqual(item.stats[2:], (("暴击", 6.9), ("攻击百分比", 9.4)))


class TestLoadInventory(unittest.TestCase):

    def test_load_json_file(self):
        data = {"set": "通用", "total": 1, "results": [
            {"index": 1, "name": "辛吉勒姆", "set": "长路启航之星", "cost": 4,
             "main_props": [{"name": "暴击伤害", "value": 44.0}, {"name": "攻击", "value": 150.0}],
             "stats": [{"name": "攻击", "value": 30.0}]}]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eval_result.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            items = load_inventory(p)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].name, items[0].cost, items[0].set_name),
                         ("辛吉勒姆", 4, "长路启航之星"))
        self.assertEqual(summarize(items)["by_cost"], {4: 1})

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_inventory(os.path.join(tempfile.gettempdir(), "不存在的目录_zzz"))


class TestRealDataset(unittest.TestCase):
    """真实数据集冒烟(不开图标识别, 只验结构): 109 只 / COST 分布 / 两类主属性的取值形态。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = latest_debug_dir()
        if not cls.dir or not os.path.exists(os.path.join(cls.dir, "image_report.md")):
            raise unittest.SkipTest("无 logs/eval_debug/ 素材")
        cls.items = load_inventory(cls.dir, use_icons=False)

    def test_shape(self):
        self.assertEqual(len(self.items), 109)
        self.assertEqual(summarize(self.items)["by_cost"], {1: 55, 3: 35, 4: 19})
        for i in self.items:
            self.assertIn(i.cost, (1, 3, 4))
            self.assertEqual(len(i.main), 2)            # 主属性 2 行(主属性 + COST 固有属性)
            self.assertTrue(1 <= len(i.stats) - 2 <= 5)  # 词条 1~5 条
            self.assertIn(i.level, (None, 25, 20, 22, 23, 15, 16, 10, 5))

    def test_cost_fixed_row_matches_official_grid(self):
        """第 2 行 = COST 固有属性: 1C 生命 2280 / 3C 攻击 100 / 4C 攻击 150(满级件)。"""
        want = {1: ("生命", 2280.0), 3: ("攻击", 100.0), 4: ("攻击", 150.0)}
        checked = 0
        for i in self.items:
            if i.level != 25:
                continue
            self.assertEqual(i.main[1], want[i.cost], str(i))
            checked += 1
        self.assertGreater(checked, 60)


if __name__ == '__main__':
    unittest.main(verbosity=2)
