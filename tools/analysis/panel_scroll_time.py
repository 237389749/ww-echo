#!/usr/bin/env python3
r"""面板下滑到底有多贵：用真机日志拟合"每条声骸的固定开销 + 每滚一步的开销"。

输入:
  - 评估日志（默认 `logs/ok-echo.log`；只取**最后一次** `评估遍历` 会话的 `[评估#N]` 行）
  - 面板数据集 `logs/panel_debug/<时间戳>/panel_ocr.jsonl`（每只的 `steps` / `notches`）
输出:
  - stdout 表 + `logs/analysis/panel_scroll_time.md`
支撑结论:
  - `docs/SESSION_2026-11-20.md` §11「20 分钟太久」：面板下滑占多少、图标优先能省多少
  - 拟合式：`每条 = 固定开销(点击+详情 OCR+截图) + 每步 × steps`（最小二乘；R^2 一并给出，
    日志时间戳本身有抖动，只看量级）
用法:
  python tools/analysis/panel_scroll_time.py [--log logs/ok-echo.log] [--panels logs/panel_debug/<ts>]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TS = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3}) ')
REC = re.compile(r'\[评估#(\d+)\]')
START = re.compile(r'评估遍历: 不识别声骸数量')
DONE = re.compile(r'评估完成, 共(\d+)个声骸.*?耗时|耗时 (\d+(?:\.\d+)?)s')


def ts_sec(m) -> float:
    t = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
    return t.timestamp() + int(m.group(2)) / 1000.0


def latest_panels() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, 'logs', 'panel_debug', '*')), key=os.path.getmtime)
    return dirs[-1] if dirs else ''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=os.path.join(ROOT, 'logs', 'ok-echo.log'))
    ap.add_argument('--panels', default='')
    args = ap.parse_args()
    panel_dir = args.panels or latest_panels()
    if not panel_dir:
        print('找不到 panel_debug 数据集')
        return 2

    steps = {}
    with open(os.path.join(panel_dir, 'panel_ocr.jsonl'), encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if r.get('kind') == 'summary':
                steps[int(r['echo'])] = int(r.get('steps') or 0)

    lines = open(args.log, encoding='utf-8', errors='replace').read().splitlines()
    if not any(START.search(ln) for ln in lines):
        print('日志里没有评估会话')
        return 2
    start = max(i for i, ln in enumerate(lines) if START.search(ln))
    records = []
    for ln in lines[start:]:
        m_ts, m_rec = TS.match(ln), REC.search(ln)
        if m_ts and m_rec:
            records.append((int(m_rec.group(1)), ts_sec(m_ts)))

    deltas = []
    for (i0, t0), (i1, t1) in zip(records, records[1:]):
        if i1 in steps and 0 < t1 - t0 < 60:
            deltas.append((i1, steps[i1], t1 - t0))
    if len(deltas) < 10:
        print(f'样本太少: {len(deltas)}')
        return 2

    X = np.array([[1.0, s] for _, s, _ in deltas])
    y = np.array([d for _, _, d in deltas])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    r2 = 1 - float(((y - pred) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
    total_steps = sum(steps.values())

    out = ['# 面板下滑的时间账（真机日志拟合）', '',
           f'- 日志：`{os.path.basename(args.log)}`（最后一次评估会话）',
           f'- 面板数据集：`{os.path.basename(panel_dir)}`',
           f'- 样本：{len(deltas)} 只（相邻 `[评估#N]` 记录的时间差，按该只的 steps 归因）', '',
           f'- **拟合：每条固定开销 {coef[0]:.2f}s + 每步 {coef[1]:.2f}s**（R^2={r2:.2f}）',
           f'- 本轮面板共滚 **{total_steps} 步** → 下滑开销 ≈ **{total_steps * coef[1]:.0f}s ≈ '
           f'{total_steps * coef[1] / 60:.1f} 分钟**', '',
           '| steps | 只数 | 实测中位 | 均值 |', '|---|---|---|---|']
    for s in sorted({s for _, s, _ in deltas}):
        vals = [d for _, ss, d in deltas if ss == s]
        if len(vals) >= 5:
            out.append(f'| {s} | {len(vals)} | {statistics.median(vals):.2f}s | {statistics.mean(vals):.2f}s |')
    out += ['', '> 读法：固定开销 = 点击 + 详情面板 OCR + 截图 + 记录；每步 = 滚轮 + 等停稳 + 合鸣区 OCR。',
            '> 图标在**固定表头**里，不需要滚面板 → 图标优先理论上能把"每步"这笔全省掉。']

    text = '\n'.join(out) + '\n'
    dst = os.path.join(ROOT, 'logs', 'analysis', 'panel_scroll_time.md')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'[写入] {dst}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
