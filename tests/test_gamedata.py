"""静态数据层（`assets/gamedata/echo_data.json` + `src/wuwa_data.py`）的单元测试 —— 不依赖游戏表。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_gamedata.py

覆盖三件事：
1. 生成物的**结构自洽**（套装↔声骸双向一致、方案/效果齐全、属性名可读）；
2. 3.7 值得写死的**回归锚点**（三个新套装、皮肤条目自带套装 —— 剥前缀即错的那 13 例）；
3. 读取层的**纯函数**（两种序列化、文本表两种形态、FlatBuffers 方案解码）。
生成物本身由 `tools/gen_echo_data.py` 产出；文本键解析不出时该工具**退出码 2 且不写文件**。
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.wuwa_data import BinData, load_textmaps, parse_plan_bin  # noqa: E402

DATA_PATH = os.path.join(REPO, "assets", "gamedata", "echo_data.json")
COSTS = ("4c", "3c", "1c")


def load_data():
    if not os.path.exists(DATA_PATH):
        raise unittest.SkipTest(f"生成物不存在: {DATA_PATH}(先跑 tools/gen_echo_data.py)")
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestGeneratedData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = load_data()
        cls.sets = cls.data["sets"]
        cls.echoes = cls.data["echoes"]
        cls.props = cls.data["props"]

    def test_source_stamp_and_counts(self):
        src = self.data["_source"]
        for key in ("version", "bindata", "textmaps", "sets", "echoes"):
            self.assertIn(key, src)
        self.assertEqual(src["sets"], len(self.sets))
        self.assertEqual(src["echoes"], len(self.echoes))
        self.assertGreaterEqual(len(self.sets), 37)      # 3.7 起是 37 套

    def test_every_set_is_complete(self):
        icon_dir = Path(REPO) / "assets" / "echo_icons"
        for name, v in self.sets.items():
            with self.subTest(set=name):
                self.assertTrue(v["id"] and v["sort_id"] is not None)
                self.assertTrue(v["icon_asset"], "图标资产名不能为空")
                self.assertEqual(v["icon_file"], f"{name}.png")
                self.assertTrue((icon_dir / v["icon_file"]).exists(),
                                f"缺图标模板 {v['icon_file']}(需从客户端官方贴图补齐, 见 CLAUDE.md「官方静态数据层」)")
                self.assertTrue(v["fetter_ids"], "缺少件套 fetter id")
                # 每档效果都必须带件数(2/3/5): UI 要按"几件套"显示效果原文
                for fid, eff in v["effects"].items():
                    with self.subTest(set=name, fid=fid):
                        # 件数必须存在(丢了它 UI 就标不出"几件套"); 常见档位 2/3/5,
                        # 实测还有一个 1 件套的特殊套装 —— 所以只要求是正数, 不锁死集合。
                        self.assertIsInstance(eff.get("pieces"), int,
                                              f"{name} 的效果 {fid} 缺件数")
                        self.assertGreaterEqual(eff.get("pieces"), 1)
                self.assertEqual(set(v["effects"]), {str(i) for i in v["fetter_ids"]},
                                 "每个 fetter id 都要有效果文本")
                self.assertTrue(any(v["echoes"][k] for k in COSTS), "套装不能没有声骸")
                self.assertEqual(set(v["echoes"]), set(COSTS))

    def test_every_plan_row_is_usable(self):
        for name, v in self.sets.items():
            with self.subTest(set=name):
                self.assertTrue(v["plan"], "官方主属性方案不能为空")
                # 个别套装某个 COST 的保留组本来就是空的(如「不绝余音」3C), 但整体不能全空
                self.assertTrue(any(r["lock"] for r in v["plan"].values()),
                                f"{name} 的 1C/3C/4C 全都给了空保留组")
                for cost, row in v["plan"].items():
                    self.assertIn(cost, ("1", "3", "4"))
                    self.assertIsInstance(row["lock"], list)
                    self.assertIsInstance(row["discard"], list)
                    self.assertFalse(set(row["lock"]) & set(row["discard"]),
                                     "同一属性不能既保留又丢弃")

    def test_echo_index_consistent_with_sets(self):
        for name, e in self.echoes.items():
            with self.subTest(echo=name):
                self.assertIn(e["cost"], (1, 3, 4))
                self.assertTrue(e["sets"], "索引里的声骸必须属至少一个套装")
                for s in e["sets"]:
                    self.assertIn(s, self.sets)
                    self.assertIn(name, self.sets[s]["echoes"][f"{e['cost']}c"],
                                  "套装↔声骸必须双向一致")

    def test_three_new_37_sets(self):
        expect = {                       # 名 → (fettergroup id, 图标资产名)
            "衔梦照世之心": (36, "T_IconElementAttriXin"),
            "镜影流电之瞬": (37, "T_IconElementAttriThunderError"),
            "茜染怀想之花": (38, "T_IconElementAttriCureA"),
        }
        for name, (sid, icon) in expect.items():
            with self.subTest(set=name):
                self.assertIn(name, self.sets)
                self.assertEqual(self.sets[name]["id"], sid)
                self.assertEqual(self.sets[name]["icon_asset"], icon)
        # 导电套 3C 锁导电(24)、治疗套 4C 锁治疗(35) —— 与套装效果文本一致
        self.assertEqual(self.sets["衔梦照世之心"]["plan"]["3"]["lock"], [24])
        self.assertEqual(self.sets["镜影流电之瞬"]["plan"]["3"]["lock"], [24])
        self.assertEqual(self.sets["茜染怀想之花"]["plan"]["4"]["lock"], [35])
        self.assertIn(11, self.sets["茜染怀想之花"]["plan"]["3"]["lock"])

    def test_skin_echoes_keep_their_own_sets(self):
        """配置里 `异相·X` 有自己的套装 —— 13 例与本体不同, 剥前缀复用本体套装必错。"""
        self.assertEqual(self.echoes["异相·巡游骑士"]["sets"], ["彻空冥雷", "熔山裂谷"])
        self.assertEqual(self.echoes["巡游骑士"]["sets"], ["凌冽决断之心", "幽夜隐匿之帷"])
        self.assertEqual(self.echoes["异相·巡游骑士"]["base"], "巡游骑士")
        conflict = sorted(n for n, e in self.echoes.items()
                          if e.get("base") and e["base"] in self.echoes
                          and self.echoes[e["base"]]["sets"] != e["sets"])
        self.assertEqual(len(conflict), 13)
        self.assertIn("异相·踏光兽", conflict)

    def test_plan_and_props_examples(self):
        self.assertEqual(self.sets["凝夜白霜"]["plan"]["4"]["lock"], [8, 9])
        self.assertEqual(self.sets["隐世回光"]["plan"]["4"]["lock"], [35])
        self.assertEqual(self.sets["不绝余音"]["plan"]["1"]["lock"], [10007])
        self.assertEqual(self.props["8"], {"name": "暴击", "pct": True})
        self.assertEqual(self.props["24"]["name"], "导电伤害加成")
        self.assertEqual(self.props["35"]["name"], "治疗效果加成")
        self.assertEqual(self.props["10007"]["name"], "攻击")
        self.assertFalse(self.props["10007"]["pct"])


class TestWuwaData(unittest.TestCase):
    """读取层的纯函数 —— 不依赖任何游戏表。"""

    def test_pairs_accepts_both_serializations(self):
        self.assertEqual(BinData.pairs([{"Key": 2, "Value": 1}, {"Key": 5, "Value": 2}]), [(2, 1), (5, 2)])
        self.assertEqual(BinData.pairs({"2": 1, "5": 2}), [("2", 1), ("5", 2)])
        self.assertEqual(BinData.pairs(None), [])

    def test_load_textmaps_forms_and_numeric_keys_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "multi_text"))
            with open(os.path.join(d, "multi_text", "MultiText.json"), "w", encoding="utf-8") as f:
                json.dump([{"Id": "PhantomFetter_36_Name", "Content": "衔梦照世之心"}], f, ensure_ascii=False)
            with open(os.path.join(d, "flat.json"), "w", encoding="utf-8") as f:
                json.dump({"PhantomFetter_37_Name": "镜影流电之瞬", "1": "风暴序曲"}, f, ensure_ascii=False)
            tm = load_textmaps(d)
            self.assertEqual(tm["PhantomFetter_36_Name"], "衔梦照世之心")
            self.assertEqual(tm["PhantomFetter_37_Name"], "镜影流电之瞬")
            self.assertNotIn("1", tm, "全数字键是另一套 id 空间, 必须跳过")

    def test_parse_plan_bin_real_blob(self):
        # 客户端 3.7 PhantomManagePlanV2 (FetterId 1, Cost 4) 的真实 BinData
        blob = base64.b64decode(
            "EAAAAAwAFAAQAAwACAAEAAwAAAAQAAAABAAAAAEAAABBnAAAAgAAAAgAAAAJAAAA")
        self.assertEqual(parse_plan_bin(blob),
                         {"Id": 40001, "FetterId": 1, "Cost": 4, "LockGroup": [8, 9]})

    def test_parse_plan_bin_rejects_garbage(self):
        for bad in (b"", b"\x01\x02", b"\xff\xff\xff\xff" * 4, base64.b64decode("EAAAAAwAFAAQAAwA")):
            with self.subTest(blob=bad):
                with self.assertRaises(ValueError):
                    parse_plan_bin(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
