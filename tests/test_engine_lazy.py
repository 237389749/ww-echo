"""引擎根包**惰性导入** + **外壳边界**的守卫。

1. `import ww_engine` 不许拉起 QtWidgets / cv2 / qfluentwidgets / 应用外壳。
   为什么需要：在 `ww_engine/__init__.py` 顶部**加一行重的 import**（例如又把 `FluentIcon`
   或 `EngineApp` 拉回顶部）不会有任何功能错误，只会让每个 `from ww_engine import og` 的调用方
   （UI 启动 / 测试 / 离线工具）付一次 ~0.6 s 的 qfluentwidgets 账单 —— 2026-11 的 P2 就是修这个
   （见 `docs/COUPLING.md` §0.3）。静态扫描抓不到「函数内 import 也是合法写法」，所以这里用**子进程实测
   sys.modules**；再用「惰性名字与直接子模块导入是同一对象」防 `_LAZY_IMPORTS` 映射写错。
2. **只有组合根**（`ww_engine/__init__.py`）可以 import 应用外壳 `ww_app_shell`；engine 其余模块
   一律走 `ww_engine.*` 子模块（`og` 在 `ww_engine.locator`）。2026-11 第三阶段拆壳时就是这么定的。

对应文档：`docs/COUPLING.md` §0.3/§0.4、CHANGELOG 补记 28/29。
"""

import ast
import importlib
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 裸 `import ww_engine` 之后不应出现在 sys.modules 里的重依赖（QtCore 允许：communicate 是 eager 的；
# ww_app_shell 也不许被拉起 —— 外壳只在要开窗口时导入）
HEAVY = ("qfluentwidgets", "cv2", "PIL", "rotypes", "pynput", "ww_app_shell")


class TestLazyRootPackage(unittest.TestCase):

    def test_root_import_does_not_pull_heavy_modules(self):
        """子进程里只 `import ww_engine`，进程内不能出现 HEAVY 里的模块。"""
        code = (
            "import sys\n"
            "import ww_engine\n"
            "heavy = sorted({m.split('.')[0] for m in sys.modules} & set(%r))\n"
            "print('heavy=', heavy)\n"
            "print('qtcore=', 'PySide6.QtCore' in sys.modules)\n" % (HEAVY,)
        )
        try:
            proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                  capture_output=True, text=True, timeout=120)
        except OSError as e:                                   # 受限沙箱里没有子进程管道
            self.skipTest(f"无法起子进程: {e}")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
        self.assertIn("heavy= []", proc.stdout, msg=proc.stdout)
        self.assertIn("qtcore= True", proc.stdout,
                      msg="communicate 应保持 eager（QtCore），否则 UI 侧信号初始化会被推迟")

    def test_all_exports_resolve_to_direct_imports(self):
        """`__all__` 每个名字都能解析；惰性名字必须与直接子模块导入是**同一对象**。"""
        import ww_engine
        lazy = getattr(ww_engine, "_LAZY_IMPORTS", None)
        self.assertIsInstance(lazy, dict, msg="根包丢了 _LAZY_IMPORTS：P2 的约定被破坏")
        for name in ww_engine.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(ww_engine, name), msg=f"根包解析不出 {name}")
                if name in lazy:
                    module, attr = lazy[name]
                    self.assertIs(getattr(ww_engine, name),
                                  getattr(importlib.import_module(module), attr),
                                  msg=f"{name} 的惰性来源与直接导入不是同一对象")
        for name in lazy:
            with self.subTest(missing=name):
                self.assertIn(name, ww_engine.__all__, msg=f"{name} 惰性登记了但没进 __all__")

    def test_only_composition_root_imports_app_shell(self):
        """engine 里只有 `ww_engine/__init__.py`（组合根）可以 import `ww_app_shell`。

        用 AST 只看真正的 import（注释/文档串里提到包名不算）。
        """
        engine = pathlib.Path(ROOT) / "ww_engine"
        root_init = engine / "__init__.py"
        offenders = []
        for path in engine.rglob("*.py"):
            if path == root_init:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    targets = [node.module]
                for t in targets:
                    if t == "ww_app_shell" or t.startswith("ww_app_shell."):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {t}")
        self.assertEqual(offenders, [],
                         msg="engine 子模块不应依赖应用外壳（改用 ww_engine.* 子模块；og 在 ww_engine.locator）")

    def test_shell_does_not_import_engine_root(self):
        """外壳必须依赖 engine 的具体子模块，不能 import 根包（否则形成 根包↔外壳 环）。"""
        shell = pathlib.Path(ROOT) / "ww_app_shell"
        if not shell.exists():
            self.skipTest("没有 ww_app_shell 包")
        offenders = []
        for path in shell.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                hit = (isinstance(node, ast.Import) and any(a.name == "ww_engine" for a in node.names)) or \
                      (isinstance(node, ast.ImportFrom) and node.module == "ww_engine" and not node.level)
                if hit:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [],
                         msg="外壳 import 了 engine 根包 → 根包↔外壳 成环；改用 ww_engine.locator / 子模块")


if __name__ == "__main__":
    unittest.main(verbosity=2)
