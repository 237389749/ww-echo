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
# `.scratch` / `.venv`: 本地临时脚本与虚拟环境（都不入库）；`logs`: 运行时产物。
# 少了 `.scratch` 会让本机的一堆一次性脚本把守卫拖红，也让"哪份代码是产品"说不清。
SKIP_DIRS = {".git", "__pycache__", "logs", ".scratch", ".venv", ".venv314", "build", "dist"}

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
        unparsable = []
        for path in _iter_py_files():
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            try:
                with open(path, "rb") as f:
                    raw = f.read()
            except OSError as e:                      # 读不了就报出来, 别静默跳过
                unparsable.append(f"{rel}: 读不出来({e})")
                continue
            if raw.startswith(b"\xef\xbb\xbf"):
                # BOM 会让 `ast.parse` 直接抛 SyntaxError —— 旧版这里的 `except SyntaxError: continue`
                # 于是把整份文件**静默排除**在守卫之外(2026-11-22 后端审查 B6 实测: 2 个入库文件中招)。
                problems.append(f"{rel}: 文件带 UTF-8 BOM(会让本守卫与 ast 类工具失效, 请存成无 BOM)")
            try:
                tree = ast.parse(raw.decode("utf-8-sig"))
            except (SyntaxError, UnicodeDecodeError) as e:
                unparsable.append(f"{rel}: 解析失败({e.__class__.__name__}: {e})")
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
                            problems.append(f"{rel}:{sub.lineno} {bad!r} | {sub.value[:60]!r}")
        self.assertEqual(unparsable, [], msg=(
            "以下文件**没能被本守卫检查**(解析失败/读不出来) —— 不允许静默跳过, 否则守卫形同虚设:\n  "
            + "\n  ".join(unparsable)))
        self.assertEqual(problems, [], msg=(
            "以下 print/logger 字符串含 GBK 编不出的字符（控制台会 UnicodeEncodeError）:\n  "
            + "\n  ".join(problems)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
