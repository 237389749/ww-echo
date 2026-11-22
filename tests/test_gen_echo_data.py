"""`tools/gen_echo_data.py` 的"不静默丢数据"契约（2026-11-22 后端审查 B11）。

生成器的 docstring 写着：**任何文本键解析不出 → 退出码 2 且不写文件**。
旧的 `_props()` / `_echoes()` 走的是 `tm.get(...)` + 回落成"键本身"，解析不出时既不记
`unresolved` 也不报错 —— 属性名会被静默丢掉（主属性数值网格缺项 → 报告"数值可疑"误报/漏报），
`Monster_Name_123` 这种键还会被当成声骸名写进索引。

跑法（项目根目录）：
    python -m unittest tests.test_gen_echo_data -v
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gen_echo_data as gen  # noqa: E402


class _FakeBin:
    """只实现 `table(name)`：按表名给行。"""

    def __init__(self, tables):
        self._t = tables

    def table(self, name):
        return self._t.get(name, [])


class PropsUnresolvedTest(unittest.TestCase):
    def test_missing_property_name_is_recorded(self):
        b = gen.Builder(_FakeBin({"PropertyIndex": [
            {"Id": 1, "Name": "Prop_1_Name", "IsPercent": True},
            {"Id": 2, "Name": "Prop_2_Name", "IsPercent": False},
        ]}), tm={"Prop_1_Name": "暴击"})                        # 第 2 个键故意缺失
        props = b._props()
        self.assertEqual([v["name"] for v in props.values()], ["暴击"])   # 解析得出的那条保留
        self.assertEqual(len(props), 1)                                    # 缺失的那条不写成键
        self.assertTrue(any("Prop_2_Name" in u for u in b.unresolved),
                        f"缺失的属性名没有被记进 unresolved: {b.unresolved}")


class EchoesUnresolvedTest(unittest.TestCase):
    def _builder(self, monster_name, tm):
        tables = {
            "PhantomRarity": [{"Rare": 5, "Cost": 4}],
            "PhantomItem": [{"PhantomType": 1, "MonsterName": monster_name,
                             "Rarity": 5, "FetterGroup": [36]}],
        }
        return gen.Builder(_FakeBin(tables), tm=tm)

    def test_missing_echo_name_is_not_used_as_key(self):
        b = self._builder("Monster_Name_999999", tm={})
        sets = {"衔梦照世之心": {"id": 36, "echoes": {"4c": [], "3c": [], "1c": []}}}
        echoes = b._echoes(sets)
        self.assertEqual(echoes, {}, "把文本键当声骸名写进了索引")
        self.assertTrue(any("Monster_Name_999999" in u for u in b.unresolved),
                        f"缺失的声骸名没有被记进 unresolved: {b.unresolved}")

    def test_resolved_echo_name_is_used(self):
        b = self._builder("Monster_1_Name", tm={"Monster_1_Name": "无归的谬误"})
        sets = {"衔梦照世之心": {"id": 36, "echoes": {"4c": [], "3c": [], "1c": []}}}
        echoes = b._echoes(sets)
        self.assertEqual(list(echoes), ["无归的谬误"])
        self.assertEqual(echoes["无归的谬误"]["sets"], ["衔梦照世之心"])
        self.assertEqual(b.unresolved, [])


class SourceInfoTest(unittest.TestCase):
    """C12：生成物的 `_source` 不许写本机绝对路径（入库产物，diff 会被路径污染）。"""

    def test_no_absolute_paths(self):
        info = gen.source_info("3.7.0", 37, 229,
                               bindata=r"C:\Users\someone\ww\search\wwdata37\BinData",
                               textmaps=r"C:\Users\someone\ww\search\wwdata37\Textmaps\zh-Hans")
        raw = json.dumps(info, ensure_ascii=False)
        self.assertNotIn("C:\\", raw)
        self.assertNotIn("Users", raw)
        self.assertEqual(info["bindata"], "BinData")
        self.assertEqual(info["textmaps"], "zh-Hans")
        self.assertEqual((info["version"], info["sets"], info["echoes"]), ("3.7.0", 37, 229))

if __name__ == "__main__":
    unittest.main(verbosity=2)
