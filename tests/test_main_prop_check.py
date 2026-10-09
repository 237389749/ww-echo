"""L2 的单元测试: COST 解析 / 官方管理方案主属性判定 / `evaluate_one` 的可选字段是**加法**。

跑法(项目根目录):
    python -m unittest discover -s tests -v
    python tests/test_main_prop_check.py

口径依据: `PhantomManagePlanV2`(= 游戏内置「声骸管理方案」) 按 (套装, COST) 给出主属性的
保留组/丢弃组(PropId), 数据由 `tools/gen_echo_data.py` 生成到 `assets/gamedata/echo_data.json`。
COST 的两种 OCR 形态与可用率见 `parse_cost` 的注释(219 张真实面板实测)。
"""

import os
import sys
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.task.EnhanceEchoTask import EnhanceEchoTask, parse_cost  # noqa: E402
from src.echo_set_templates import load_gamedata                  # noqa: E402

Box = namedtuple('Box', 'name x y width')          # 与 ok-script 的文本框同名属性(最小子集)


def _task():
    t = EnhanceEchoTask.__new__(EnhanceEchoTask)   # 只要纯计算方法, 不跑 __init__
    t.config = {'当前套装': '通用'}
    return t


class TestParseCost(unittest.TestCase):

    def test_merged_box(self):
        for text, want in (('COST 4', 4), ('COST4', 4), ('COST 3', 3), ('COST1', 1), ('COST 1', 1)):
            with self.subTest(text=text):
                self.assertEqual(parse_cost([Box(text, 1330, 248, 117)]), want)

    def test_label_only_with_digit_on_same_row(self):
        # 实测 102/219 张只读到标签 'COST' → 取同行右侧的数字框
        boxes = [Box('COST', 1330, 248, 85), Box('4', 1425, 250, 20), Box('22.0%', 1400, 460, 40)]
        self.assertEqual(parse_cost(boxes), 4)

    def test_ignores_digits_on_other_rows(self):
        boxes = [Box('COST', 1330, 248, 85), Box('3', 1425, 460, 20)]
        self.assertIsNone(parse_cost(boxes))

    def test_none_when_no_cost(self):
        self.assertIsNone(parse_cost([]))
        self.assertIsNone(parse_cost([Box('攻击', 1326, 454, 104), Box('150', 1400, 454, 40)]))


class TestDedupKey(unittest.TestCase):
    """去重签名: 名字里的间隔号/空白差异不该让同一只被记两次(实测 #38/#44 就是这么来的)。"""

    ROWS = [("暴击", "22.0%"), ("攻击", "150"), ("暴击", "6.9%")]

    def test_punctuation_variants_are_equal(self):
        k1 = EnhanceEchoTask.dedup_key("双极·渊陨重锋", self.ROWS)
        k2 = EnhanceEchoTask.dedup_key("双极・渊陨重锋", self.ROWS)     # OCR 读成全角中点
        k3 = EnhanceEchoTask.dedup_key(" 双极 · 渊陨重锋 ", self.ROWS)
        self.assertEqual(k1, k2)
        self.assertEqual(k1, k3)

    def test_different_values_still_differ(self):
        # 注: 主属性行的原始值也会被 snap 到词条档位表(150/100 都归到最高档 60), 所以这里用**词条**区分
        a = EnhanceEchoTask.dedup_key("甲", [("暴击", "22.0%"), ("暴击", "6.9%")])
        b = EnhanceEchoTask.dedup_key("甲", [("暴击", "22.0%"), ("暴击", "9.3%")])
        self.assertNotEqual(a, b)


class TestReadCostBadge(unittest.TestCase):
    """COST 角标**单区放大重读**(全屏 1× 漏检数字时的兜底; 实测 20261008 那批 27/135 会漏)。

    这里用假任务只验证"截对了区域 + 放大了 + 解析结果对" —— OCR 本身不进单测(慢且不确定),
    真实数据上的效果见 `tools/...` 与 eval_rules/CHANGELOG 记录的 27/27 复现实验。
    """

    class _Fake:
        def __init__(self, boxes, shape=(1200, 1920, 3)):
            import numpy as np
            self.frame = np.zeros(shape, dtype=np.uint8)
            self.boxes = boxes
            self.calls = []

        def ocr(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return list(self.boxes)

    def test_roi_and_upscale(self):
        f = self._Fake([Box('COST 3', 10, 10, 100)])
        self.assertEqual(EnhanceEchoTask.read_cost_badge(f), 3)
        (_args, kwargs), = f.calls
        roi = kwargs.get('frame')
        self.assertIsNotNone(roi)                       # 传的是自己截好的图, 不再是整帧
        # 帧 1920x1200 上 x 1315..1520 / y 228..300 → 205x72, 放大 3×
        self.assertEqual(roi.shape[:2], (216, 615))

    def test_merged_and_split_forms(self):
        for boxes, want in ([[Box('COST1', 0, 0, 100)], 1],
                            [[Box('COST 4', 0, 0, 100)], 4],
                            [[Box('COST', 0, 0, 90), Box('3', 120, 2, 20)], 3]):
            with self.subTest(boxes=[b.name for b in boxes]):
                self.assertEqual(EnhanceEchoTask.read_cost_badge(self._Fake(boxes)), want)

    def test_no_frame_or_garbage(self):
        self.assertIsNone(EnhanceEchoTask.read_cost_badge(self._Fake([], shape=(0, 0, 3))))
        self.assertIsNone(EnhanceEchoTask.read_cost_badge(self._Fake([Box('暴击', 0, 0, 50)])))



class TestCheckMainProp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if load_gamedata() is None:
            raise unittest.SkipTest('无 assets/gamedata/echo_data.json')

    def test_lock_group_ok(self):
        # 4C: 官方两组都是暴击/暴伤(治疗套 4C 是治疗加成)
        self.assertEqual(EnhanceEchoTask.check_main_prop('凝夜白霜', 4, [('暴击', '22.0%')])['state'], 'ok')
        self.assertEqual(EnhanceEchoTask.check_main_prop('隐世回光', 4, [('治疗效果加成', '26.4%')])['state'], 'ok')
        # 3C: 导电套锁导电(24)
        self.assertEqual(EnhanceEchoTask.check_main_prop('衔梦照世之心', 3, [('导电伤害加成', '30.0%')])['state'], 'ok')
        # 1C: 锁固定攻击(10007)
        self.assertEqual(EnhanceEchoTask.check_main_prop('凝夜白霜', 1, [('攻击', '150')])['state'], 'ok')

    def test_discard_group_off(self):
        # 导电套的 3C 丢弃组 = 其余五个元素
        self.assertEqual(EnhanceEchoTask.check_main_prop('衔梦照世之心', 3, [('热熔伤害加成', '30.0%')])['state'], 'off')
        self.assertEqual(EnhanceEchoTask.check_main_prop('镜影流电之瞬', 3, [('气动伤害加成', '30.0%')])['state'], 'off')

    def test_ocr_prefix_noise_still_matches(self):
        # 面板 OCR 会给主属性名带上图标误读前缀(X攻击/父攻击/茶暴击伤害/💥暴击); 最长优先匹配不受影响。
        # 注: 攻击(10007)在 4C 的方案里既不在保留组也不在丢弃组 → other; 它在 1C 才是保留项。
        cases = [('X攻击', 1, '攻击', 'ok'), ('父攻击', 1, '攻击', 'ok'),
                 ('茶暴击伤害', 4, '暴击伤害', 'ok'), ('发暴击伤害', 4, '暴击伤害', 'ok'),
                 ('💥暴击', 4, '暴击', 'ok'), ('☆暴击', 4, '暴击', 'ok')]
        for raw, cost, prop, state in cases:
            with self.subTest(raw=raw, cost=cost):
                got = EnhanceEchoTask.check_main_prop('凝夜白霜', cost, [(raw, '22.0%')])
                self.assertEqual((got['prop'], got['state']), (prop, state))

    def test_longest_name_wins(self):
        # `暴击伤害` 必须先于 `暴击` 命中(否则暴伤会被当成暴击)
        got = EnhanceEchoTask.check_main_prop('凝夜白霜', 4, [('暴击伤害', '44.0%')])
        self.assertEqual(got['prop'], '暴击伤害')
        self.assertEqual(got['prop_id'], 9)

    def test_other_and_unknown(self):
        # 4C 的 1C 词条(攻击 10007)不在 4C 的保留/丢弃组里 → other(合法但官方未表态)
        self.assertEqual(EnhanceEchoTask.check_main_prop('凝夜白霜', 4, [('攻击', '150')])['state'], 'other')
        # 认不出的名字 → unknown; 无入参/无方案 → None
        self.assertEqual(EnhanceEchoTask.check_main_prop('凝夜白霜', 4, [('ZZZ', '1')])['state'], 'unknown')
        self.assertIsNone(EnhanceEchoTask.check_main_prop('凝夜白霜', 4, None))
        self.assertIsNone(EnhanceEchoTask.check_main_prop('凝夜白霜', None, [('暴击', '22.0%')]))
        self.assertIsNone(EnhanceEchoTask.check_main_prop('不存在的套装', 4, [('暴击', '22.0%')]))


class TestEvaluateOneIsAdditive(unittest.TestCase):
    """`evaluate_one` 的新字段必须是**加法**: 不传主属性/COST 时记录里一个键都不多。"""

    STATS = [('暴击', 8.1), ('暴击伤害', 16.2), ('攻击百分比', 9.4), ('共鸣效率', 9.2), ('攻击', 40.0)]

    def test_without_new_inputs_keys_absent(self):
        rec = _task().evaluate_one('测试声骸', self.STATS, '凝夜白霜', 'icon')
        for key in ('cost', 'main_props', 'plan_check'):
            self.assertNotIn(key, rec)

    def test_with_new_inputs_keys_added(self):
        rec = _task().evaluate_one('测试声骸', self.STATS, '凝夜白霜', 'icon',
                                   main_props=[('暴击', '22.0%'), ('攻击', '150')], cost=4)
        self.assertEqual(rec['cost'], 4)
        self.assertEqual([m['name'] for m in rec['main_props']], ['暴击', '攻击'])
        self.assertEqual(rec['main_props'][0]['value'], 22.0)
        self.assertEqual(rec['plan_check']['state'], 'ok')
        self.assertEqual(rec['plan_check']['plan'], {'lock': [8, 9], 'discard': []})

    def test_cost_only(self):
        rec = _task().evaluate_one('测试声骸', self.STATS, '凝夜白霜', 'icon', cost=4)
        self.assertEqual(rec['cost'], 4)
        self.assertNotIn('main_props', rec)
        self.assertNotIn('plan_check', rec)


if __name__ == '__main__':
    unittest.main(verbosity=2)
