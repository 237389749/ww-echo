#!/usr/bin/env python3
r"""report6 面板图标回归：图标识别准确率 vs 面板明文（真值），并对照"环色/二值化形状"两条路线。

输入:
  - `logs/panel_debug/<时间戳>/`（SAVE_PANEL_DATASET 产物：`<idx>_<名字>_top.png` 是回顶后的面板裁剪
    482x783@1440x900 + `panel_ocr.jsonl` 的 step 文本（**整帧像素坐标**，含 `+NN` 等级框）/ summary 记录）
  - 评估报告 JSON（默认 `eval_report6.json`；`results[i].set` 就是当时的真值——那条来自面板明文 `text`）
输出:
  - stdout 摘要 + `logs/analysis/icon_accuracy_report6.md`
支撑结论:
  - `docs/SESSION_2026-11-20.md` §3 的"图标 123/140=87.9%"在 report6 上的复核
  - "把合鸣效果下滑做成可选的精确模式"是否可行（图标够准就不用滚面板）
  - 环色（先颜色）与二值化形状能否替代/补充灰度 ZNCC
用法:
  python tools/analysis/icon_accuracy_report.py [eval_report6.json] [--panels logs/panel_debug/20261120_163851]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src import echo_icon_match as M  # noqa: E402

# 面板裁剪的归一化区（与 EnhanceEchoTask.EFFECT_BOX 一致）+ 当时的抓帧尺寸
EFFECT_BOX = (0.66, 0.08, 0.995, 0.95)
FRAME_W, FRAME_H = 1440, 900
ORIGIN = (int(EFFECT_BOX[0] * FRAME_W), int(EFFECT_BOX[1] * FRAME_H))

LEVEL_RE = re.compile(r'^\+\s*(\d+)$')
NUM_RE = re.compile(r'^\d+$')


def imread_unicode(path):
    # cv2.imread 读不了中文路径（项目已知坑）→ 直接走 imdecode，避免每条打印一次 WARN
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def load_records(panel_dir):
    steps, summ = [], {}
    path = os.path.join(panel_dir, 'panel_ocr.jsonl')
    if not os.path.exists(path):
        return steps, summ
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get('kind') == 'step':
                steps.append(rec)
            elif rec.get('kind') == 'summary':
                summ[rec.get('tag')] = rec
    return steps, summ


def level_box(steps, tag):
    """从 step 的整帧 OCR 框里找等级 `+NN`（也处理 `+` 与数字拆成两个框）。"""
    boxes = [t for s in steps if s.get('tag') == tag for t in (s.get('texts') or [])]
    for t in boxes:
        m = LEVEL_RE.match((t.get('name') or '').strip())
        if m:
            return int(t['x']), int(t['y']), int(t['w']), int(t['h'])
    # `+` 与 `25` 分开的框：同一行、x 相邻
    for t in boxes:
        if (t.get('name') or '').strip() != '+':
            continue
        for u in boxes:
            if u is t or not NUM_RE.match((u.get('name') or '').strip()):
                continue
            if abs(int(u['y']) - int(t['y'])) < 12 and 0 <= int(u['x']) - int(t['x']) < 40:
                x0 = int(t['x'])
                return (x0, int(t['y']), int(u['x']) + int(u['w']) - x0, max(int(t['h']), int(u['h'])))
    return None


def crop_bgr(frame, box):
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    sub = frame[y1:y2, x1:x2]
    return cv2.resize(sub, (M.ICON_SIZE, M.ICON_SIZE), interpolation=cv2.INTER_AREA)


def to_gray(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)


def zncc_rank(gray, bank):
    """与 match_icon 同一套：±SHIFT 平移搜索 + 圆形 mask + 去均值；返回 (names, 每模板最佳分)。"""
    names, matrix, norms, sel = bank
    padded = np.pad(gray, M.SHIFT, mode='edge')
    best = np.full(len(names), -9.0, np.float32)
    for dy in range(-M.SHIFT, M.SHIFT + 1):
        for dx in range(-M.SHIFT, M.SHIFT + 1):
            win = padded[M.SHIFT + dy:M.SHIFT + dy + M.ICON_SIZE,
                         M.SHIFT + dx:M.SHIFT + dx + M.ICON_SIZE]
            vec = win.reshape(-1)[sel].astype(np.float32)
            vec -= vec.mean()
            nv = float(np.linalg.norm(vec))
            if nv < 1e-6:
                continue
            best = np.maximum(best, (matrix @ vec) / (norms * nv))
    return names, best


def rank_of(names, scores, want):
    order = np.argsort(-scores)
    for rank, i in enumerate(order, 1):
        if names[i] == want:
            return rank, float(scores[i])
    return 999, -9.0


def top1(names, scores):
    i = int(np.argmax(scores))
    return names[i], float(scores[i])


def hue_dist(a, b):
    if a is None or b is None:
        return None
    d = abs(float(a) - float(b))
    return min(d, 180.0 - d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('report', nargs='?', default=os.path.join(ROOT, 'eval_report6.json'))
    ap.add_argument('--panels', default='')
    args = ap.parse_args()

    panel_dir = args.panels
    if not panel_dir:
        cands = sorted(glob.glob(os.path.join(ROOT, 'logs', 'panel_debug', '*')),
                       key=os.path.getmtime)
        panel_dir = cands[-1] if cands else ''
    if not panel_dir or not os.path.isdir(panel_dir):
        print('找不到面板数据集: logs/panel_debug/<时间戳>/')
        return 2

    with open(args.report, encoding="utf-8") as f:
        data = json.load(f)
    truth = {int(r['index']): r for r in (data.get('results') or []) if r.get('index') is not None}

    steps, summ = load_records(panel_dir)
    bank = M._bank()
    names_tpl = bank[0]
    hues = M.set_hue_map()

    tops = sorted(glob.glob(os.path.join(panel_dir, '*_top.png')))
    rows, skipped = [], []
    for p in tops:
        tag = os.path.basename(p)[:-len('_top.png')]
        m = re.match(r'^(\d+)_', tag)
        idx = int(m.group(1)) if m else None
        rec = truth.get(idx or -1)
        if rec is None:
            skipped.append((tag, '报告里没有该 index'))
            continue
        lv = level_box(steps, tag)
        if lv is None:
            skipped.append((tag, '没有等级框'))
            continue
        frame = imread_unicode(p)
        if frame is None:
            skipped.append((tag, '图读不出来'))
            continue
        # 整帧坐标 → 面板裁剪坐标
        lb = (lv[0] - ORIGIN[0], lv[1] - ORIGIN[1], lv[2], lv[3])
        box = M.icon_box_at_level(lb[0], lb[1], lb[2], lb[3], FRAME_W)
        bgr = crop_bgr(frame, box)
        if bgr is None:
            skipped.append((tag, '图标裁剪越界'))
            continue
        gray = to_gray(bgr)

        # ① 灰度 ZNCC（现方案）
        _n, scores = zncc_rank(gray, bank)
        pred, s1 = top1(names_tpl, scores)
        s2 = float(np.sort(scores)[-2]) if len(scores) > 1 else 0.0
        margin = s1 - s2
        rank, true_score = rank_of(names_tpl, scores, rec['set'])
        # ② 环色
        h = M._ring_hue_bgr(bgr)
        hue_c = [(n, hue_dist(h, hues.get(n))) for n in names_tpl]
        hue_ok = [(n, d) for n, d in hue_c if d is not None]
        hue_pred, hue_d = min(hue_ok, key=lambda kv: kv[1]) if hue_ok else ('', 999)
        # ③ 二值化形状（Otsu，两种极性各算一次取大）
        bw = _bin(gray)
        bw_rank = _binary_rank(bw)
        b_pred, b_score = top1(names_tpl, bw_rank)

        # 候选集（名字给出的候选；summary 里有就优先用）
        cands = list((summ.get(tag) or {}).get('cands') or [])
        if not cands:
            from src.echo_set_templates import get_sets_by_echo
            cands = get_sets_by_echo(rec.get('name') or '')
        rows.append(dict(tag=tag, idx=idx, name=rec.get('name'), truth=rec.get('set'),
                         level=rec.get('level'), cands=cands,
                         pred=pred, s1=s1, margin=margin, rank=rank, true_score=true_score,
                         scores_arr=scores,
                         hue=h, hue_pred=hue_pred, hue_d=hue_d,
                         b_pred=b_pred, b_score=b_score,
                         frame_w=FRAME_W))

    n = len(rows)
    ok = sum(1 for r in rows if r['pred'] == r['truth'])
    in_cands = sum(1 for r in rows if r['truth'] in r['cands'])
    gate = [r for r in rows if r['s1'] >= M.MIN_SCORE and r['margin'] >= M.MIN_MARGIN]
    gate_ok = sum(1 for r in gate if r['pred'] == r['truth'])
    hue_ok_n = sum(1 for r in rows if r['hue_pred'] == r['truth'])
    b_ok = sum(1 for r in rows if r['b_pred'] == r['truth'])

    lines = []
    lines.append('# report6 面板图标回归（真值 = 面板明文 `text`）')
    lines.append('')
    lines.append(f'- 面板数据集：`{os.path.basename(panel_dir)}`')
    lines.append(f'- 报告：`{os.path.basename(args.report)}`')
    lines.append(f'- 参与：**{n}** 只（跳过 {len(skipped)}；都是需要滚面板的多候选件）')
    lines.append('')
    lines.append('## 1. 灰度 ZNCC（现方案）')
    lines.append('')
    lines.append(f'- top-1（不设门槛）：**{ok}/{n} = {ok / n:.1%}**；真值平均排名 '
                 f'{np.mean([r["rank"] for r in rows]):.2f}')
    lines.append(f'- 置信闸（s1≥{M.MIN_SCORE} 且 margin≥{M.MIN_MARGIN}）：覆盖 **{len(gate)}/{n}={len(gate) / n:.1%}**，'
                 f'其中 top-1 正确 **{gate_ok}/{len(gate)} = {gate_ok / max(1, len(gate)):.1%}**')
    wrong = [r for r in rows if r['pred'] != r['truth']]
    lines.append(f'- 错配 {len(wrong)} 只：' + ('、'.join(f"{r['tag']}:{r['pred']}≠{r['truth']}({r['s1']:.2f})"
                                                    for r in wrong[:12]) or '无'))
    lines.append(f'- s1：正确件中位 {np.median([r["s1"] for r in rows if r["pred"] == r["truth"]]):.3f}，'
                 f'错件中位 {(np.median([r["s1"] for r in wrong]) if wrong else float("nan")):.3f}')
    lines.append('')
    lines.append('## 2. 候选集约束（名字候选）')
    lines.append('')
    lines.append(f'- 真值在名字候选里的：**{in_cands}/{n} = {in_cands / n:.1%}**（候选集天然天花板）')
    lines.append('')
    lines.append('| 门槛 | 覆盖 | 覆盖率 | 其中正确 | 精度 |')
    lines.append('|---|---|---|---|---|')
    for score_th in (0.30, 0.40, 0.50, 0.60):
        for margin_th in (0.0, 0.02, 0.05):
            sel = [r for r in rows if r['cands'] and r['s1'] >= score_th and r['margin'] >= margin_th]
            if not sel:
                continue
            good = sum(1 for r in sel if r['pred'] == r['truth'])
            lines.append(f'| s≥{score_th:.2f} m≥{margin_th:.2f} | {len(sel)} | {len(sel) / n:.0%} | '
                         f'{good} | {good / len(sel):.1%} |')
    lines.append('')
    lines.append('## 3. 环色（先看颜色）')
    lines.append('')
    lines.append(f'- 能读出环色的：{sum(1 for r in rows if r["hue"] is not None)}/{n}')
    lines.append(f'- 环色 top-1（最近 hue）：**{hue_ok_n}/{n} = {hue_ok_n / n:.1%}**')
    lines.append(f'- 环色分组一致（`hue_group`）：'
                 f'{sum(1 for r in rows if M.hue_group(r["hue"]) == M.hue_group(hues.get(r["truth"])))}/{n}')
    lines.append('')
    lines.append('## 4. 二值化形状（Otsu）')
    lines.append('')
    lines.append(f'- 二值形状 top-1：**{b_ok}/{n} = {b_ok / n:.1%}**')
    lines.append('')

    by_level = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        lv = r['level']
        if lv is None:
            continue
        by_level[lv][1] += 1
        by_level[lv][0] += int(r['pred'] == r['truth'])
    lines.append('## 5. 按等级')
    lines.append('')
    lines.append('| 等级 | 只数 | 图标 top-1 | 闸内覆盖(s≥.6/m≥.05) | 候选约束+低门槛(≥.3/.05) |')
    lines.append('|---|---|---|---|---|')
    for lv in sorted(by_level, reverse=True):
        good, tot = by_level[lv]
        gated = [r for r in rows if r['level'] == lv and r['s1'] >= M.MIN_SCORE and r['margin'] >= M.MIN_MARGIN]
        cons = [r for r in rows if r['level'] == lv and r['cands'] and r['s1'] >= 0.3 and r['margin'] >= 0.05
                and r['pred'] in r['cands']]
        cons_ok = sum(1 for r in cons if r['pred'] == r['truth'])
        lines.append(f'| +{lv} | {tot} | {good}/{tot} = {good / tot:.0%} | {len(gated)} | '
                     f'{len(cons)}（正确 {cons_ok}） |')
    lines.append('')

    # ── 7. 环色作为"候选过滤器"（零成本，只读一个 hue） ──
    hue_unique = hue_unique_ok = hue_none = 0
    for r in rows:
        if r['hue'] is None:
            hue_none += 1
        kept = [c for c in r['cands'] if M.hue_group(hues.get(c)) == M.hue_group(r['hue'])]
        if not kept:
            kept = list(r['cands'])          # 与 filter_by_set_hue 同口径: 滤空不丢候选
        if len(kept) == 1:
            hue_unique += 1
            hue_unique_ok += int(kept[0] == r['truth'])
    lines.append('## 7. 环色当"候选过滤器"（只读一个 hue，不做形状）')
    lines.append('')
    lines.append(f'- 有名字候选的件：{sum(1 for r in rows if r["cands"])}/{n}')
    lines.append(f'- 环色把候选**缩到唯一**：{hue_unique} 只，其中正确 **{hue_unique_ok}**'
                 f'（精度 {hue_unique_ok / max(1, hue_unique):.1%}）')
    lines.append(f'- 环色读不出（无彩色环）：{hue_none} 只')
    lines.append('')

    # ── 8. 颜色粗筛 + ZNCC 细判 ──
    group_sizes = collections.Counter(M.hue_group(v) for v in hues.values())
    lines.append('## 8. 先颜色（粗筛）再灰度形状（ZNCC）')
    lines.append('')
    lines.append('- 37 套按环色分成 ' + str(len(group_sizes)) + ' 组：'
                 + ' / '.join(f'{g}×{c}' for g, c in sorted(group_sizes.items())))
    huef = []
    for r in rows:
        g = M.hue_group(r['hue'])
        idx = [i for i, nm in enumerate(names_tpl) if M.hue_group(hues.get(nm)) == g]
        if not idx:
            idx = list(range(len(names_tpl)))
        best_i = max(idx, key=lambda i: r['scores_arr'][i])
        huef.append((r, names_tpl[best_i], float(r['scores_arr'][best_i])))
    huef_ok = sum(1 for r, p, s in huef if p == r['truth'])
    lines.append(f'- 粗筛后 top-1：**{huef_ok}/{n} = {huef_ok / n:.1%}**（全量 top-1 为 {ok / n:.1%}）')
    for th in (0.30, 0.40, 0.50, 0.60):
        sel = [(r, p) for r, p, s in huef if s >= th]
        good = sum(1 for r, p in sel if p == r['truth'])
        lines.append(f'- 粗筛 + s≥{th:.2f}：覆盖 {len(sel)}/{n}，精度 {good / max(1, len(sel)):.1%}')
    lines.append('')

    # ── 9. 时间账（面板滚动 = 每步一次滚动 + 一次 OCR） ──
    steps_total = sum((summ.get(r['tag']) or {}).get('steps') or 0 for r in rows)
    notches_total = sum((summ.get(r['tag']) or {}).get('notches') or 0 for r in rows)
    multi = sum(1 for r in rows if ((summ.get(r['tag']) or {}).get('steps') or 0) > 1)
    lines.append('## 9. 时间账（面板下滑的开销）')
    lines.append('')
    lines.append(f'- 这 {n} 只合计滚了 **{steps_total} 步**（{notches_total} 格），'
                 f'平均 {steps_total / n:.1f} 步/只；其中 {multi} 只滚了不止 1 步')
    lines.append('- 实测拟合（`tools/analysis/panel_scroll_time.py`）：每条固定 **4.51s** + 每滚一步 **1.41s**')
    lines.append(f'- → 面板下滑 ≈ **{steps_total * 1.41:.0f}s ≈ {steps_total * 1.41 / 60:.1f} 分钟**'
                 f'（整轮 1214s = 20.2 分钟，占 {steps_total * 1.41 / 1214:.0%}）')
    lines.append('- 图标匹配：37 模板 × 25 次平移 ≈ 每只 **10~30ms**（同一张 28×28，无需滚动/OCR）')
    remain_gate = n - len(gate)
    cons_all = [r for r in rows if r['cands'] and r['s1'] >= 0.3 and r['margin'] >= 0.05 and r['pred'] in r['cands']]
    remain_cons = n - len(cons_all)
    est_steps = steps_total * remain_gate / n
    est_steps_c = steps_total * remain_cons / n
    lines.append(f'- 改成"图标优先"后仍需滚面板：闸内 → **{remain_gate}/{n}**；'
                 f'候选约束 + 低门槛 → **{remain_cons}/{n}**')
    lines.append(f'- → 预计面板步数 {steps_total} → ≈{est_steps:.0f}（候选约束版 ≈{est_steps_c:.0f}），'
                 f'省 ≈{(steps_total - est_steps) * 1.41:.0f}s ≈ {(steps_total - est_steps) * 1.41 / 60:.1f} 分钟')
    lines.append('')

    lines.append('## 10. 错配明细（灰度 ZNCC top-1）')
    lines.append('')
    lines.append('| tag | 名字 | 真值 | 预测 | s1 | margin | 真值在候选 |')
    lines.append('|---|---|---|---|---|---|---|')
    for r in wrong:
        lines.append(f"| {r['tag']} | {r['name']} | {r['truth']} | {r['pred']} | {r['s1']:.2f} | "
                     f"{r['margin']:.2f} | {'是' if r['truth'] in r['cands'] else '否'} |")
    if skipped:
        lines.append('')
        lines.append('## 跳过')
        lines.append('')
        for tag, why in skipped:
            lines.append(f'- {tag}: {why}')

    text = '\n'.join(lines) + '\n'
    out = os.path.join(ROOT, 'logs', 'analysis', 'icon_accuracy_report6.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'[写入] {out}')
    return 0


def _bin(gray):
    g = np.clip(gray, 0, 255).astype(np.uint8)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def _binary_rank(bw):
    """二值形状的 ZNCC：模板也 Otsu 二值化，两种极性都试，取每模板最佳。"""
    names, matrix, norms, sel = M._bank()
    # 模板二值库（缓存到模块级）
    global _BIN_BANK
    try:
        _BIN_BANK
    except NameError:
        _BIN_BANK = None
    if _BIN_BANK is None:
        bws = []
        for path in sorted(glob.glob(os.path.join(M.icons_dir(), '*.png'))):
            g = M._template_gray(path)
            if g is None:
                continue
            c = M._to_canvas(g, int(round(M.ICON_SIZE * M.TEMPLATE_SCALE)))
            bws.append((_bin(c).reshape(-1)[sel].astype(np.float32)))
        mat = np.stack(bws)
        _BIN_BANK = (mat,)
    mat = _BIN_BANK[0]

    best = np.full(len(names), -9.0, np.float32)
    sel_f = bw.reshape(-1)[sel].astype(np.float32)
    for flip in (False, True):
        v = (255.0 - sel_f) if flip else sel_f
        v = v - v.mean()
        nv = float(np.linalg.norm(v))
        if nv < 1e-6:
            continue
        mm = mat - mat.mean(axis=1, keepdims=True)
        mn = np.linalg.norm(mm, axis=1)
        best = np.maximum(best, (mm @ v) / (mn * nv + 1e-9))
    return best


if __name__ == '__main__':
    raise SystemExit(main())
