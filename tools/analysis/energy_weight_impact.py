#!/usr/bin/env python3
r"""共效口径影响面：`DEFAULT_WEIGHTS` 0.5 vs 37 套模板 0.6 —— 改哪一边、影响哪些判定。

输入:
  - 评估报告 JSON（默认 `eval_report6.json`；2026-11-20 真机 160 条，含 set/stats/main_props/level）
  - 当前 `assets/echo_set_templates.json` + `src.echo_stats.DEFAULT_WEIGHTS`
输出:
  - stdout 摘要 + `logs/analysis/energy_weight_impact.md`（逐场景分布 / 判定变化 / B 线变化）
支撑结论:
  - `docs/SESSION_2026-11-20.md` §11-2「共效口径 0.5 vs 0.6 待拍板」
  - 只做**影响面测量**，不改任何配置；拍板后再改 `echo_set_templates.json` / `DEFAULT_WEIGHTS`

口径:
  - 每个场景都重跑一遍 `evaluate_one`（与线上报告同一份评分+判定），只比较分数与判定。
  - B 线（保留地板）单独用 `_legacy_threshold(set, 5)` 算：它吃"该套装权重升序最低 4 条"，
    共效 0.6→0.5 在 5 键套上是 20.5→19.5、6 键套 17.5→16.5 —— 这个方向和"降评分"是同向还是反向，
    正是要量出来的东西。
用法:
  python tools/analysis/energy_weight_impact.py [eval_report6.json]
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import echo_score_sim                                          # noqa: E402
from src.echo_set_templates import load_templates                       # noqa: E402
from src.echo_stats import DEFAULT_WEIGHTS                              # noqa: E402
from src.task.EnhanceEchoTask import EnhanceEchoTask, _legacy_threshold  # noqa: E402

ENERGY = '共鸣效率'
task = EnhanceEchoTask.__new__(EnhanceEchoTask)     # 只借用纯计算方法, 不跑 __init__
task.config = {'当前套装': '通用'}


# ── 权重快照 / 恢复（同一进程里跑多个场景，必须每次都从干净状态开始） ──────────────
def snapshot() -> tuple:
    return (dict(DEFAULT_WEIGHTS),
            {n: dict(info['weights']) for n, info in load_templates().items()})


def restore(snap: tuple) -> None:
    default, templates = snap
    DEFAULT_WEIGHTS.clear()
    DEFAULT_WEIGHTS.update(default)
    for name, w in templates.items():
        cur = load_templates()[name]['weights']
        cur.clear()
        cur.update(w)
    echo_score_sim._cache.clear()        # 分位/完成度按套装名缓存，权重变了必须清


def sets_with_energy(value: float) -> list[str]:
    return [n for n, info in load_templates().items()
            if abs(info['weights'].get(ENERGY, 0.0) - value) < 1e-9]


# ── 场景 ────────────────────────────────────────────────────────────────────────
def sc_baseline() -> str:
    return '不改（现状）'


def sc_default_06() -> str:
    DEFAULT_WEIGHTS[ENERGY] = 0.6
    return '只把通用表 DEFAULT_WEIGHTS 共效 0.5→0.6'


def sc_tpl_05() -> str:
    names = sets_with_energy(0.6)
    for n in names:
        load_templates()[n]['weights'][ENERGY] = 0.5
    return f'只把 {len(names)} 套模板共效 0.6→0.5（= 统一 0.5）'


def sc_tpl_06() -> str:
    names = sets_with_energy(0.5)
    for n in names:
        load_templates()[n]['weights'][ENERGY] = 0.6
    return f'只把 {len(names)} 套（听唤）共效 0.5→0.6'


def sc_all_06() -> str:
    DEFAULT_WEIGHTS[ENERGY] = 0.6
    names = sets_with_energy(0.5)
    for n in names:
        load_templates()[n]['weights'][ENERGY] = 0.6
    return f'统一 0.6：通用表 + {len(names)} 套（听唤）0.5→0.6'


def sc_ying_06() -> str:
    names = sets_with_energy(1.2)
    for n in names:
        load_templates()[n]['weights'][ENERGY] = 0.6
    return f'隐世回光共效 1.2→0.6（{len(names)} 套）'


SCENARIOS = [sc_baseline, sc_default_06, sc_tpl_05, sc_tpl_06, sc_all_06, sc_ying_06]


# ── 重放 ────────────────────────────────────────────────────────────────────────
def replay(records: list[dict]) -> list[dict]:
    out = []
    for rec in records:
        stats = [(s['name'], float(s['value'])) for s in (rec.get('stats') or [])]
        mains = [(m['name'], str(m['value'])) for m in (rec.get('main_props') or [])]
        out.append(task.evaluate_one(rec.get('name') or '', stats, rec.get('set') or '通用',
                                     rec.get('set_src') or 'default',
                                     main_props=mains or None, cost=rec.get('cost'),
                                     level=rec.get('level')))
    return out


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else (ROOT / 'eval_report6.json'))
    if not src.exists():
        print(f'找不到报告: {src}（先跑一次真机评估，或显式给一个评估产物 JSON）')
        return 2
    data = json.loads(src.read_text(encoding='utf-8'))
    records = data.get('results') or []
    if not records:
        print(f'报告里没有 results: {src}')
        return 2

    sets = collections.Counter(r.get('set') or '通用' for r in records)
    energy_rows = sum(1 for r in records
                      if any(s.get('name') == ENERGY for s in (r.get('stats') or [])))
    snap = snapshot()

    # 基线先跑：B 线前值、判定前值都从它取
    restore(snap)
    base_rows = replay(records)
    base_verdict = [r['verdict_cn'] for r in base_rows]
    base_score = [r['score'] for r in base_rows]
    base_b5 = {}
    for name in sets:
        if name == '通用':
            base_b5[name] = _legacy_threshold('通用', 5)
        else:
            base_b5[name] = _legacy_threshold(name, 5)

    lines = []
    lines.append('# 共效口径影响面（report6 / 160 条）')
    lines.append('')
    lines.append(f'- 生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append(f'- 输入报告：`{src.name}`（{len(records)} 条 / {len(sets)} 个套装）')
    lines.append(f'- 含共效词条的件：**{energy_rows}/{len(records)}**')
    tpl = load_templates()
    by_w = collections.Counter(info['weights'].get(ENERGY, 0.0) for info in tpl.values())
    lines.append('- 模板共效权重分布：' + ' / '.join(f'{w:g}×{c}' for w, c in sorted(by_w.items())))
    lines.append(f'- `DEFAULT_WEIGHTS` 共效：**{DEFAULT_WEIGHTS[ENERGY]:g}**')
    lines.append('- report6 里的件按套装：' + ' / '.join(f'{k} {v}' for k, v in sets.most_common()))
    lines.append('')
    lines.append('> 说明：`通用` 指套装未映射的件；report6 里若为 0 条，则"改 DEFAULT_WEIGHTS"对这份报告**零影响**。')
    lines.append('')

    summary = []
    sections = []
    for fn in SCENARIOS:
        restore(snap)
        label = fn()
        t0 = time.time()
        rows = replay(records)
        secs = time.time() - t0
        dist = collections.Counter(r['verdict_cn'] for r in rows)
        changed = []
        dmax = 0.0
        for i, (b, n) in enumerate(zip(base_rows, rows)):
            d = n['score'] - b['score']
            dmax = max(dmax, abs(d))
            if n['verdict_cn'] != b['verdict_cn']:
                changed.append((i, records[i].get('name'), records[i].get('set'),
                                b['score'], n['score'], b['verdict_cn'], n['verdict_cn'],
                                b['threshold'], n['threshold']))
        b_changed = []
        for name in sets:
            if name == '通用':
                continue
            now = _legacy_threshold(name, 5)
            if abs(now - base_b5[name]) > 1e-9:
                b_changed.append((name, base_b5[name], now))
        summary.append((label, dist, len(changed), dmax, secs))

        sections.append(f'## {label}')
        sections.append('')
        sections.append('- 判定分布：' + ' / '.join(f'{k} {v}' for k, v in sorted(dist.items())))
        sections.append(f'- 判定变化：**{len(changed)}/{len(records)}** 条，最大 |Δ分| = {dmax:.2f}（{secs:.1f}s）')
        if b_changed:
            sections.append('- B(满级) 变化：' + '；'.join(f'{n} {a:g}→{c:g}'
                                                       for n, a, c in b_changed))
        if changed:
            sections.append('')
            sections.append('| # | 名字 | 套装 | 分数 | 判定 | A 线 |')
            sections.append('|---|---|---|---|---|---|')
            for idx, nm, st, s0, s1, v0, v1, a0, a1 in changed:
                sections.append(f'| {idx} | {nm} | {st} | {s0:.2f} → {s1:.2f} | {v0} → **{v1}** | {a0:g} → {a1:g} |')
        sections.append('')

    # ── 汇总表插在元信息之后、逐场景小节之前 ──
    meta = lines[:]
    table = ['## 0. 场景汇总', '', '| 场景 | 判定分布 | 判定变化 | 最大 |Δ分| | 用时 |',
             '|---|---|---|---|---|']
    for label, dist, nchanged, dmax, secs in summary:
        table.append(f'| {label} | ' + '/'.join(f'{k}{v}' for k, v in sorted(dist.items()))
                     + f' | {nchanged} | {dmax:.2f} | {secs:.1f}s |')
    table.append('')
    text = '\n'.join(meta + table + sections) + '\n'

    out_path = ROOT / 'logs' / 'analysis' / 'energy_weight_impact.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')

    print(text)
    print(f'[写入] {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
