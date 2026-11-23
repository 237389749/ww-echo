"""后端 A 批修复的回归守卫（2026-11-22 后端审查 A1/A4）。

为什么单独成文件：这两条都**没有"跑一个函数看返回值"的自然入口** ——
- A1 是"用了错误的落盘 API"（`cv2.imwrite` 对非 ASCII 路径静默返回 False），
  只能靠"产品面不许出现该 API + 真写一张到中文目录"两条一起守；
- A4 是"清理链在异常路径上被跳过"，真实入口要起引擎线程，所以用 AST 守住
  "`destroy()` 在 finally 里" / "`except` 捕到了 BaseException"这两个结构事实。

对应文档：`docs/BACKEND_REVIEW_2026-11-22.md` §2 A1 / A4。
"""
import ast
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import echo_panel_shot                                                    # noqa: E402
from src.task.EnhanceEchoTask import EnhanceEchoTask                               # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _func(rel, name):
    tree = ast.parse(_read(rel))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


class TestImageWriteGuard(unittest.TestCase):
    """A1：产品面的落盘必须走 `imwrite_unicode`（裸 `cv2.imwrite` 在中文路径下静默丢图）。"""

    #: 允许出现的例外（相对路径前缀 → 理由）。**不要随手加**。
    ALLOW_DIRS = (
        ("tools/analysis/", "复现脚本区: 一次性探针, 产物不进交付物"),
        ("ww_engine/", "vendored 引擎: 模板匹配调试图, 只在 debug 模式写 logs/"),
    )

    def _product_py_files(self):
        out = []
        for sub in ("src", "ui"):
            for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, sub)):
                out += [os.path.join(dirpath, fn) for fn in filenames if fn.endswith(".py")]
        tools = os.path.join(ROOT, "tools")
        out += [os.path.join(tools, fn) for fn in os.listdir(tools) if fn.endswith(".py")]
        return out

    def test_no_bare_cv2_imwrite_in_product_code(self):
        bad = []
        for path in self._product_py_files():
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if any(rel.startswith(d) for d, _why in self.ALLOW_DIRS):
                continue
            for i, line in enumerate(_read(rel).splitlines(), 1):
                if "cv2.imwrite(" in line:
                    bad.append(f"{rel}:{i} {line.strip()}")
        self.assertEqual(bad, [], msg=(
            "以下落盘用了裸 cv2.imwrite —— 它对非 ASCII 路径返回 False 且不抛"
            "(Windows 中文用户名 → 报告里的截图全是碎图)。改用 src.echo_panel_shot.imwrite_unicode:\n  "
            + "\n  ".join(bad)))

    def test_imwrite_unicode_writes_into_non_ascii_dir(self):
        """中文目录下真能出图（裸 cv2.imwrite 在同一路径上会返回 False，这就是 A1 的根因）。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "测试中文目录")
            os.makedirs(folder)
            img = np.zeros((12, 12, 3), np.uint8)
            ascii_path = os.path.join(tmp, "ascii.png")
            cn_path = os.path.join(folder, "截图.png")
            self.assertFalse(cv2.imwrite(cn_path, img) and os.path.exists(cn_path),
                             "本机 cv2.imwrite 居然支持非 ASCII 路径 —— A1 的前提变了，回来复核")
            self.assertTrue(echo_panel_shot.imwrite_unicode(cn_path, img))
            self.assertTrue(os.path.exists(cn_path))
            self.assertTrue(cv2.imwrite(ascii_path, img))          # 对照: ASCII 路径本来就没事

    def test_save_fail_frame_reports_empty_on_write_failure(self):
        """写失败必须返回 `''`，否则日志里的"画面已存: xxx"是假证据（A1 的第二半）。"""
        class _FakeTask(EnhanceEchoTask):
            def __init__(self):
                self.logs = []

            @property
            def frame(self):
                return np.zeros((8, 8, 3), np.uint8)

            def log_debug(self, message, notify=False):
                self.logs.append(message)

        task = _FakeTask()
        orig = echo_panel_shot.imwrite_unicode
        try:
            echo_panel_shot.imwrite_unicode = lambda *a, **k: False
            self.assertEqual(task._save_fail_frame(), '', "写失败却返回了路径 → 日志会撒谎")
            echo_panel_shot.imwrite_unicode = lambda *a, **k: True
            path = task._save_fail_frame()
            self.assertTrue(path.endswith("eval_fail_frame.png"))
        finally:
            echo_panel_shot.imwrite_unicode = orig


class TestLifecycleGuard(unittest.TestCase):
    """A4：退出路径也必须跑清理（`destroy()` 在 finally 里、评估侧捕 BaseException）。"""

    def test_executor_destroy_runs_in_finally(self):
        fn = _func("ww_engine/task/TaskExecutor.py", "execute")
        self.assertIsNotNone(fn, "TaskExecutor.execute 不见了")
        finally_calls = []
        for stmt in fn.body:
            if isinstance(stmt, ast.Try):
                for node in stmt.finalbody:
                    finally_calls += [ast.unparse(c.func) for c in ast.walk(node)
                                      if isinstance(c, ast.Call)]
        self.assertIn("self.destroy", finally_calls,
                      "destroy() 不在 execute() 的 finally 里 —— SystemExit 会跳过整条清理链")

    def test_evaluate_only_cleans_up_on_systemexit(self):
        fn = _func("src/task/EnhanceEchoTask.py", "evaluate_only")
        self.assertIsNotNone(fn, "evaluate_only 不见了")
        caught = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                caught |= {ast.unparse(node.type)}
        self.assertIn("BaseException", caught,
                      "evaluate_only 只捕 Exception → 退出时的 SystemExit 会跳过临时目录清理")

    def test_execute_destroys_even_on_system_exit(self):
        """行为验证（不只是结构）：循环里 `sys.exit(0)` 穿透后 `destroy()` 仍要跑。

        这是 A4 的真实失败路径 —— `TaskExecutor.frame`/`sleep` 在退出时就抛 `sys.exit(0)`，
        而 `except Exception` 抓不到它。用未绑定函数把真实现跑在假 self 上，避免起引擎线程。
        """
        from ww_engine.task.TaskExecutor import TaskExecutor

        class _Dummy:
            destroyed = False

            def _execute_loop(self):
                raise SystemExit(0)

            def destroy(self):
                self.destroyed = True

        dummy = _Dummy()
        with self.assertRaises(SystemExit):
            TaskExecutor.execute(dummy)          # type: ignore[arg-type]  # 假 self, 只走 try/finally
        self.assertTrue(dummy.destroyed, "SystemExit 穿透后 destroy() 没跑 —— A4 回来了")


class TestCaptureClose(unittest.TestCase):
    """B13：BitBlt 在切换 capture 时要能真正释放 GDI（`close()` 以前继承基类的 `pass`）。

    真机上的效果是 window DC / memory DC / DIB 只增不减；这里只能守"这个方法真的存在且能跑" ——
    句柄计数需要真机（见 `docs/BACKEND_REVIEW_2026-11-22.md` §8）。
    """

    def test_close_on_empty_method_is_safe(self):
        import threading

        from ww_engine.device.capture_methods.bitblt import BitBltCaptureMethod

        method = object.__new__(BitBltCaptureMethod)
        method.lock = threading.Lock()
        method.contexts = {}
        method.dc_object = method.compatible_dc = method.window_dc = method.bitmap = None
        method.last_hwnd = method.last_width = method.last_height = 0
        method.close()                       # 不抛即通过（真机在这里 ReleaseDC/DeleteObject）
        self.assertEqual(method.contexts, {})
        self.assertIsNone(method.bitmap)


class TestPairProps(unittest.TestCase):
    """`_pair_props` 必须**一直**用"最近邻 + 未用集合"（贪心）。

    2026-11-23 的 rep7 真机报告把这条钉死了：当时试过"数量相等就按行序 zip"，结果 #136/#137
    （+20/4 词条）名/值各多一个噪声（技能描述行 + `COST 3` 拆出来的裸 `3`）**凑巧数量相等** →
    zip 把整列错开一格：截图上是 `冷凝伤害加成 25.2% / 攻击 84 / 攻击 8.6% / 暴击 6.3%`，
    记录成了 `冷凝 3.0 / 攻击 25.2 / 暴击 8.6 / 生命 6.3`。
    """

    @staticmethod
    def _box(name, y):
        from types import SimpleNamespace
        return SimpleNamespace(name=name, y=y)

    def test_normal_panel_pairs_in_order(self):
        props = [self._box("攻击", 100), self._box("暴击", 200)]
        vals = [self._box("150", 110), self._box("6.3%", 190)]
        self.assertEqual(EnhanceEchoTask._pair_props(props, vals),
                         [("攻击", "150"), ("暴击", "6.3%")])

    def test_rep7_shift_case(self):
        """rep7 #136 的真实几何：7 个名（含尾部署性描述行）+ 7 个值（含表头 `COST 3` 的裸 3）。"""
        props = [self._box("冷凝伤害加成", 250), self._box("攻击", 285),
                 self._box("攻击", 320), self._box("暴击", 355),
                 self._box("生命", 390), self._box("普攻伤害加成", 425),
                 self._box("使用声骸技能，召唤车刃镰", 600)]
        vals = [self._box("3", 110), self._box("25.2%", 265), self._box("84", 300),
                self._box("8.6%", 335), self._box("6.3%", 370),
                self._box("8.6%", 405), self._box("9.4%", 440)]
        paired = EnhanceEchoTask._pair_props(props, vals)
        self.assertEqual(paired[0], ("冷凝伤害加成", "25.2%"))    # ← 错位时这里是 ("冷凝伤害加成", "3")
        self.assertEqual(paired[1], ("攻击", "84"))
        self.assertEqual(paired[3], ("暴击", "6.3%"))
        self.assertEqual(paired[5], ("普攻伤害加成", "9.4%"))
        self.assertEqual(paired[6], ("使用声骸技能，召唤车刃镰", "3"))   # 噪声行吃掉表头噪声值

    def test_fewer_values_than_props_fills_zero(self):
        props = [self._box("攻击", 100), self._box("暴击", 200), self._box("声骸技能", 300)]
        vals = [self._box("150", 110), self._box("6.3%", 190)]
        self.assertEqual(EnhanceEchoTask._pair_props(props, vals),
                         [("攻击", "150"), ("暴击", "6.3%"), ("声骸技能", "0")])

if __name__ == "__main__":
    unittest.main(verbosity=2)
