"""角色预设(`src/char_profiles.py`): 存取往返 + 与引擎字段的翻译。

不依赖游戏与 Qt; 用临时文件当预设库, 不碰仓库里的 `assets/char_profiles.json`。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.char_profiles import (CRIT_DEFAULTS, ENERGY_DEFAULTS, build_profile,          # noqa: E402
                               corrections_of, delete, derived_of, load_all,
                               to_request_kwargs, upsert)
from src.echo_panel import Correction, DerivedBonus                                    # noqa: E402


class TestCharProfiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "chars.json")

    def tearDown(self):
        self.dir.cleanup()

    def _profile(self):
        return build_profile(
            "攻击",
            {"攻击": 1336, "暴击": 57.3, "共鸣效率": 100},
            [Correction("攻击百分比", 37.5, "配队"), Correction("共鸣效率", 10, "轻云 2 件套")],
            [DerivedBonus(source="共鸣效率", threshold=125, per_point=2, cap=50, label="天赋")],
            specialty=("重击",),
            energy={"min": 120, "slope": 0.30, "floor": 0.85},      # 全默认 → 不该写进 json
            crit={"target": 110, "slope": 0.40, "floor": 0.80},     # target 非默认 → 要写
            plan={"mode": "3+2", "set_a": "息界同调之律", "set_b": "轻云出月", "cost4_owner": "B"})

    def test_build_profile_keeps_only_non_default_thresholds(self):
        prof = self._profile()
        self.assertNotIn("energy", prof)                            # 门槛全默认 → 省掉
        self.assertEqual(prof["crit"], {"target": 110.0})           # 只留改过的那项
        self.assertEqual(prof["specialty"], ["重击伤害加成"])        # 简写已归一
        self.assertEqual(prof["bare"]["攻击"], 1336.0)

    def test_roundtrip_and_delete(self):
        self.assertEqual(load_all(self.path), {})                   # 文件不存在 → 空, 不抛
        upsert("仇远", self._profile(), self.path)
        chars = load_all(self.path)
        self.assertEqual(list(chars), ["仇远"])
        self.assertEqual(chars["仇远"]["plan"]["cost4_owner"], "B")
        self.assertTrue(delete("仇远", self.path))
        self.assertFalse(delete("仇远", self.path))                 # 再删一次返回 False
        self.assertEqual(load_all(self.path), {})

    def test_to_request_kwargs(self):
        kw = to_request_kwargs(self._profile())
        self.assertEqual(kw["allowed_bonus"], ("重击伤害加成",))     # 指定专伤 → 引擎字段
        self.assertEqual(kw["scaling"], "攻击")
        self.assertEqual(kw["mode"], "3+2")
        self.assertEqual(kw["set_a"], "息界同调之律")
        self.assertEqual(kw["cost4_owner"], "B")
        self.assertEqual(kw["crit_target"], 110.0)
        self.assertNotIn("energy_min", kw)                          # 预设没存 → 不覆盖默认
        # 空预设 → 什么都不给(调用方用 PlanRequest 默认值)
        self.assertEqual(to_request_kwargs({}), {})

    def test_corrections_and_derived(self):
        prof = self._profile()
        corr = corrections_of(prof)
        self.assertEqual([(c.key, c.value, c.source) for c in corr],
                         [("攻击百分比", 37.5, "配队"), ("共鸣效率", 10.0, "轻云 2 件套")])
        der = derived_of(prof)
        self.assertEqual(len(der), 1)
        self.assertEqual((der[0].source, der[0].threshold, der[0].per_point, der[0].cap),
                         ("共鸣效率", 125.0, 2.0, 50.0))
        self.assertEqual(derived_of({}), [])                        # 缺字段 → 空列表, 不报错

    def test_defaults_are_the_engine_defaults(self):
        """门槛默认值必须与 `PlanRequest` 一致(不一致会让"省掉默认项"变成悄悄改口径)。"""
        from src.echo_combos import PlanRequest
        req = PlanRequest()
        self.assertEqual(ENERGY_DEFAULTS, {"min": req.energy_min, "slope": req.energy_slope,
                                           "floor": req.energy_floor})
        self.assertEqual(CRIT_DEFAULTS, {"target": req.crit_target, "slope": req.crit_slope,
                                         "floor": req.crit_floor})

    def test_repo_profiles_file_is_valid(self):
        """仓库里的 assets/char_profiles.json(用户数据)必须能被解析, 且每个角色都能翻译成请求字段。"""
        chars = load_all()
        if not chars:
            self.skipTest("仓库里还没有角色预设")
        for name, prof in chars.items():
            with self.subTest(name=name):
                self.assertTrue(prof.get("scaling"), f"{name} 缺缩放属性")
                self.assertIsInstance(to_request_kwargs(prof), dict)
                corrections_of(prof)
                derived_of(prof)


if __name__ == "__main__":
    unittest.main()
