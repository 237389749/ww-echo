#!/usr/bin/env python3
"""耦合 P1 的等价性自检：抽取前(旧提交) vs 当前实现的四个纯函数逐例对比。

输入:
  - `git show <ref>:src/task/EnhanceEchoTask.py`（默认 `3e698cf` = P1 之前的最后一个提交；
    落到 `%TEMP%` 后用 importlib 加载，**不改工作区**）
  - 当前 `src/echo_parse.py` / `src/echo_scoring.py`
输出:
  - stdout：每个函数跑了多少例、不一致清单（有则打印 old/new 并退出码 1）
支撑结论:
  - `docs/COUPLING.md` §6「P1：纯函数抽取，不改判定」
  - CHANGELOG 补记 27（score/dedup_key/normalize_stat/parse_number 逐例 0 差异）

覆盖的样本（刻意选边界，不是随机）:
  - `parse_number`: `%` / `％` / 无百分号 / 空串 / 非数字
  - `normalize_stat`: 全部标准词条名 + 已知 OCR 污染变体（图标误读前缀、拆字、技能行）
  - `dedup_key`: 间隔号/空白变体 + 同名不同档位 + 空属性行
  - `compute_weighted_score`: 全部词条的全档位网格 × (None / 通用 / 真实套装 / 不存在的套装)

用法:
  python tools/analysis/p1_equiv_check.py
  python tools/analysis/p1_equiv_check.py --old 3e698cf
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
OLD_FILE = "src/task/EnhanceEchoTask.py"

OCR_NAMES = [
    '暴击', '暴击伤害', '攻击', '攻击百分比', '生命', '防御', '共鸣效率', '普攻伤害加成',
    '重击伤害加成', '共鸣技能伤害加成', '共鸣解放伤害加成',
    '艾攻击', '父攻击', '茶暴击伤害', '发暴击伤害', '共呜效率', '共鸣技伤害加成',
    '器 | 暴击伤害', '使用声骸技能，召唤无归的谬误', '热熔伤害加成', 'ZZZ', '攻',
]
NUMBERS = ['12.4%', '12.4％', '150', '', 'abc', '0.8', ' 6.3 %', '22.0']
DEDUP_CASES = [
    ('双极·渊陨重锋', [('暴击', '22.0%'), ('攻击', '150'), ('攻击', '9.4%'), ('共鸣效率', '10.8%')]),
    ('双极・渊陨重锋', [('暴击', '22.0%'), ('攻击', '150'), ('攻击', '9.4%'), ('共鸣效率', '10.8%')]),
    (' 双极 · 渊陨重锋 ', [('暴击', '22.0%'), ('攻击', '150')]),
    ('甲', [('暴击', '22.0%'), ('暴击', '6.9%')]),
    ('甲', [('暴击', '22.0%'), ('暴击', '9.3%')]),
    ('乙', []),
]


def load_old(ref: str):
    """把 `<ref>:src/task/EnhanceEchoTask.py` 写到临时文件并加载为独立模块。"""
    src = subprocess.check_output(["git", "show", f"{ref}:{OLD_FILE}"], cwd=ROOT).decode("utf-8")
    tmp = pathlib.Path(tempfile.gettempdir()) / f"_p1_old_enhance_{ref.replace('/', '_')}.py"
    tmp.write_text(src, encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("_p1_old_enhance", tmp)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default="3e698cf", help="P1 之前的提交（默认 3e698cf）")
    args = parser.parse_args()

    old = load_old(args.old)
    from src import echo_parse, echo_scoring                    # noqa: E402
    from src.echo_stats import _TIERS                            # noqa: E402
    from src.task.EnhanceEchoTask import EnhanceEchoTask         # noqa: E402

    old_task = old.EnhanceEchoTask.__new__(old.EnhanceEchoTask)
    old_task.config = {'当前套装': '通用'}
    new_task = EnhanceEchoTask.__new__(EnhanceEchoTask)
    new_task.config = {'当前套装': '通用'}

    fails: list[tuple[str, object, object]] = []
    counts: dict[str, int] = {}

    def check(fn: str, label: str, a, b) -> None:
        counts[fn] = counts.get(fn, 0) + 1
        if a != b:
            fails.append((label, a, b))

    for text in NUMBERS:
        check("parse_number", f"{text!r}", old.parse_number(text), echo_parse.parse_number(text))

    for raw in OCR_NAMES:
        for vstr in ('12.4%', '150', '0', ''):
            check("normalize_stat", f"{raw!r},{vstr!r}",
                  old.EnhanceEchoTask._normalize_stat(raw, vstr),
                  echo_parse.normalize_stat(raw, vstr))

    for name, rows in DEDUP_CASES:
        check("dedup_key", name, old.EnhanceEchoTask.dedup_key(name, rows),
              echo_parse.dedup_key(name, rows))

    samples = [
        [(n, f'{v}%') for n, tiers in _TIERS.items() for v in tiers],
        [('暴击', '10.5%'), ('暴击伤害', '21.0%'), ('攻击百分比', '11.6%'),
         ('共鸣效率', '12.4%'), ('普攻伤害加成', '11.6%')],
        [('攻击', '60'), ('生命', '580'), ('防御', '70'), ('共鸣效率', '12.4%'), ('ZZZ', '1')],
        [('治疗', '1'), ('暴击', 'abc')],
        [],
    ]
    for set_name in (None, '通用', '凝夜白霜', '隐世回光', '不存在的套装'):
        for stats in samples:
            label = f"set={set_name}, n={len(stats)}"
            want = old_task.compute_weighted_score(stats, set_name=set_name)
            check("compute_weighted_score", f"task {label}",
                  want, new_task.compute_weighted_score(stats, set_name=set_name))
            check("compute_weighted_score", f"free {label}",
                  want, echo_scoring.compute_weighted_score(stats, set_name))

    total = sum(counts.values())
    print(f"对比 {args.old} -> 当前实现: {total} 例")
    for fn, n in counts.items():
        print(f"  {fn}: {n} 例")
    if fails:
        print(f"[!] 不一致 {len(fails)} 例")
        for label, a, b in fails[:10]:
            print(f"  {label}\n    old={a}\n    new={b}")
        return 1
    print("[ok] 全部一致（纯函数抽取未改口径）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
