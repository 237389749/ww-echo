"""解释器下界与依赖锁的守卫（2026-11-18）。

背景: 文档里曾写"Python 3.11+"，实际那是 `numpy 2.4`（opencv/openvino 的**传递依赖**）
的 Requires-Python；真正的下界是 `openvino 2026` / `PySide6 6.12` 要求的 **3.10**。
这里钉住三件事，防止以后又把"环境解析结果"写成"项目要求"：

① requirements.txt 的**直接依赖全部 `==`**（且不写 numpy —— 它是传递依赖）；
② `pyproject.toml` 的 `requires-python` 与文档口径一致（3.10+）；
③ `mainui.py` 在 import 之前就做版本检查（装错版本立刻报错，而不是崩在 Qt 里）。
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FLOOR = (3, 10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8-sig') as f:
        return f.read()


class TestRequirementsPinned(unittest.TestCase):

    def _deps(self):
        deps = []
        for line in _read('requirements.txt').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            deps.append(line)
        return deps

    def test_all_direct_deps_are_exactly_pinned(self):
        loose = [d for d in self._deps() if '==' not in d]
        self.assertEqual(loose, [], msg=f'直接依赖必须用 == 钉死: {loose}')

    def test_transitive_numpy_is_not_pinned_here(self):
        """numpy 是 opencv/openvino 传来的；把它写进 requirements 会把 3.11 门槛固化成项目要求。"""
        self.assertFalse([d for d in self._deps() if d.lower().startswith('numpy')])


class TestDeclaredFloor(unittest.TestCase):

    def test_pyproject_declares_floor(self):
        txt = _read('pyproject.toml')
        self.assertIn('requires-python = ">=3.10"', txt)

    def test_mainui_checks_version_before_imports(self):
        src = _read(os.path.join('mainui.py'))
        i_guard = src.find('sys.version_info < (3, 10)')
        self.assertGreater(i_guard, 0, msg='mainui.py 缺少 3.10 版本检查')
        i_qt = src.find('from PySide6')
        self.assertLess(i_guard, i_qt, msg='版本检查必须在 import PySide6 之前')

    def test_docs_do_not_claim_311_floor(self):
        for rel in ('README.md', os.path.join('docs', 'BASELINE.md')):
            txt = _read(rel)
            self.assertNotIn('**3.11+**', txt, msg=f'{rel} 仍把 3.11 写成下界')
            self.assertIn('3.10', txt, msg=f'{rel} 应写明 3.10 下界及其依据')


class TestSyntaxFloorNotAboveDeclared(unittest.TestCase):
    """代码语法必须能在声明的下界上解析（防"文档说 3.10、代码用 3.11 语法"）。"""

    def test_all_py_modules_parse_with_floor(self):
        import ast
        import pathlib
        bad = []
        for rel in ('mainui.py', 'config.py', 'src', 'ui', 'ww_engine', 'ww_app_shell', 'tools', 'tests'):
            p = pathlib.Path(ROOT) / rel
            files = [p] if p.is_file() else [f for f in p.rglob('*.py') if '__pycache__' not in str(f)]
            for f in files:
                try:
                    ast.parse(f.read_text(encoding='utf-8-sig'), filename=str(f),
                              feature_version=FLOOR)
                except SyntaxError as e:
                    bad.append((str(f), e.lineno, e.msg))
        self.assertEqual(bad, [], msg=f'有文件用到比 {FLOOR} 更新的语法: {bad[:5]}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
