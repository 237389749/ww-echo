"""`tools/echo_plan.py` 的命令行校验（2026-11-22 后端审查 B10）。

为什么单独测：以前同一类"输入写错"有两种表现 —— `--cost4` 缺失是友好的 `SystemExit`，
而 `--set-b` 缺失 / 两套相同 / 套装名打错 / `--derive` 非数字 都是**裸 traceback**（exit 1），
脚本化调用只能靠堆栈文本区分"我参数错了"还是"程序有 bug"。这里钉住：一律友好、一行、带指路。

跑法（项目根目录）：
    python -m unittest tests.test_plan_cli -v
"""
import argparse
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import echo_plan as ep  # noqa: E402
from src.echo_combos import PlanRequest  # noqa: E402


def _ns(**kw):
    base = dict(scaling="攻击", mode="5", set_a="隐世回光", set_b="", cost4="",
                top=5, crit="expect", all_levels=False, specialty=[], all_bonus=False,
                energy_min=120.0, energy_slope=0.3, energy_floor=0.85,
                crit_target=100.0, crit_slope=0.4, crit_floor=0.8, derive=[])
    base.update(kw)
    return argparse.Namespace(**base)


class RectifyInputTest(unittest.TestCase):
    def _exit_text(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
            fn(*a, **kw)
        return cm.exception.code, buf.getvalue() + (cm.exception.__str__() or "")

    def test_3plus2_requires_set_b(self):
        code, msg = self._exit_text(ep.build_request, _ns(mode="3+2", cost4="A", set_a="隐世回光"))
        self.assertEqual(code, "3+2 模式必须指定 --set-b(套装 2)")

    def test_3plus2_rejects_same_set(self):
        code, msg = self._exit_text(ep.build_request,
                                    _ns(mode="3+2", cost4="A", set_a="隐世回光", set_b="隐世回光"))
        self.assertIn("不能相同", str(code))

    def test_3plus2_still_requires_cost4(self):
        code, _ = self._exit_text(ep.build_request, _ns(mode="3+2", set_b="轻云出月"))
        self.assertIn("--cost4", str(code))

    def test_unknown_set_name_is_friendly(self):
        req = PlanRequest(mode="5", set_a="不存在的套装")
        code, _ = self._exit_text(ep.check_set_names, req)
        self.assertIn("不在套装模板里", str(code))

    def test_general_is_allowed_as_target(self):
        """`通用` 是合法目标（套装未映射的件落在它下面），不能被名字校验拦掉。"""
        ep.check_set_names(PlanRequest(mode="5", set_a="通用"))      # 不抛即通过

    def test_derive_non_numeric_is_friendly(self):
        code, _ = self._exit_text(ep.parse_derive, "共鸣效率:abc:2:50")
        self.assertIn("必须是数字", str(code))

    def test_derive_valid(self):
        d = ep.parse_derive("共鸣效率:125:2:50")
        self.assertEqual((d.source, d.threshold, d.per_point, d.cap), ("共鸣效率", 125.0, 2.0, 50.0))

    def test_float_bare_still_friendly(self):
        """`--bare` 的坏格式本来就是友好的（对照，确认两处口径一致）。"""
        code, _ = self._exit_text(ep.parse_pairs, ["攻击"], "--bare")
        self.assertIn("键=值", str(code))


class TopOptionTest(unittest.TestCase):
    """C10：`--top 0` 以前照样输出 1 行（combos 里 `max(1, top_k)`），与 help 不符。"""

    def test_top_must_be_positive(self):
        with self.assertRaises(SystemExit) as cm:
            ep.build_request(_ns(top=0))
        self.assertIn("--top", str(cm.exception.code))

    def test_top_one_is_fine(self):
        req = ep.build_request(_ns(top=1))
        self.assertEqual(req.top_k, 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
