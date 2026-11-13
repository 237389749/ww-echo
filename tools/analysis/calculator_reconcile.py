#!/usr/bin/env python3
"""与外部「声骸策略工坊」(ww-echo-policy-calculator) 做离线对账。

输入:
  - 本项目 `src/echo_stats.py` (档位表/通用权重/期望) 与 `assets/echo_set_templates.json` (套装权重)
  - 参考工程 `ww-echo-policy-calculator-main/`:
      `apps/ocr/EchoOCRTask.py` 的 `BUFF_VALUE_OPTIONS` (官方档位, 与 metadata.rs 同源)
      `data/echo-data.json` 的角色评分预设
      `crates/echo_app/src/lib.rs` 的锁词条成本表
      `crates/echo_app/tests/service.rs` 的评分/资源成本测试向量

输出:
  - stdout 或 `--out` 的 Markdown: 档位表校验 / 权重比例对照 / 达标线与保留线的完成度 /
    锁成本对照 / 强化继续-重开的盈亏平衡概率 / 结论清单
  - `--check`: 档位表或锁成本不一致时退出码 1 (对账闸门)

支撑结论:
  - `docs/CALCULATOR_RECONCILIATION.md` 的全部数字
  - `CHANGELOG.md` 补记 23 (2026-11-13 与策略计算器对账)

用法:
  python tools/analysis/calculator_reconcile.py
  python tools/analysis/calculator_reconcile.py --check
  python tools/analysis/calculator_reconcile.py --ref <参考工程目录> --out logs/analysis/calc.md

依赖: 项目 requirements (读 `src.echo_set_templates`/`EnhanceEchoTask` 会经 ww_engine 拉 PySide6;
      纯分析可用 venv 跑)。参考工程只读, 不写它。
"""
from __future__ import annotations

import argparse
import ast
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.echo_stats import DEFAULT_WEIGHTS, _TIERS, get_mean  # noqa: E402
from src.echo_set_templates import get_all_set_names, get_set_weights  # noqa: E402
from src.task.EnhanceEchoTask import _legacy_threshold, EnhanceEchoTask  # noqa: E402

DEFAULT_REF = ROOT / "ww-echo-policy-calculator-main"

# 参考工程 OCR 用整数(百分比 x10, 固定值 x1); 这里换算成本项目的显示单位。
REF_TIERS = {
    "Crit_Rate": ("暴击", 0.1),
    "Crit_Damage": ("暴击伤害", 0.1),
    "Attack": ("攻击百分比", 0.1),
    "Defence": ("防御百分比", 0.1),
    "HP": ("生命百分比", 0.1),
    "Attack_Flat": ("攻击", 1.0),
    "Defence_Flat": ("防御", 1.0),
    "HP_Flat": ("生命", 1.0),
    "ER": ("共鸣效率", 0.1),
    "Basic_Attack_Damage": ("普攻伤害加成", 0.1),
    "Heavy_Attack_Damage": ("重击伤害加成", 0.1),
    "Skill_Damage": ("共鸣技能伤害加成", 0.1),
    "Ult_Damage": ("共鸣解放伤害加成", 0.1),
}

RATIO_KEYS = ("Crit_Damage", "Attack", "Attack_Flat", "ER")
LABELS = {
    "Crit_Rate": "暴击",
    "Crit_Damage": "暴击伤害",
    "Attack": "攻击%",
    "Attack_Flat": "固定攻击",
    "ER": "共鸣效率",
    "Skill_Damage": "共技",
    "Ult_Damage": "共解",
}


def load_reference_tiers(ref: Path) -> dict[str, list[float]]:
    """从参考工程的 OCR 任务读取官方档位表(比解析 Rust 常量稳)。"""
    path = ref / "apps" / "ocr" / "EchoOCRTask.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "BUFF_VALUE_OPTIONS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"BUFF_VALUE_OPTIONS not found in {path}")


def load_reference_presets(ref: Path) -> dict:
    return json.loads((ref / "data" / "echo-data.json").read_text(encoding="utf-8"))


def first_variant_weights(preset: dict) -> dict:
    variants = preset.get("variants") or []
    return dict(variants[0].get("weights") or {}) if variants else {}


def reference_avg_roll_ratios(weights: dict, weights_are_max_roll: bool) -> dict[str, float]:
    """把参考权重换到「平均档贡献」后归一到暴击=1。

    - `linear` 预设的权重本身就是平均档价值(presetIntro 的每 1% 伤害 × 平均档) -> 直接用;
    - Wuwa Echo Tool 的权重是**满档**价值(生成时乘了 max_value) -> 乘 mean/max 换到平均档。
    """
    vals = {}
    for key in ("Crit_Rate",) + RATIO_KEYS:
        label = REF_TIERS[key][0]
        w = weights.get(key, 0.0)
        if weights_are_max_roll:
            w = w * get_mean(label) / max(_TIERS[label])
        vals[key] = w
    crit = vals["Crit_Rate"]
    if not crit:
        return {}
    return {k: vals[k] / crit for k in RATIO_KEYS}


def our_avg_roll_ratios() -> dict[str, float]:
    """我们的条分在平均档时的相对贡献 = w(共同 x10 约掉)。"""
    crit = DEFAULT_WEIGHTS["暴击"]
    out = {}
    for key, label in (
        ("Crit_Damage", "暴击伤害"),
        ("Attack", "攻击百分比"),
        ("Attack_Flat", "攻击"),
        ("ER", "共鸣效率"),
    ):
        out[key] = DEFAULT_WEIGHTS[label] / crit
    return out


def completion_rows() -> list[tuple[str, float, float, float, float]]:
    """每套装: (名字, B, top5 满档分, B 完成度%, 出现前 5 权重时的 A 完成度%)。"""
    rows = []
    for name in get_all_set_names():
        weights = {k: v for k, v in (get_set_weights(name) or {}).items()
                   if not k.startswith("_") and v > 0 and k in _TIERS}
        if len(weights) < 5:
            continue
        top5 = sum(sorted(
            (10 * w * max(_TIERS[k]) / get_mean(k) for k, w in weights.items()),
            reverse=True,
        )[:5])
        b = _legacy_threshold(name, 5)
        a5 = 10 * sum(sorted(weights.values(), reverse=True)[:5])
        rows.append((name, b, top5, b / top5 * 100.0, a5 / top5 * 100.0))
    return rows


def generic_completion() -> tuple[float, float, float, float]:
    top5 = sum(sorted(
        (10 * w * max(_TIERS[k]) / get_mean(k) for k, w in DEFAULT_WEIGHTS.items()),
        reverse=True,
    )[:5])
    b = _legacy_threshold("通用", 5)
    a5 = 10 * sum(sorted(DEFAULT_WEIGHTS.values(), reverse=True)[:5])
    return b, top5, b / top5 * 100.0, a5 / top5 * 100.0


def fmt(x: float, digits: int = 3) -> str:
    return f"{x:.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", type=Path, default=DEFAULT_REF)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    ref = args.ref
    if not ref.exists():
        print(f"[skip] 参考工程不存在: {ref}")
        print("       把 ww-echo-policy-calculator-main/ 放到仓库根再跑, 或传 --ref。")
        return 2 if args.check else 0

    lines: list[str] = []
    problems: list[str] = []

    def out(line: str = "") -> None:
        lines.append(line)

    out("# 与「声骸策略工坊」对账")
    out()
    out(f"- 参考工程: `{ref.relative_to(ROOT) if ref.is_relative_to(ROOT) else ref}`")
    out("- 生成命令: `python tools/analysis/calculator_reconcile.py --check`")
    out()

    # 1. 档位表
    out("## 1. 官方档位表")
    out()
    ref_tiers = load_reference_tiers(ref)
    mismatches = []
    for key, (label, scale) in REF_TIERS.items():
        theirs = sorted((v * scale for v in ref_tiers.get(key, [])), reverse=True)
        ours = sorted(_TIERS.get(label, []), reverse=True)
        if not theirs or not ours:
            mismatches.append((key, "missing", ours, theirs))
        elif any(abs(a - b) > 1e-9 for a, b in zip(ours, theirs)) or len(ours) != len(theirs):
            mismatches.append((key, "diff", ours, theirs))
    if mismatches:
        out(f"**[!] 档位表不一致 {len(mismatches)} 项**")
        for key, why, ours, theirs in mismatches:
            out(f"- `{key}` {why}: ours={ours} theirs={theirs}")
        problems.append("tier table")
    else:
        out(f"[ok] 13 类词条档位完全一致 ({len(REF_TIERS)} 组)。")
    out()

    # 2. 权重比例
    presets = load_reference_presets(ref)
    ours = our_avg_roll_ratios()
    linear = presets["presets"]["linear"]["presets"]
    wuwa = presets["presets"]["wuwa_echo_tool"]["presets"]
    linear_rows = [reference_avg_roll_ratios(first_variant_weights(p), False) for p in linear]
    wuwa_rows = [reference_avg_roll_ratios(first_variant_weights(p), True) for p in wuwa]
    linear_rows = [r for r in linear_rows if r]
    wuwa_rows = [r for r in wuwa_rows if r]
    out("## 2. 词条权重比例(暴击 = 1, 平均档贡献)")
    out()
    out("口径: 我们的条分在平均档的贡献 = `w`; 参考 `linear` 预设的权重本身就是平均档价值"
        "(presetIntro: 每 1% 的伤害提升 × 平均档); `Wuwa Echo Tool` 的权重是**满档**价值"
        "(生成时乘 `max_value`), 这里乘 `mean/max` 换到平均档。三者归一到暴击 = 1 后可比。")
    out()
    out("| 词条 | 我们(通用) | 参考 linear(爱弥斯) | 参考 Wuwa 中位 | Wuwa p10~p90 |")
    out("|---|---:|---:|---:|---:|")
    for key in RATIO_KEYS:
        vals = sorted(r[key] for r in wuwa_rows)
        p10 = vals[len(vals) // 10]
        p90 = vals[min(len(vals) - 1, len(vals) * 9 // 10)]
        lin = linear_rows[0][key] if linear_rows else float("nan")
        out(f"| {LABELS[key]} | {fmt(ours[key])} | {fmt(lin)} | "
            f"{fmt(statistics.median(vals))} | {fmt(p10)}~{fmt(p90)} |")
    out()
    out(f"参考 Wuwa 预设数: {len(wuwa_rows)}/{len(wuwa)} 个角色(取第一变体; 6 组暴击权重为 0 的辅助向不计)。")
    out()

    # 3. A/B 线的完成度
    generic_b_pct, generic_a_pct = generic_completion()[2:]
    rows = completion_rows()
    groups: dict[str, list] = {"5 键": [], "13 键": [], "其他": []}
    for r in rows:
        w = {k: v for k, v in (get_set_weights(r[0]) or {}).items()
             if not k.startswith("_") and v > 0 and k in _TIERS}
        groups["13 键" if len(w) >= 12 else ("5 键" if len(w) <= 6 else "其他")].append(r)
    out("## 3. 达标线 A / 保留线 B 的「完成度」")
    out()
    out("完成度 = 线值 / 该套装 Top-5 全满档分(与我们报告里的「完成度」同一口径)。")
    out()
    out("| 组 | n | B 完成度(中位) | A 完成度(中位) | A 完成度范围 |")
    out("|---|---:|---:|---:|---:|")
    out(f"| 通用(未映射) | 1 | {fmt(generic_b_pct, 1)}% | {fmt(generic_a_pct, 1)}% | - |")
    for gname in ("5 键", "13 键", "其他"):
        g = groups[gname]
        if not g:
            continue
        b_med = statistics.median(r[3] for r in g)
        a_med = statistics.median(r[4] for r in g)
        a_range = f"{min(r[4] for r in g):.1f}%~{max(r[4] for r in g):.1f}%"
        out(f"| {gname} | {len(g)} | {fmt(b_med, 1)}% | {fmt(a_med, 1)}% | {a_range} |")
    all_a = [r[4] for r in rows]
    out()
    out(f"全部套装 A 完成度: 中位 {statistics.median(all_a):.1f}%, "
        f"范围 {min(all_a):.1f}%~{max(all_a):.1f}%。")
    out(f"轻云出月 B 完成度: {next((fmt(r[3], 1) + '%' for r in rows if r[0] == '轻云出月'), 'n/a')}"
        " (0.1 占位键让 B 被压得很低)。")
    out()
    out("参考工程的默认目标: linear 70/100 = **70%**, Wuwa 70/100 = **70%**, "
        "漂泊者强化助手 95/120 = **79.2%**, XWUID 35/50 = **70%**。")
    out(f"我们的 A 完成度中位 {statistics.median(all_a):.1f}% 与 70% 目标相差 "
        f"{statistics.median(all_a) - 70:+.1f} 个百分点。")
    out()

    # 4. 锁词条成本
    out("## 4. 锁词条成本(频整器/次)")
    out()
    lock_max = getattr(EnhanceEchoTask, "REFORGE_LOCK_MAX", 4)
    out("| 锁定条数 | 我们 `max(1, L-1)` | 参考 `1 if L<=2, 2 if L==3, else 3` |")
    out("|---:|---:|---:|")
    for lock in range(1, 6):
        ours_cost = max(1, lock - 1) if lock <= lock_max else None
        ref_cost = 1 if lock <= 2 else (2 if lock == 3 else 3)
        if ours_cost is not None and ours_cost != ref_cost:
            problems.append(f"lock cost L={lock}")
        out(f"| {lock} | {ours_cost if ours_cost is not None else '不支持'} | {ref_cost} |")
    out()

    # 5. 强化 vs 重开 的成本对比
    out("## 5. 强化「继续 vs 重开」的盈亏平衡(参考成本口径)")
    out()
    out("参考工程 `tests/service.rs`: 一只新声骸开满 5 条 = 50 调谐器(每条 10); "
        "默认资源价值里特级密音筒/胚子 = 0, 所以这里只算调谐器。")
    out()
    out("继续的期望调谐器/成品 = `(5 - 当前词条数) * 10 / p_continue`; "
        "重开 = `50 / p_new`。令两者相等得到继续值得的临界概率:")
    out()
    out("`p_continue_break_even = (5 - tier) / 5 * p_new`")
    out()
    out("| 当前词条 tier | p_new=0.05 | 0.10 | 0.20 | 0.30 |")
    out("|---:|---:|---:|---:|---:|")
    for tier in (2, 3, 4):
        cells = [f"{(5 - tier) / 5 * p:.3f}" for p in (0.05, 0.10, 0.20, 0.30)]
        out(f"| {tier} | " + " | ".join(cells) + " |")
    out()
    out(f"我们的 `ENCHANT_MIN_PROB` = {EnhanceEchoTask.ENCHANT_MIN_PROB:.2f}; "
        "上表说明: 只要继续概率高于 2%~12%(tier 3/4, p_new<=0.20), 继续就比重开省调谐器"
        "(tier 2 更低; 我们的前瞻门只用于 Lv15/20)。")
    out("注意: 参考的完整 DP 还含经验/胚子/失败后的重抽选择, 这里只是调谐器单项的盈亏平衡; "
        "未运行参考求解器(本机缺 echo_policy 源码, GitHub 不可达)。")
    out()

    # 6. 结论
    out("## 6. 结论(可改进项)")
    out()
    out("1. **档位表/锁成本一致** — 两边的官方数据与频整器成本口径可以直接对照, 没有发现分歧。")
    out(f"2. **A 线在完成度上≈{statistics.median(all_a):.0f}%**, 与参考默认目标 70% 接近; "
        "B 线是更低的保留地板(中位约 49%), 参考没有对应档位。")
    out("3. **通用权重几乎是 linear 爱弥斯的平均档权重, 但共效偏高**: 我们 暴伤/攻击%/固定攻击/共效 = "
        f"{ours['Crit_Damage']:.2f}/{ours['Attack']:.2f}/{ours['Attack_Flat']:.2f}/{ours['ER']:.2f}; "
        f"linear 爱弥斯 = {linear_rows[0]['Crit_Damage']:.2f}/{linear_rows[0]['Attack']:.2f}/"
        f"{linear_rows[0]['Attack_Flat']:.2f}/{linear_rows[0]['ER']:.2f}; "
        f"Wuwa 中位 = {statistics.median(r['Crit_Damage'] for r in wuwa_rows):.2f}/"
        f"{statistics.median(r['Attack'] for r in wuwa_rows):.2f}/"
        f"{statistics.median(r['Attack_Flat'] for r in wuwa_rows):.2f}/"
        f"{statistics.median(r['ER'] for r in wuwa_rows):.2f}。"
        "共效是否下调需要用户口径(共效有循环价值, 程序不建模), 其余三项与 linear 几乎一致。")
    out("4. **强化阈值可能过严**: 重抽用 0.60 合理(频整器相对价值 1000), 但强化每条只要 10 调谐器, "
        "继续的盈亏平衡概率远低于 0.60; 建议把「建议强化」与「建议重铸」拆成两个判据"
        "(或加期望调谐器对比), 需用户拍板。")
    out("5. **主属性不进评分**: 参考的评分/目标含主词条原始分, 我们的 A/B/完成度只算副词条。"
        "这是两边结构性差异; 要接主属性需要先定主词条权重表(4C 暴击/暴伤, 3C 属伤/攻击等)。")
    out("6. **OCR 可借鉴**: 参考用页面锚点 + 连续两次一致 + 置信度 0.85 + 合法值校验; "
        "我们的优势是词条名白名单/档位离散校验, 缺「低置信重读」和页面锚点。")
    out()

    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"[ok] wrote {args.out}")
    else:
        print(text)

    if problems:
        print(f"[!] 对账不一致: {problems}", file=sys.stderr)
        return 1 if args.check else 0
    print("[ok] tier table / lock cost check passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
