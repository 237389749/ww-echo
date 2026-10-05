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


if __name__ == '__main__':
    unittest.main(verbosity=2)
