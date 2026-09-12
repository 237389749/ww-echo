"""`src/echo_set_templates` 声骸名容错匹配的单元测试 —— 不依赖游戏数据。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_echo_set_templates.py

覆盖 CHANGELOG 阶段十一记录的匹配链(剥「异相」前缀 → 精确 → 白名单清洗 → 子串 → LCS),
以及"名字层已实证无解、必须交套装图标兜底"的案例(阶段十二的动机)。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.echo_set_templates as T  # noqa: E402


class TestEchoNameMatching(unittest.TestCase):

    def test_returns_candidate_list(self):
        cands = T.get_sets_by_echo('海维夏')
        self.assertIsInstance(cands, list)
        self.assertTrue(cands)

    def test_skin_prefix_stripped(self):
        base = T.get_sets_by_echo('双极·星升辉铳')
        self.assertTrue(base)
        self.assertEqual(T.get_sets_by_echo('异相·双极·星升辉铳'), base)

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
        self.assertEqual(len(names), 34)
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
