#!/usr/bin/env python3
r"""离线重放「详情面板找套装」：读评估时存下的面板数据集，不开游戏就能反复调判定。

输入:
  `logs/panel_debug/<时间戳>/`（评估时 `SAVE_PANEL_DATASET` 自动生成）:
    `panel_ocr.jsonl`  每步一行 `{"kind":"step", ...}` + 每只一行 `{"kind":"summary", ...}`
    `<tag>_sNN.png`    该步的面板裁剪（EFFECT_BOX 区域）
    `<tag>_long.png`   各步拼成的**长图**（人眼一眼看完整面板）
    `<tag>_top.png`    回顶后的证明图（"每个声骸滑到底后回到最上"）
输出:
  逐只一张表：线上结论 vs 离线重放（第几步命中）/ 回顶是否成功 / 长图尺寸；
  `--stitch` 用步图补齐缺失的长图，`--steps` 打每步 OCR 摘要，`--check` 有问题时退出码 1。
支撑结论:
  `docs/SESSION_2026-11-18.md` §3 的套装判定链、CHANGELOG 补记 47（面板 OCR 区单位错 + 回顶）；
  迭代方式：**一次真机跑 → 这里反复重放**，不用重开游戏。

用法:
  python tools/analysis/replay_panel_scroll.py                    # 最新一份
  python tools/analysis/replay_panel_scroll.py <目录> --steps
  python tools/analysis/replay_panel_scroll.py <目录> --stitch --check
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.echo_set_templates import (get_sets_by_echo, has_heading,  # noqa: E402
                                    match_set_effect, match_set_text, name_own_line)


class Box:
    """把 dataset 里的一行还原成 `match_set_*` 认识的对象（只需要 name/坐标/置信度）。"""

    __slots__ = ('name', 'x', 'y', 'width', 'height', 'confidence')

    def __init__(self, name, x=0, y=0, w=0, h=0, conf=0.0):
        self.name, self.x, self.y = name, x, y
        self.width, self.height, self.confidence = w, h, conf

    def __repr__(self):
        return f'Box({self.name!r} @{self.x},{self.y})'


def newest_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    dirs = [p for p in base.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.name) if dirs else None


def load_dataset(path: Path):
    """→ (steps_by_tag, summary_by_tag)；dataset 缺 jsonl 时返回空表（只做长图）。"""
    steps: dict[str, list] = collections.defaultdict(list)
    summary: dict[str, dict] = {}
    f = path / 'panel_ocr.jsonl'
    if not f.exists():
        return steps, summary
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        tag = rec.get('tag') or ''
        if not tag:
            continue
        if rec.get('kind') == 'step':
            steps[tag].append(rec)
        elif rec.get('kind') == 'summary':
            summary[tag] = rec
    for tag in steps:
        steps[tag].sort(key=lambda r: r.get('step', 0))
    return steps, summary


def replay(steps, cands):
    """按**线上同一份判据**重放：套装名(且独占一行/见过标题)优先 → 效果原文反查。

    返回 `(套装名, 来源, 第几步, 备注)`；命中不了返回 `(None, '', -1, '')`。
    """
    heading_seen = False
    for rec in steps:
        texts = [Box(t.get('name', ''), t.get('x', 0), t.get('y', 0),
                     t.get('w', 0), t.get('h', 0), t.get('conf', 0.0))
                 for t in (rec.get('texts') or [])]
        if has_heading(texts, '合鸣效果'):
            heading_seen = True
        named, how = match_set_text(texts, cands)
        if not named and cands:
            named_all, how_all = match_set_text(texts)
            if named_all:
                named, how = named_all, how_all + '/all'
        if named and (heading_seen or name_own_line(texts, named)):
            return named, 'text', rec.get('step', 0), how
        cand, s1, s2 = match_set_effect(texts, cands)
        if cand:
            return cand, 'effect', rec.get('step', 0), f'覆盖 {s1:.2f}/{s2:.2f}'
    return None, '', -1, ''


def stitch_missing(path: Path, tags, only=None):
    """用步图补齐缺失的长图（`echo_panel_shot.stitch`，与评估时同一份实现）。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print('[x] 没有 cv2，无法拼长图')
        return 0
    from src.echo_panel_shot import stitch_and_save
    made = 0
    for tag in tags:
        if only and only not in tag:
            continue
        long_path = path / f'{tag}_long.png'
        if long_path.exists():
            continue
        imgs = []
        for i in range(64):
            p = path / f'{tag}_s{i:02d}.png'
            if not p.exists():
                break
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                imgs.append(img)
        if not imgs:
            continue
        out, used_n, h = stitch_and_save(str(long_path), imgs)
        if out:
            made += 1
            print(f'  [长图] {tag}: {used_n}/{len(imgs)} 步 → {h}px 高')
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('dir', nargs='?', help='logs/panel_debug 下的某次目录（缺省取最新）')
    ap.add_argument('--steps', action='store_true', help='逐只打印每一步的 OCR 摘要')
    ap.add_argument('--stitch', action='store_true', help='用步图补齐缺失的长图')
    ap.add_argument('--check', action='store_true', help='线上漏读/回顶失败时退出码 1')
    args = ap.parse_args()

    path = Path(args.dir) if args.dir else newest_dir(ROOT / 'logs' / 'panel_debug')
    if not path or not path.exists():
        print('[x] 没有面板数据集: logs/panel_debug/<时间戳>/（跑一次评估会生成）')
        return 2

    steps, summary = load_dataset(path)
    pngs = sorted(p.name for p in path.glob('*_s??.png'))
    print(f'[目录] {path}')
    print(f'[内容] 步图 {len(pngs)} 张 / 记录了 {len(summary)} 只 / jsonl {"有" if steps else "无"}')
    if args.stitch:
        made = stitch_missing(path, sorted(set(list(steps) + list(summary)) | 
                                           {n.split("_s")[0] for n in pngs}))
        print(f'[长图] 本次补出 {made} 张')

    if not summary:
        print('[!] 没有 summary 记录：只能看图，重放不了（数据集是旧版本或中途停止）')
        return 0

    missed_online, restore_fail, both_empty = [], [], []
    print('\n  #   声骸                     候选  步  线上                离线重放(第几步)     回顶  长图')
    for tag in sorted(summary):
        s = summary[tag]
        cands = list(s.get('cands') or [])
        online = f"{s.get('found')}({s.get('src')})" if s.get('found') else '-'
        name, src, step, note = replay(steps.get(tag, []), cands)
        offline = f'{name}({src}@{step})' if name else '-'
        long_png = path / f'{tag}_long.png'
        long_info = f'{long_png.stat().st_size // 1024}KB' if long_png.exists() else '缺'
        ok_top = 'Y' if s.get('restore_ok', True) else '[x]'
        print(f" {tag[:3]:>3} {str(s.get('name'))[:24]:<24} {len(cands):>3} {s.get('steps', 0):>3}  "
              f"{online:<19} {offline:<20} {ok_top:<4} {long_info}")

        if not s.get('found') and name:
            missed_online.append((tag, s.get('name'), name, src, step))
        if not s.get('found') and not name:
            both_empty.append((tag, s.get('name'), s.get('notches')))
        if s.get('restore_ok') is False:
            restore_fail.append((tag, s.get('name')))
        if args.steps:
            for rec in steps.get(tag, []):
                lines = [t.get('name') for t in (rec.get('texts') or [])]
                print(f"       step{rec.get('step')} 滚{rec.get('notches')}格: "
                      + ' | '.join(str(x) for x in lines[:8]))

    print('\n' + '-' * 72)
    if missed_online:
        print(f'[x] 线上没读到但离线能读到 {len(missed_online)} 只（判据/时序问题，可在离线复现）:')
        for tag, nm, found, src, step in missed_online[:10]:
            print(f'    {tag} {nm} → {found}({src}@{step})')
    if both_empty:
        print(f'[!] 线上/离线都没读到 {len(both_empty)} 只（看长图: 面板没滚到 or 套装名被读坏）:')
        for tag, nm, notches in both_empty[:10]:
            print(f'    {tag} {nm} (滚 {notches} 格)')
    if restore_fail:
        print(f'[x] 回顶失败 {len(restore_fail)} 只（下一只会读不到词条，看 _top.png）:')
        for tag, nm in restore_fail[:10]:
            print(f'    {tag} {nm}')
    if not (missed_online or both_empty or restore_fail):
        print('[ok] 每只都读到了 / 也没漏读、没回顶失败')
    bad = bool(missed_online or restore_fail)
    return 1 if (bad and args.check) else 0


if __name__ == '__main__':
    raise SystemExit(main())
