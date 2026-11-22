"""角色预设(`src/char_profiles.py`): 存取往返 + 与引擎字段的翻译。

不依赖游戏与 Qt; 用临时文件当预设库, 不碰仓库里的 `assets/char_profiles.json`。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.char_profiles import (CRIT_DEFAULTS, ENERGY_DEFAULTS, THRESHOLD_FIELDS,      # noqa: E402
                               ProfileFileError, apply_thresholds, build_profile,
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

    # ── A2(2026-11-22 后端审查): 坏文件不许被"读成空"后覆盖 ──────────────────

    def test_corrupt_file_refuses_to_overwrite(self):
        """带 BOM / 半截 JSON 的文件: `upsert` 必须**报错且原文件字节不变**。

        旧实现把解析失败当成"没有预设"→ `upsert` 用 1 条覆盖全文件(实测 A/B/C 三个角色全丢)。
        """
        upsert("A", {"scaling": "攻击"}, self.path)
        upsert("B", {"scaling": "生命"}, self.path)
        with open(self.path, "rb") as f:
            raw = f.read()
        with open(self.path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + raw)          # 记事本 "UTF-8 带 BOM"
        with open(self.path, "rb") as f:
            before = f.read()
        with self.assertRaises(ProfileFileError):
            upsert("新角色", {"scaling": "攻击"}, self.path)
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before, "坏文件被改写了 —— 用户预设已丢")
        self.assertEqual(load_all(self.path), {})  # 展示路径仍不崩(只告警)

    def test_corrupt_file_refuses_delete(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"version": 1, "chars": {"A": ')   # 半截 JSON
        with self.assertRaises(ProfileFileError):
            delete("A", self.path)

    def test_upsert_keeps_existing_and_saves_atomically(self):
        upsert("A", {"scaling": "攻击"}, self.path)
        upsert("B", {"scaling": "生命"}, self.path)
        self.assertEqual(sorted(load_all(self.path)), ["A", "B"])
        self.assertFalse(os.path.exists(self.path + ".tmp"), "临时文件没清掉")

    # ── A3(2026-11-22 后端审查): 预设里的门槛必须真的进请求 ────────────────────

    def _ns(self, **kw):
        import argparse
        ns = argparse.Namespace(energy_min=120.0, energy_slope=0.30, energy_floor=0.85,
                                crit_target=100.0, crit_slope=0.40, crit_floor=0.80,
                                all_levels=False)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_apply_thresholds_loads_all_saved_fields(self):
        prof = {"energy": {"min": 110, "slope": 0.5, "floor": 0.7},
                "crit": {"target": 90, "slope": 0.2, "floor": 0.6},
                "max_level_only": False}
        ns = self._ns()
        applied = apply_thresholds(ns, prof)
        self.assertEqual((ns.energy_min, ns.energy_slope, ns.energy_floor), (110.0, 0.5, 0.7))
        self.assertEqual((ns.crit_target, ns.crit_slope, ns.crit_floor), (90.0, 0.2, 0.6))
        self.assertTrue(ns.all_levels)             # max_level_only=False ⇔ --all-levels
        self.assertEqual(len(applied), 7)

    def test_apply_thresholds_explicit_cli_wins(self):
        prof = {"energy": {"min": 110}, "crit": {"target": 90}, "max_level_only": False}
        ns = self._ns()
        applied = apply_thresholds(ns, prof, given=lambda f: f in ("energy-min", "all-levels"))
        self.assertEqual(ns.energy_min, 120.0)     # 显式给了 → 保留命令行值
        self.assertFalse(ns.all_levels)
        self.assertEqual(ns.crit_target, 90.0)     # 没给 → 听预设
        self.assertNotIn("energy_min", applied)
        self.assertNotIn("all_levels", applied)

    def test_every_translatable_field_is_consumed_by_cli(self):
        """防"再加一个字段又漏接线": `to_request_kwargs` 能吐出的键, 必须有归属。

        门槛 7 项由 `apply_thresholds` 吃掉; 其余(bare/补正/专伤/配装)在 CLI 里走另一条路径。
        新增字段时这张表也要一起改 —— 这条断言就是为了让人被迫改。
        """
        sample = {"specialty": ["重击"], "max_level_only": True, "scaling": "攻击",
                  "energy": {"min": 1, "slope": 1, "floor": 1},
                  "crit": {"target": 1, "slope": 1, "floor": 1},
                  "plan": {"mode": "5", "set_a": "a", "set_b": "b", "cost4_owner": "A"}}
        keys = set(to_request_kwargs(sample))
        threshold_attrs = {a for _f, a in THRESHOLD_FIELDS} | {"max_level_only"}
        elsewhere = {"allowed_bonus", "scaling", "mode", "set_a", "set_b", "cost4_owner"}
        self.assertEqual(keys - threshold_attrs - elsewhere, set(),
                         "to_request_kwargs 新增了字段但 CLI 没人消费")


if __name__ == "__main__":
    unittest.main()
