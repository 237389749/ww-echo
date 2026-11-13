#!/usr/bin/env python3
"""底层耦合体检（stdlib-only，不导入项目，不依赖游戏/Qt）。

输入:
  - 仓库内全部 `.py`（排除 `ww-echo-policy-calculator-main/` 与 `__pycache__`）
输出:
  - stdout 或 `--out` 的 Markdown:
      分层矩阵 / 跨层违规 / UI 对 engine 内部模块的 import / Qt 直接依赖 /
      模块级循环 / 可选 import 耗时
  - `--check`: 只对“engine 反向 import 项目代码”这一条硬边界返回 1（当前应为 0）
  - `--timing`: 用当前解释器逐个 import 并计时（需要 requirements 环境）

支撑结论:
  - `docs/COUPLING.md` 的全部数字
  - CHANGELOG 补记 25

用法:
  python tools/analysis/import_coupling.py
  python tools/analysis/import_coupling.py --out logs/analysis/coupling.md --timing

分层:
  engine = ww_engine.*
  shell  = ww_app_shell.*（应用外壳：EngineApp/StartController/overlay/QMessageBox；可依赖 engine）
  domain = src.*（不含 src.task.*）
  task_adapter = src.task.*
  ui = ui.*
  entry = config.py / mainui.py
  tools / tests = tools.* / tests.*
"""
from __future__ import annotations

import argparse
import ast
import collections
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXCLUDE = {"ww-echo-policy-calculator-main"}

LAYERS = ("engine", "shell", "domain", "task_adapter", "ui", "entry", "tools", "tests")

# engine → 非 engine 的唯一例外：组合根 `ww_engine/__init__.py` 可以引用应用外壳
# （`OK.app` 与惰性导出 `EngineApp`）。engine 的其他模块 import shell = 违规。
SHELL_IMPORTERS = {"ww_engine"}


def layer_of(module: str) -> str:
    if module.startswith("ww_engine"):
        return "engine"
    if module.startswith("ww_app_shell"):
        return "shell"
    if module.startswith("src.task"):
        return "task_adapter"
    if module.startswith("src"):
        return "domain"
    if module.startswith("ui"):
        return "ui"
    if module in ("config", "mainui"):
        return "entry"
    if module.startswith("tools"):
        return "tools"
    if module.startswith("tests"):
        return "tests"
    return "other"


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_relative(module: str, level: int, current: str, is_package: bool = False) -> str:
    """相对 import → 绝对模块名。

    坑：`from . import X` 写在 `pkg/__init__.py` 里时，level=1 指的是**包自身**(`pkg`)；
    写在普通模块 `pkg/mod.py` 里才指父包(`pkg`)。`module_name()` 把 `__init__` 剥掉了，
    所以必须由调用方传 `is_package`，否则 `from . import roapi` 会被误记成 `pkg → 父包` 的边
    (2026-11-13 的假边 `ww_engine.rotypes → ww_engine` 就是这么来的，会污染 SCC)。
    """
    if level == 0:
        return module
    parts = current.split(".")
    if not is_package:
        parts = parts[:-1]
    up = level - 1
    if up:
        parts = parts[:-up] if up <= len(parts) else []
    return ".".join(parts + ([module] if module else []))


def build_graph():
    files = [p for p in ROOT.rglob("*.py")
             if not any(x in p.parts for x in EXCLUDE) and "__pycache__" not in str(p)]
    modules = {module_name(p): p for p in files}
    packages = set()
    for m in modules:
        parts = m.split(".")
        for i in range(1, len(parts)):
            packages.add(".".join(parts[:i]))

    edges: set[tuple[str, str]] = set()
    raw_imports: dict[str, set[str]] = collections.defaultdict(set)
    bom: list[str] = []
    for module, path in modules.items():
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            bom.append(module)
        tree = ast.parse(data.decode("utf-8-sig"))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = resolve_relative(node.module or "", node.level or 0, module,
                                        is_package=path.name == "__init__.py")
                for alias in node.names:
                    if alias.name == "*":
                        targets.append(base)
                    else:
                        cand = f"{base}.{alias.name}"
                        targets.append(cand if cand in modules or cand in packages else base)
            for target in targets:
                raw_imports[module].add(target)
                parts = target.split(".")
                for i in range(len(parts), 0, -1):
                    cand = ".".join(parts[:i])
                    if cand in modules and cand != module:
                        edges.add((module, cand))
                        break
    return modules, edges, raw_imports, bom


def strongly_connected(modules, edges):
    """Tarjan SCC; 返回长度 >1 的环。"""
    graph = collections.defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                result.append(sorted(comp))

    for m in modules:
        if m not in index:
            visit(m)
    return result


def timing_table(modules: list[str]) -> list[tuple[str, float | None]]:
    rows = []
    for module in modules:
        code = ("import time\n"
                f"t=time.perf_counter()\nimport {module}\n"
                "print(round(time.perf_counter()-t,3))\n")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                text=True, timeout=120,
            )
            value = float(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 else None
        except Exception:
            value = None
        rows.append((module, value))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timing", action="store_true")
    args = parser.parse_args()

    modules, edges, raw_imports, bom = build_graph()
    by_layer = collections.Counter((layer_of(a), layer_of(b)) for a, b in edges)
    out: list[str] = []

    def emit(line: str = "") -> None:
        out.append(line)

    emit("# 底层耦合体检")
    emit()
    emit(f"- 模块数: **{len(modules)}**，模块级唯一依赖边: **{len(edges)}**")
    emit(f"- 排除目录: `{', '.join(sorted(EXCLUDE))}`")
    if bom:
        emit(f"- [!] 带 UTF-8 BOM 的文件: {', '.join('`' + m + '`' for m in bom)}")
    emit()

    emit("## 1. 分层矩阵（唯一模块对；行=importer，列=imported）")
    emit()
    cols = list(LAYERS)          # 含 engine：外壳→engine 的边（18 条）必须看得见
    emit("| importer \\ imported | " + " | ".join(cols) + " |")
    emit("|---|" + "---:|" * len(cols))
    for row in LAYERS:
        emit(f"| {row} | " + " | ".join(
            "—" if row == c else str(by_layer[(row, c)]) for c in cols) + " |")
    emit()

    emit("## 2. 跨层违规（按严重度）")
    emit()
    violations: list[tuple[str, str, str, str]] = []
    for a, b in sorted(edges):
        la, lb = layer_of(a), layer_of(b)
        if la == "engine" and lb != "engine" and not (lb == "shell" and a in SHELL_IMPORTERS):
            # engine → 非 engine 一律 P0；唯一例外是组合根引用应用外壳（见 SHELL_IMPORTERS）
            violations.append(("P0", "engine 反向依赖项目代码", a, b))
        elif la == "shell" and lb not in ("engine", "shell"):
            violations.append(("P1", "shell 依赖 engine 之外的层", a, b))
        elif la == "domain" and lb in ("engine", "task_adapter", "ui", "entry"):
            violations.append(("P1", "domain 依赖上游", a, b))
        elif la == "task_adapter" and lb in ("ui", "entry"):
            violations.append(("P1", "task_adapter 依赖 UI/entry", a, b))
        elif la == "ui" and lb == "entry":
            violations.append(("P2", "UI 依赖 entry(config)", a, b))
        elif la == "entry" and lb == "task_adapter":
            violations.append(("P2", "entry 依赖 task adapter", a, b))
    if not violations:
        emit("[ok] 没有发现跨层反向依赖。")
    else:
        emit("| 严重度 | 类型 | importer | imported |")
        emit("|---|---|---|---|")
        for sev, kind, a, b in violations:
            emit(f"| {sev} | {kind} | `{a}` | `{b}` |")
    emit()

    emit("## 3. UI 对 engine 内部模块的 import（非根 API）")
    emit()
    internals = sorted((a, b) for a, b in edges
                       if layer_of(a) == "ui" and b.startswith("ww_engine."))
    if internals:
        for a, b in internals:
            emit(f"- `{a}` -> `{b}`")
    else:
        emit("[ok] UI 只 import `ww_engine` 根。")
    emit()

    emit("## 4. Qt / qfluentwidgets 直接依赖")
    emit()
    qt_by_layer: dict[str, list[str]] = collections.defaultdict(list)
    for module, imports in raw_imports.items():
        if any(x.startswith(("PySide6", "qfluentwidgets")) for x in imports):
            qt_by_layer[layer_of(module)].append(module)
    for lay in LAYERS:
        if not qt_by_layer.get(lay):
            continue
        emit(f"- {lay} ({len(qt_by_layer[lay])}): " + ", ".join(f"`{m}`" for m in sorted(qt_by_layer[lay])))
    emit()
    core_qt = [m for m in qt_by_layer.get("engine", [])
               if not (m.startswith("ww_engine.gui") or m.startswith("ww_engine.overlay"))]
    if core_qt:
        emit("> engine 非 GUI 代码里的 Qt 直接依赖: " + ", ".join(f"`{m}`" for m in sorted(core_qt)))
    else:
        emit("[ok] engine 的非 GUI 代码不再直接依赖 Qt（QtWidgets 全在 `ww_app_shell`；"
             "engine 侧只剩 `ww_engine.gui` 里的 `Signal` 中枢）。")
    emit()

    emit("## 5. 模块级循环（SCC）")
    emit()
    cycles = strongly_connected(modules, edges)
    external = [c for c in cycles if any(not m.startswith("ww_engine") for m in c)]
    emit(f"- 长度 >1 的 SCC: **{len(cycles)}** 个（其中涉及非 engine 模块: **{len(external)}** 个）")
    for comp in cycles:
        prefix = "engine/rotypes" if all(m.startswith("ww_engine") for m in comp) else "MIXED"
        head = ", ".join(f"`{m}`" for m in comp[:6])
        more = "" if len(comp) <= 6 else f" …(+{len(comp) - 6})"
        emit(f"- [{prefix}] {len(comp)} 个: {head}{more}")
    emit()

    if args.timing:
        emit("## 6. import 耗时（当前解释器，单次，单位 s）")
        emit()
        emit("| 模块 | 秒 |")
        emit("|---|---:|")
        for module, value in timing_table([
            "src.echo_stats", "src.echo_panel", "src.char_profiles",
            "ww_engine", "src.echo_set_templates", "src.echo_icon_match",
            "src.echo_inventory", "src.echo_combos", "tools.echo_plan",
        ]):
            emit(f"| `{module}` | {value if value is not None else 'n/a'} |")
        emit()

    text = "\n".join(out) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"[ok] wrote {args.out}")
    else:
        print(text)

    hard = [v for v in violations if v[0] == "P0"]
    if hard:
        print(f"[!] engine 反向依赖 {len(hard)} 条", file=sys.stderr)
        return 1 if args.check else 0
    print("[ok] engine 边界干净（无反向 import）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
