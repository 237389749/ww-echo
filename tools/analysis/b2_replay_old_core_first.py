"""用"旧的 `_core_first` 兜底(全部键, 含 0 权重)"重跑 B2, 证明那条修正对这份数据集零影响。

输入: `logs/eval_debug/20260911_110817/`（B2 素材, 未入库）+ 当前 `assets/echo_set_templates.json`
输出: stdout 判定分布; 覆盖 `eval_report.html`（跑完请用当前代码再跑一次 `tools/offline_eval_report.py` 复原）
支撑: CHANGELOG 补记 21 的证据 ②——"`_core_first` 改成权重>0 之后分布完全没变, 所以 B2 的分布变化与它无关"

用法（仓库根）:
    python tools/analysis/b2_replay_old_core_first.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import src.task.EnhanceEchoTask as T                      # noqa: E402
from src.echo_set_templates import load_templates          # noqa: E402


def old_core_first(set_name):
    """2026-10-29 之前的兜底: 模板 weights 字典的全部键（未认的词条也记 0, 但仍算"核心"）。"""
    if not set_name or set_name == "通用":
        return None
    info = load_templates().get(set_name)
    if not info:
        return None
    core = info.get("core_first")
    if core:
        return list(core)
    return list(info["weights"].keys())


T.get_set_core_first = old_core_first      # judge_echo 在模块内按名字取, 替换生效

import tools.offline_eval_report as R                      # noqa: E402

sys.argv = ["offline_eval_report.py"]
raise SystemExit(R.main())
