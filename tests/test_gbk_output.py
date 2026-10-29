"""CLI / logger 输出的字符必须是 GBK(cp936) 可编码 —— 否则 Windows 原生控制台会 UnicodeEncodeError。

动机（2026-10-29 实际踩到三次）：`offline_eval_report.py` 的 `✓`、`echo_plan.py` 的 `⚠` 与「第1名 −x%」的 `−`、
`EnhanceEchoTask` 渐进路径的 `✅` —— 字符本身没错，但 cp936 编不出来 → 命令在**打印阶段**崩（结果已经算完），
stderr 只留一条 "--- Logging error ---"，看起来像"跑失败"。

只扫**会走到 stdout / ok Logger(控制台)** 的调用：`print` / `log_info` / `log_warning` / `log_error` / `_log`。
Qt 渲染（`_append_log`）与报告 HTML **不在此列** —— 它们没有 cp936 约束（`⚠`/`✔`/`✘` 在那里是刻意保留的）。

跑法（项目根目录）:
    python -m unittest discover -s tests -v
"""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "logs", ".venv314", "build", "dist"}

# 这些函数名把字符串送到 stdout / ok 的 Logger（控制台 handler 用 cp936）
TARGET_CALLS = {"print", "log_info", "log_warning", "log_error", "_log"}


def _iter_py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _gbk_bad(text: str) -> str:
    bad = []
    for c in sorted(set(text)):
        if ord(c) <= 127:
            continue
        try:
            c.encode("gbk")
        except UnicodeEncodeError:
            bad.append(c)
    return "".join(bad)


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


class TestGbkSafeOutput(unittest.TestCase):
    def test_cli_and_logger_strings_are_gbk_encodable(self):
        problems = []
        for path in _iter_py_files():
            try:
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or _call_name(node) not in TARGET_CALLS:
                    continue
                for arg in node.args:
                    for sub in ast.walk(arg):
                        if not (isinstance(sub, ast.Constant) and isinstance(sub.value, str)):
                            continue
                        bad = _gbk_bad(sub.value)
                        if bad:
                            rel = os.path.relpath(path, ROOT).replace("\\", "/")
                            problems.append(f"{rel}:{sub.lineno} {bad!r} | {sub.value[:60]!r}")
        self.assertEqual(problems, [], msg=(
            "以下 print/logger 字符串含 GBK 编不出的字符（控制台会 UnicodeEncodeError）:\n  "
            + "\n  ".join(problems)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
