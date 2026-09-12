"""套装图标识别离线回归 —— 用 `logs/eval_debug/<时间戳>/` 的全屏截图跑 `src/echo_icon_match`。

评估遍历的 debug 数据集(`evaluate_only` 内 `if True:` 开关)每格存一张 `*_full.png`(整帧)与
`*_detail.png`(详情面板), 无需开游戏即可回归图标识别:

    python tools/eval_icon_match.py                  # 用 logs/eval_debug/ 下最新的目录
    python tools/eval_icon_match.py <目录> [--limit N]

口径: 高置信比例(置信线见 echo_icon_match.MIN_SCORE/MIN_MARGIN)、s1 分布,
以及"图标 top1 ∈ 声骸名候选集(get_sets_by_echo)"的一致率(需同目录的 image_report.md 提供名字)。
名字层已实证无解的错字案例(如 梦魔·青羽鹭 → 名字候选错, 图标给 息界同调之律)在"不一致明细"里逐条列出。
"""

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402

from src.echo_icon_match import match_icon  # noqa: E402
from src.echo_set_templates import get_sets_by_echo  # noqa: E402

_ITEM_RE = re.compile(r'^### (\S+)\n(.*?)(?=^### |\Z)', re.S | re.M)
_DETAIL_RE = re.compile(r'\*\*【详情文字】\*\*\n((?:- .*\n)+)')


def latest_debug_dir() -> str:
    dirs = sorted(glob.glob(os.path.join('logs', 'eval_debug', '*')), key=os.path.getmtime)
    return dirs[-1] if dirs else ''


def names_from_report(dbg_dir: str) -> dict:
    """image_report.md 的 `### <tag>` → 详情文字首行(声骸名); 缺失时返回空表。"""
    path = os.path.join(dbg_dir, 'image_report.md')
    if not os.path.exists(path):
        return {}
    text = open(path, encoding='utf-8').read()
    out = {}
    for m in _ITEM_RE.finditer(text):
        detail = _DETAIL_RE.search(m.group(2))
        if detail:
            out[m.group(1)] = detail.group(1).strip().split('\n')[0][2:].strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('debug_dir', nargs='?', default='')
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 张(默认全部)')
    args = ap.parse_args()

    dbg = args.debug_dir or latest_debug_dir()
    if not dbg or not os.path.isdir(dbg):
        print(f'找不到 debug 数据目录: {dbg or "logs/eval_debug/*"} (先跑一次评估模式生成)')
        return 2
    frames = sorted(glob.glob(os.path.join(dbg, '*_full.png')))
    if args.limit:
        frames = frames[:args.limit]
    names = names_from_report(dbg)
    print(f'数据集: {dbg}\n整帧 {len(frames)} 张, image_report.md 名字 {len(names)} 条')

    rows = []
    for path in frames:
        tag = os.path.basename(path).replace('_full.png', '')
        frame = cv2.imread(path)
        if frame is None:
            continue
        rows.append((tag, names.get(tag, ''), *match_icon(frame)))

    total = len(rows)
    hit = sum(1 for r in rows if r[2])
    scored = [r[3] for r in rows if r[2]]
    agree = corr = 0
    judged = 0
    misses = []
    for tag, name, icon_set, score, margin in rows:
        if not (name and icon_set):
            continue
        cands = get_sets_by_echo(name)
        if not cands:
            continue
        judged += 1
        if icon_set in cands:
            agree += 1
        else:
            corr += 1
            misses.append((tag, name, cands, icon_set, score, margin))
    print(f'高置信 {hit}/{total} ({100 * hit / max(1, total):.1f}%)'
          + (f', s1 中位 {sorted(scored)[len(scored) // 2]:.3f}' if scored else ''))
    if judged:
        print(f'名字口径: 候选非空 {judged} 张, 一致 {agree} ({100 * agree / judged:.1f}%), '
              f'不一致 {corr}(名字层错字 → 图标纠正, 见下)')
    if misses:
        print('不一致明细(名字层错字 → 名字候选错, 以图标为准):')
        for tag, name, cands, icon_set, score, margin in misses:
            print(f'  {tag} {name} 名字候选={cands} → 图标 {icon_set} (s1={score:.3f} margin={margin:.3f})')
    low = [r for r in rows if not r[2]]
    print(f'低置信(回退名字候选) {len(low)} 张'
          + (': ' + ', '.join(f'{r[0]}(s1={r[3]:.3f})' for r in low) if low else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
