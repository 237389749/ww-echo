"""
一键重建「队伍面板」全套产物（可复现入口）。

输入:
  - eval_report6.json（评估产物，已入库；160 条 / 131 满级）
输出:
  - logs/analysis/team_plan_20261124/                 team_plan.json / report.md / *.csv（默认口径）
  - logs/analysis/team_plan_20261124/pure/            两系数全关（--no-gates）
  - logs/analysis/team_plan_20261124/swap4c/          4C 主词条换暴伤（--swap4c）
  - logs/analysis/team_plan_20261124/swap3c/          3C 属伤换攻击%（--swap3c sigrika32,sigrika5）
  - logs/analysis/team_plan_20261124/team_panel.xlsx  面板账本（10 页）
  - logs/analysis/team_plan_20261124/team_plan.xlsx   分析工作簿
支撑: docs/TEAM_PANEL_SUMMARY_2026-11-24.md §8~§10 的全部数字

两个解释器（这是本仓库的既有现实，不是本脚本引入的）:
  - team_plan.py       需要 cv2   —— 系统 Python（requirements.txt 那套）
  - *_xlsx.py          需要 openpyxl —— 默认 Python 没装，用 --py-xlsx 指定

用法:
  python tools/analysis/build_team_panel.py                    # 全量重建
  python tools/analysis/build_team_panel.py --skip-data        # 只重出两个工作簿
  python tools/analysis/build_team_panel.py --check            # 只检查依赖与输入
  python tools/analysis/build_team_panel.py --py-xlsx "C:/.../python.exe"
  python tools/analysis/build_team_panel.py --values-only      # 账本写数值不写公式
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "logs" / "analysis" / "team_plan_20261124"
INVENTORY = ROOT / "eval_report6.json"

DATA_RUNS = (
    ("默认口径（期望×共效系数）", []),
    ("纯伤害（两系数全关）", ["--no-gates"]),
    ("4C 主词条换暴伤（假设）", ["--swap4c"]),
    ("3C 属伤换攻击%（假设）", ["--swap3c", "sigrika32,sigrika5"]),
)
SUB_DIR = {0: "", 1: "pure", 2: "swap4c", 3: "swap3c"}


def has_module(python: str, module: str) -> bool:
    """`python -c "import X"` 探测；不可执行也当 False。"""
    try:
        r = subprocess.run([python, "-c", f"import {module}"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def pick(python: str, module: str, hint: str) -> str:
    if has_module(python, module):
        return python
    if python != "python" and has_module("python", module):
        print(f"  · 当前解释器没有 {module}，改用 PATH 上的 python")
        return "python"
    raise SystemExit(
        f"找不到带 {module} 的解释器。\n{hint}\n"
        f"  已试: {python}" + ("、python" if python != "python" else "")
    )


def run(cmd: list[str], step: str) -> None:
    print(f"\n[{step}] " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f"步骤失败（退出码 {r.returncode}）：{step}")


def main() -> None:
    ap = argparse.ArgumentParser(description="一键重建队伍面板全套产物")
    ap.add_argument("--py-data", default=sys.executable,
                    help="跑 team_plan.py 的解释器（需要 cv2）；默认当前解释器")
    ap.add_argument("--py-xlsx", default=sys.executable,
                    help="跑两个 xlsx 脚本的解释器（需要 openpyxl）；默认当前解释器")
    ap.add_argument("--skip-data", action="store_true", help="跳过四份 team_plan 数据，只重出工作簿")
    ap.add_argument("--values-only", action="store_true", help="账本写数值而非公式（免重算）")
    ap.add_argument("--check", action="store_true", help="只检查依赖与输入，不执行")
    a = ap.parse_args()

    print(f"仓库根目录: {ROOT}")
    if not INVENTORY.exists():
        raise SystemExit(f"缺输入：{INVENTORY}\n"
                         "这是评估产物；从评估报告目录拷一份过来，或改用 --inventory 的等价文件。")
    print(f"输入: {INVENTORY.name}（{INVENTORY.stat().st_size / 1024:.0f} KB）")

    py_data = pick(a.py_data, "cv2",
                   "  team_plan.py 依赖 cv2（opencv-python）；先 pip install -r requirements.txt。")
    py_xlsx = pick(a.py_xlsx, "openpyxl",
                   "  xlsx 脚本依赖 openpyxl；pip install openpyxl（或 -r tools/analysis/requirements.txt）。")
    print(f"数据解释器: {py_data}")
    print(f"工作簿解释器: {py_xlsx}")
    if a.check:
        print("\n--check 通过：输入与依赖都在。")
        return

    if not a.skip_data:
        for i, (name, extra) in enumerate(DATA_RUNS):
            out = OUT / SUB_DIR[i] if SUB_DIR[i] else OUT
            run([py_data, "tools/analysis/team_plan.py", *extra, "--out", out], name)

    run([py_xlsx, "tools/analysis/team_panel_xlsx.py",
         *(["--values-only"] if a.values_only else [])], "面板账本")
    run([py_xlsx, "tools/analysis/team_plan_xlsx.py",
         OUT / "team_plan.json", OUT / "team_plan.xlsx"], "分析工作簿")

    print("\n完成。产物：")
    for rel in ("team_plan.json", "report.md", "team_panel.xlsx", "team_plan.xlsx",
                "pure/team_plan.json", "swap4c/team_plan.json", "swap3c/team_plan.json"):
        p = OUT / rel
        print(f"  {'OK ' if p.exists() else 'MISS'} {p.relative_to(ROOT)}"
              + (f"  {p.stat().st_size / 1024:.0f} KB" if p.exists() else ""))
    if not a.values_only:
        print("\n提示：账本里的公式没有缓存值，用 Excel/WPS/LibreOffice 打开一次会重算；"
              "要在不支持重算的查看器里看，加 --values-only。")


if __name__ == "__main__":
    main()
