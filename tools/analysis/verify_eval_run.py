#!/usr/bin/env python3
r"""一次真机评估的验收：条数 / 去重 / 套装来源 / 每屏重叠 / 滚动健康。

输入:
  - 评估 JSON（「运行」页保存报告时同目录写的那份 `<报告名>.json`）
  - 运行日志（缺省 `logs/ok-echo.log`；自动只取**最后一次**评估会话）
输出:
  - 控制台验收表 + 问题清单；`--check` 时有问题退出码 1
  - 每屏一行: 格数 / 新增 / 重复 / 网格几何 / 滚动行数与残差（`--screens` 全打印, 否则只打异常屏）
支撑结论:
  - `docs/SESSION_2026-11-18.md` §8 的三条验收（条数 153±2、每屏重复 10~13 格、`set_src=text` 占多数）
  - `docs/BASELINE.md` 的「真机评估」验收口径
用法:
  python tools/analysis/verify_eval_run.py eval_report.json
  python tools/analysis/verify_eval_run.py eval_report.json --log logs/ok-echo.log --check
  python tools/analysis/verify_eval_run.py --log logs/ok-echo.2026-11-14.log --screens   # 无 JSON 时只看日志
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RE_START = '评估遍历: 不识别声骸数量'
RE_DONE = re.compile(r'评估完成, 共(\d+)个声骸')
RE_SCREEN = re.compile(r'本屏完成: (\d+) 格, 新增 (\d+) 条, 重复/点空 (\d+) 格, 0词条 (\d+) 格')
RE_SCROLL = re.compile(r'滚动\((.*?)\): (-?\d+) 格 → ([+-]?\d+\.\d) 行 \(≈([\d.]+)px/格, '
                       r'残差 (\d+), 停稳 ([\d.]+)s, 画面变化 (\d+)%\)')
RE_GRID = re.compile(r'本屏网格: (\d+) 列 × (\d+) 行 \(行距 (\d+)px\)')
RE_GUARD = '本屏无重叠'
RE_STUCK = '滚动受阻'
RE_OVER = re.compile(r'一次滚了 ([\d.]+) 行\(可见 (\d+) 行\)')
RE_SHORT = re.compile(r'本次只滚了 ([\d.]+) 行\(目标 (\d+) 行\)')
RE_SETTEXT = re.compile(r'\[套装\] 合鸣效果区读到套装名: (.*?)\((.*?), 滚 (\d+) 格\)')
RE_SETEFFECT = re.compile(r'\[套装\] 按合鸣效果文本命中: (.*?) \(')
RE_ECHO = re.compile(r'\[评估#(\d+)\] (.*?) \| (\d)/5词条 \| 得分=([\d.]+) \| (.*?) \| 套装=(.*?)\((.*?)\)')
TS = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3}) ')


class Screen:
    __slots__ = ('idx', 'cells', 'new', 'dup', 'zero', 'cols', 'rows', 'row_pitch',
                 'scroll_px', 'moved', 'resid', 'still', 'change', 'input', 'guarded', 'secs')

    def __init__(self, idx):
        self.idx = idx
        for k in self.__slots__[1:]:
            setattr(self, k, None)
        self.guarded = False


def parse_ts(line):
    m = TS.match(line)
    if not m:
        return None
    import datetime
    dt = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
    return dt.timestamp() + int(m.group(2)) / 1000.0


def parse_log(path: Path):
    text = path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    # 只取最后一次评估会话
    start = 0
    for i, ln in enumerate(lines):
        if RE_START in ln:
            start = i
    lines = lines[start:]

    screens: list[Screen] = []
    cur: Screen | None = None
    grid = None
    stats = collections.Counter()
    non_text: list[tuple] = []
    done = None
    first_ts = last_ts = None

    for i, ln in enumerate(lines):
        t = parse_ts(ln)
        if t:
            first_ts = first_ts or t
            last_ts = t
        m = RE_GRID.search(ln)
        if m:
            grid = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            stats['grid_marks'] += 1
            continue
        m = RE_SCREEN.search(ln)
        if m:
            cur = Screen(len(screens))
            cur.cells, cur.new, cur.dup, cur.zero = (int(x) for x in m.groups())
            if grid:
                cur.cols, cur.rows, cur.row_pitch = grid
            screens.append(cur)
            continue
        m = RE_SCROLL.search(ln)
        if m:
            if cur is not None and cur.moved is None:
                cur.input = m.group(1)
                cur.scroll_px = int(m.group(2))
                cur.moved = float(m.group(3))
                cur.resid = int(m.group(5))
                cur.still = float(m.group(6))
                cur.change = int(m.group(7))
            else:
                stats['extra_scroll_lines'] += 1
            continue
        if RE_GUARD in ln:
            stats['guard'] += 1
            if cur is not None:
                cur.guarded = True
            continue
        if RE_STUCK in ln:
            stats['stuck'] += 1
            continue
        m = RE_OVER.search(ln)
        if m:
            stats['overshoot'] += 1
            stats['overshoot_max'] = max(stats['overshoot_max'], float(m.group(1)))
            continue
        m = RE_SHORT.search(ln)
        if m:
            stats['short'] += 1
            continue
        m = RE_SETTEXT.search(ln)
        if m:
            stats['set_text'] += 1
            stats['set_text_max_scroll'] = max(stats['set_text_max_scroll'], int(m.group(3)))
            if '/all' in m.group(2):
                stats['set_text_all'] += 1
            continue
        m = RE_SETEFFECT.search(ln)
        if m:
            stats['set_effect'] += 1
            continue
        m = RE_ECHO.search(ln)
        if m:
            idx, name, tier, score, verdict, setname, src = m.groups()
            if src != 'text':
                non_text.append((int(idx), name, setname, src))
            continue
        m = RE_DONE.search(ln)
        if m:
            done = int(m.group(1))
            lines = lines[:i + 1]        # 会话在「评估完成」结束，后面的启动日志不算耗时
            break

    # 每屏耗时（按本屏的时间戳差）
    stamps = [parse_ts(ln) for ln in lines if RE_SCREEN.search(ln)]
    stamps = [s for s in stamps if s]
    secs = [round(b - a, 1) for a, b in zip(stamps, stamps[1:])]
    for sc, s in zip(screens, secs + [None]):
        sc.secs = s
    stats['duration'] = round((last_ts - first_ts), 1) if first_ts and last_ts else None
    return screens, stats, non_text, done


def parse_report(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data.get('results') or []
    return data, rows


def sig(r):
    return (r.get('name'),
            tuple((s['name'], round(float(s['value']), 1)) for s in (r.get('stats') or [])),
            tuple((m['name'], round(float(m['value']), 1)) for m in (r.get('main_props') or [])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('json_path', nargs='?', help='评估产物 JSON（可选）')
    ap.add_argument('--log', default=str(ROOT / 'logs' / 'ok-echo.log'))
    ap.add_argument('--expect', type=int, default=153, help='期望条数（SESSION_2026-11-18 §8）')
    ap.add_argument('--tol', type=int, default=2)
    ap.add_argument('--min-text-pct', type=float, default=60.0,
                    help='set_src=text 至少占比(%%), 低于则告警')
    ap.add_argument('--screens', action='store_true', help='打印每一屏')
    ap.add_argument('--check', action='store_true', help='有问题时退出码 1')
    args = ap.parse_args()

    problems: list[str] = []
    warns: list[str] = []

    print('=' * 72)
    print('真机评估验收')
    print('=' * 72)

    # ── 1. 报告 ──────────────────────────────────────────────────────────
    rows = None
    if args.json_path:
        data, rows = parse_report(Path(args.json_path))
        n = len(rows)
        lo, hi = args.expect - args.tol, args.expect + args.tol
        mark = 'PASS' if lo <= n <= hi else 'WARN'
        print(f'\n[条数] {n}  (期望 {args.expect}±{args.tol} = {lo}~{hi})  -> {mark}')
        if mark == 'WARN':
            warns.append(f'条数 {n} 不在 {lo}~{hi}（声骸列表条数变了也会这样，看其它项）')
        print(f"  时间={data.get('evaluated_at')}  顶层 set={data.get('set')}")
        print('  词条数分布: ' + str(dict(sorted(collections.Counter(
            len(r.get('stats') or []) for r in rows).items()))))

        dups = [k for k, c in collections.Counter(sig(r) for r in rows).items() if c > 1]
        print(f'\n[去重] 完全重复 {len(dups)} 组  -> {"PASS" if not dups else "FAIL"}')
        if dups:
            problems.append(f'完全重复 {len(dups)} 组（滚动重叠没吸收干净）')
            for d in dups[:3]:
                print(f'    {d[0]} x{collections.Counter(sig(r) for r in rows)[d]}')

        src = collections.Counter(r.get('set_src') or 'default' for r in rows)
        total = sum(src.values()) or 1
        pretty = {k: f'{v}({v * 100 / total:.0f}%)' for k, v in src.most_common()}
        text_pct = src.get('text', 0) * 100 / total
        verdict = 'PASS' if text_pct >= args.min_text_pct else ('WARN' if text_pct > 0 else 'FAIL')
        print(f'\n[套装来源] {pretty}  -> {verdict} (text {text_pct:.0f}%, 门槛 {args.min_text_pct:.0f}%)')
        if verdict != 'PASS':
            (problems if verdict == 'FAIL' else warns).append(
                f'set_src=text 只占 {text_pct:.0f}%（面板套装名没读到）')
            bad = [(r.get('index'), r.get('name'), r.get('set'), r.get('set_src')) for r in rows
                   if (r.get('set_src') or 'default') != 'text']
            for x in bad[:12]:
                print(f'    #{x[0]:>3} {x[1]} -> {x[2]} ({x[3]})')

        v = collections.Counter(r.get('verdict') for r in rows)
        print('\n[判定分布] ' + ', '.join(f'{k}={v[k]}' for k in
                                     ('pass', 'hold', 'keep', 'pending', 'fail', 'zero') if v.get(k)))
        mp_bad = sum(1 for r in rows if (r.get('main_prop_check') or {}).get('status') == 'bad'
                     if isinstance(r.get('main_prop_check'), dict))
        if mp_bad:
            warns.append(f'主属性数值可疑 {mp_bad} 条')

    # ── 2. 日志 ──────────────────────────────────────────────────────────
    log_path = Path(args.log)
    screens: list[Screen] = []
    stats = collections.Counter()
    non_text_log = []
    done = None
    if log_path.exists():
        screens, stats, non_text_log, done = parse_log(log_path)
        print(f'\n[日志] {log_path}  (最后一次评估会话: {len(screens)} 屏, '
              f'耗时 {stats.get("duration")}s)')
        if done is not None:
            same = (rows is None) or (done == len(rows))
            print(f'  日志条数={done}  报告条数={len(rows) if rows is not None else "-"}'
                  f'  -> {"一致" if same else "不一致(报告不是这次跑的?)"}')
            if not same:
                problems.append(f'日志 {done} 条 vs 报告 {len(rows)} 条不一致')
        if not screens:
            print('  [!] 日志里没找到本次会话的「本屏完成」（日志被截断/换了路径？）')
    else:
        print(f'\n[日志] 不存在: {log_path}（跳过每屏/滚动检查）')

    if screens:
        cells = sum(s.cells for s in screens)
        new = sum(s.new for s in screens)
        dup = sum(s.dup for s in screens)
        zero = sum(s.zero for s in screens)
        print(f'\n[每屏] {len(screens)} 屏 / {cells} 格 / 新增 {new} / 重复 {dup} / 0词条 {zero}')
        print(f'  网格: ' + ', '.join(sorted({f'{s.cols}列×{s.rows}行(行距{s.row_pitch}px)'
                                            for s in screens if s.cols})))
        dups = [s.dup for s in screens[1:]]  # 首屏没有重叠
        if dups:
            med = statistics.median(dups)
            print(f'  非首屏重复/屏: 中位 {med:.0f} (期望 8~14 = 重叠约 2 行), '
                  f'范围 {min(dups)}~{max(dups)}')
            if not (8 <= med <= 14):
                warns.append(f'每屏重复中位 {med:.0f} 不在 8~14（重叠行数不对）')
        empty_dups = [s for s in screens[1:] if s.dup == 0]
        print(f'  非首屏「一格都不重复」的屏: {len(empty_dups)}'
              f'{"（=无重叠守卫该触发的屏）" if empty_dups else ""}')
        moved = [s.moved for s in screens if s.moved is not None and s.moved > 0]
        if moved:
            print(f'  滚动实测位移: 中位 {statistics.median(moved):.1f} 行 '
                  f'(只作"动没动"的证据, 像素测量在真机不可靠)')
        deltas = [s.new for s in screens]
        print(f'  新增/屏: ' + ' '.join(str(d) for d in deltas))

        if stats.get('guard'):
            msg = f'无重叠守卫触发 {stats["guard"]} 次（自愈，不算失败）'
            print(f'  {msg}')
        if stats.get('stuck'):
            problems.append(f'滚动受阻 {stats["stuck"]} 次')
            print(f'  [x] 滚动受阻 {stats["stuck"]} 次')
        if stats.get('overshoot'):
            warns.append(f'滚过头告警 {stats["overshoot"]} 次（最多 {stats.get("overshoot_max")} 行）')
            print(f'  [!] 一次滚了 N 行告警 {stats["overshoot"]} 次（最大 {stats.get("overshoot_max")} 行）')
        if stats.get('short'):
            print(f'  [!] 滚动距离不足告警 {stats["short"]} 次（重叠会被去重吸收）')
        print(f'  套装: 面板文字命中 {stats.get("set_text", 0)} 条'
              f'（其中放开到 37 套 {stats.get("set_text_all", 0)} 条, 最多滚 '
              f'{stats.get("set_text_max_scroll", 0)} 格）/ 效果文本命中 {stats.get("set_effect", 0)} 条')
        if stats.get('duration'):
            print(f'  平均每屏 {stats["duration"] / max(1, len(screens)):.1f}s')

        if args.screens:
            print('\n  逐屏:')
            print('    #   格 新增 重复 0词条  网格        滚轮格 px/格 位移 残差 停稳 变化 守卫 耗时')
            for s in screens:
                print(f'   {s.idx:>3} {s.cells:>4} {s.new:>4} {s.dup:>4} {s.zero:>5}   '
                      f'{str(s.cols) + "x" + str(s.rows):<10} {s.scroll_px if s.scroll_px else "-":>5} '
                      f'{s.moved if s.moved is not None else "-":>5} {s.resid if s.resid is not None else "-":>4} '
                      f'{s.still if s.still is not None else "-":>4} '
                      f'{str(s.change) + "%" if s.change is not None else "-":>5} '
                      f'{"Y" if s.guarded else " ":>2} {s.secs if s.secs else "-":>5}')

        if non_text_log:
            print(f'\n  日志里 set_src!=text 的条目: {len(non_text_log)} 条')
            try:
                from src.echo_set_templates import get_sets_by_echo
                for idx, name, setname, src in non_text_log[:15]:
                    print(f'    #{idx:>3} {name} -> {setname} ({src}) 候选={get_sets_by_echo(name)}')
            except Exception:   # 没装依赖时降级
                for idx, name, setname, src in non_text_log[:15]:
                    print(f'    #{idx:>3} {name} -> {setname} ({src})')

    # ── 3. 结论 ──────────────────────────────────────────────────────────
    print('\n' + '-' * 72)
    if problems:
        print('[x] 不通过:')
        for p in problems:
            print('    - ' + p)
    if warns:
        print('[!] 提醒:')
        for w in warns:
            print('    - ' + w)
    if not problems and not warns:
        print('[ok] 全部验收项通过')
    elif not problems:
        print('[ok] 硬性验收项通过（有提醒）')
    return 1 if (problems and args.check) else 0


if __name__ == '__main__':
    raise SystemExit(main())
