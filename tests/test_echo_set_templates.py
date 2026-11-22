"""`src/echo_set_templates` 声骸名容错匹配的单元测试 —— 不依赖游戏数据。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_set_templates.py

覆盖 CHANGELOG 阶段十一记录的匹配链，以及阶段十二(图标兜底)与「官方静态数据层」的动机：
- 有 `assets/gamedata/echo_data.json` 时按**显示名**匹配，**皮肤名与本体名分池**
  (配置里 `异相·X` 有自己的套装，13 例与本体不同 → 剥前缀复用本体套装必错)；
- 无生成物时退回旧口径(剥「异相」前缀 + 模板 `_echoes`)。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.echo_set_templates as T  # noqa: E402


class TestEchoNameMatching(unittest.TestCase):

    def test_returns_candidate_list(self):
        cands = T.get_sets_by_echo('海维夏')
        self.assertIsInstance(cands, list)
        self.assertTrue(cands)

    def test_skin_echo_keeps_its_own_sets(self):
        """配置里 `异相·X` 是独立声骸、有自己的套装 —— 不再"剥前缀复用本体套装"。"""
        self.assertEqual(T.get_sets_by_echo('异相·巡游骑士'), ['彻空冥雷', '熔山裂谷'])
        self.assertEqual(T.get_sets_by_echo('巡游骑士'), ['凌冽决断之心', '幽夜隐匿之帷'])
        gd = T.load_gamedata()
        if gd is None:
            self.skipTest('无生成物, 当前是旧口径')
        for name, e in gd['echoes'].items():
            if e.get('base'):        # 42 个皮肤条目: 每个都必须精确命中自己的套装
                with self.subTest(skin=name):
                    self.assertEqual(T.get_sets_by_echo(name), e['sets'])

    def test_skin_real_ocr_truncation(self):
        """真实 dataset 那只: OCR 截成 `异相·双极·星升辉`(丢了「铳」)。"""
        if T.load_gamedata() is None:
            self.skipTest('无生成物')
        self.assertEqual(T.get_sets_by_echo('异相·双极·星升辉'), ['流金溯真之式'])
        self.assertEqual(T.normalize_echo_name('异相·双极·星升辉'), '异相·双极·星升辉铳')
        # 皮肤与本体是两只不同的声骸(K 剥前缀复用本体套装会得到另一个集合)
        self.assertNotEqual(T.get_sets_by_echo('异相·双极·星升辉'),
                            T.get_sets_by_echo('双极·星升辉铳'))

    def test_falls_back_to_templates_without_gamedata(self):
        """生成物缺失(旧安装/打包遗漏)时退回旧口径: 剥「异相」前缀 → 模板 `_echoes`。"""
        try:
            with mock.patch.object(T, 'load_gamedata', return_value=None):
                T._echo_index = None
                base = T.get_sets_by_echo('双极·星升辉铳')
                self.assertTrue(base)
                self.assertEqual(T.get_sets_by_echo('异相·双极·星升辉铳'), base)
        finally:
            T._echo_index = None     # 让后续测试按生成物重建

    def test_new_37_sets_are_usable(self):
        expects = {'衔梦照世之心': '共鸣回响·天演溯心',
                   '镜影流电之瞬': '共鸣回响·天演溯心',
                   '茜染怀想之花': '千傀重楼'}
        for set_name, four_c in expects.items():
            with self.subTest(set=set_name):
                self.assertIn(set_name, T.get_all_set_names())
                self.assertIn(four_c, T.get_set_echoes(set_name)['4c'])
                self.assertTrue(T.get_set_weights(set_name), '新套装要有权重(模板已用通用权重播种)')
                self.assertIn(set_name, T.get_sets_by_echo('巡霄枪卫') + [set_name])

    def test_nightmare_prefix_is_real_and_kept(self):
        # 「梦魇·」是真实前缀(独立声骸), 不能被当成皮肤前缀剥离
        nightmare = T.get_sets_by_echo('梦魇·青羽鹭')
        self.assertTrue(nightmare)
        self.assertNotEqual(nightmare, T.get_sets_by_echo('青羽鹭'))
        self.assertIn('息界同调之律', nightmare)

    def test_known_occluded_case_justifies_icon_matching(self):
        # 「梦魔」(魇→魔 错字)名字层会子串抢跑误配 → 这正是套装图标兜底的场景
        self.assertNotIn('息界同调之律', T.get_sets_by_echo('梦魔·青羽鹭'))

    def test_unmatched_returns_empty(self):
        for bad in ('', '这不是声骸名', 'ZZZZ'):
            with self.subTest(name=bad):
                self.assertEqual(T.get_sets_by_echo(bad), [])

    def test_unknown_echo_maps_to_none(self):
        self.assertIsNone(T.get_set_by_echo('这不是声骸名'))

    def test_prefer_respected_else_first_candidate(self):
        echo, cands = self._first_multi_set_echo()
        self.assertGreaterEqual(len(cands), 2)
        self.assertEqual(T.get_set_by_echo(echo), cands[0])
        self.assertEqual(T.get_set_by_echo(echo, prefer=cands[-1]), cands[-1])
        self.assertEqual(T.get_set_by_echo(echo, prefer='不存在的套装'), cands[0])

    def test_templates_shape(self):
        names = T.get_all_set_names()
        self.assertEqual(len(names), 37)         # 3.6=34, 3.7 新增 3 套(官方表)
        templates = T.load_templates()
        for name in names:
            with self.subTest(set_name=name):
                info = templates[name]
                self.assertTrue(info['weights'], '有效词条不能为空')
                self.assertEqual(set(info['echoes'].keys()), {'4c', '3c', '1c'})

    def _first_multi_set_echo(self):
        """找一个属 ≥2 套装的声骸(181 个声骸名中 120 个属多套)。"""
        for set_name in T.get_all_set_names():
            for echoes in (T.get_set_echoes(set_name) or {}).values():
                for echo in echoes:
                    cands = T.get_sets_by_echo(echo)
                    if len(cands) >= 2:
                        return echo, cands
        self.skipTest('模板中无多套装声骸样本')


class TestCoreFirstFallback(unittest.TestCase):
    """`get_set_core_first` 的缺省必须是**权重 > 0** 的词条 —— 不是 weights 字典的全部键。

    旧实现返回全部键(模板里未认的词条记 0), 于是 Lv5/L10 的结构判定会放过该套装完全不认的词条
    (如凝夜白霜只出 防御 也判"存在核心词条")。33/37 套走缺省路径, 所以这条要钉住。
    """

    def test_default_is_positive_weight_only(self):
        w = T.get_set_weights("凝夜白霜")
        if not w:
            self.skipTest("无模板")
        core = T.get_set_core_first("凝夜白霜") or []
        self.assertEqual(set(core), {k for k, v in w.items() if v > 0})
        self.assertNotIn("防御", core)
        self.assertNotIn("生命", core)

    def test_explicit_core_first_wins(self):
        if not T.get_set_weights("隐世回光"):
            self.skipTest("无模板")
        self.assertEqual(T.get_set_core_first("隐世回光"), ["攻击百分比", "共鸣效率"])

    def test_general_mode_returns_none(self):
        self.assertIsNone(T.get_set_core_first("通用"))


class TestTemplateValidation(unittest.TestCase):
    """B3(2026-11-22 后端审查)：手写坏的模板必须**过滤 + 告警**，不能把异常抛给调用方。

    `assets/echo_set_templates.json` 是文档让用户手写的策略文件。旧实现里 `float(weight)` 与
    `_core_first` 的迭代都没有保护，`{"暴击": "高"}` 会让 `load_templates` 抛 ValueError 一路冒到
    `EnhanceEchoTask.__init__` → 整个程序起不来，而且不说清是哪个套装。
    """

    def test_bad_values_are_filtered_not_raised(self):
        cases = {
            "权重字符串": {"S": {"暴击": "高", "攻击百分比": 0.5}},
            "权重 null": {"S": {"暴击": None}},
            "_core_first 数字": {"S": {"暴击": 1.0, "_core_first": 5}},
            "_core_first 字符串": {"S": {"暴击": 1.0, "_core_first": "暴击"}},
            "_low_first 非 dict": {"S": {"暴击": 1.0, "_low_first": "x"}},
            "套装不是 dict": {"S": "oops"},
        }
        for title, raw in cases.items():
            with self.subTest(title):
                out = T._validate_and_filter(raw)          # ← 关键是"不抛"
                self.assertIsInstance(out, dict)

    def test_valid_entries_survive_neighbour_error(self):
        out = T._validate_and_filter({"S": {"暴击": 1.0, "攻击百分比": "坏"}})
        self.assertEqual(out["S"]["weights"], {"暴击": 1.0})   # 好的留下, 坏的那条被过滤

    def test_load_templates_survives_bad_file(self):
        """真文件里写坏一个权重 → `load_templates` 仍返回 dict(不再让程序起不来)。"""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tpl.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "sets": {"坏套装": {"暴击": "高"}}}, f, ensure_ascii=False)
            old = (T._TEMPLATE_PATH, T._template_cache, T._cache_mtime, T._echo_index)
            T._TEMPLATE_PATH, T._template_cache, T._cache_mtime = path, None, 0
            try:
                out = T.load_templates(force=True)     # ← 不抛
                self.assertEqual(out["坏套装"]["weights"], {})
            finally:
                T._TEMPLATE_PATH, T._template_cache, T._cache_mtime, T._echo_index = old


class TestLowFirst(unittest.TestCase):
    """低权重首条门槛 `_low_first`: **按套装可选** —— 只有轻云出月这类带 0.1 占位键的套装需要。"""

    def test_light_cloud_has_gate(self):
        self.assertEqual(T.get_set_low_first("轻云出月"), {"below": 0.1, "top": 2})

    def test_other_sets_default_off(self):
        self.assertIsNone(T.get_set_low_first("凝夜白霜"))
        self.assertIsNone(T.get_set_low_first("通用"))
        self.assertIsNone(T.get_set_low_first("不存在的套装"))

    def test_invalid_config_is_ignored(self):
        cleaned = T._validate_and_filter({
            "测试套": {"暴击": 1.0, "_low_first": {"below": "x", "top": 2}},
            "测试套2": {"暴击": 1.0, "_low_first": {"below": 0.1, "top": 0}},
        })
        self.assertIsNone(cleaned["测试套"]["low_first"])
        self.assertIsNone(cleaned["测试套2"]["low_first"])

    def test_valid_config_is_parsed(self):
        cleaned = T._validate_and_filter({
            "测试套": {"暴击": 1.0, "_low_first": {"below": 0.25, "top": 3}},
        })
        self.assertEqual(cleaned["测试套"]["low_first"], {"below": 0.25, "top": 3})


class TestEchoSetCounts(unittest.TestCase):
    """一值单键 / 一值多键 —— 评估链只对单键名字锁定套装(2026-11-20 report4 的教训)。

    统计的权威来源是生成物 `echoes[name].sets`；评估链里 `len(get_sets_by_echo(name)) == 1`
    才允许按名字锁定，多键必须逐只读面板（格洛犸图 → 长路启航之星/雪落无声之愿）。
    """

    def test_official_distribution(self):
        counts = T.echo_set_counts()
        self.assertEqual(len(counts), 229, msg='官方索引 229 个显示名(含异相皮肤)')
        dist = {}
        for c in counts.values():
            dist[c] = dist.get(c, 0) + 1
        self.assertEqual(dist, {1: 71, 2: 108, 3: 47, 4: 3},
                         msg='单键 71 / 多键 158；数据换版后要重新确认评估口径')

    def test_known_cases(self):
        counts = T.echo_set_counts()
        self.assertEqual(counts['格洛犸图'], 2)      # 长路启航之星 / 雪落无声之愿
        self.assertEqual(counts['冰盈舞者'], 3)
        self.assertEqual(counts['辛吉勒姆'], 1)      # 一值单键 → 可按名锁定
        self.assertEqual(counts['无常凶鹭'], 1)


class TestWeightsAreCopied(unittest.TestCase):
    """C1：`get_set_weights` 必须返回副本。

    以前返回模板缓存里的同一个 dict —— 任何调用方 `w[k] = v` 都会改掉全局模板，
    后面的评分/判定跟着变，而且找不到是谁改的（实测改一下再取就变）。
    """

    def test_mutation_does_not_leak_into_cache(self):
        name = "凝夜白霜"
        w = T.get_set_weights(name)
        if not w:
            self.skipTest("无模板")
        w["暴击"] = 99.0
        self.assertNotEqual(T.get_set_weights(name)["暴击"], 99.0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
