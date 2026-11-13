"""背包声骸网格的纯几何计算（domain，无 Qt/engine）。

**为什么单独成模块（2026-11-14）**：小窗口（如 1254x889）下 `+25` 角标只有 10~14px 高，
OCR 单次只检出 5~14/30 个，而且常把 `+25` 拆成 `+` 与 `25` 两个框。原来的 `scan_grid`
只按单次 OCR 的角标聚行聚列 → 漏行漏列 → 点错格子/第一格不是第一格/重复记录。
这里把「文本框 → 完整 6 列网格点」的纯逻辑抽出来，配合**两路 OCR 合并 + 等间距推断**，
并且可以脱离游戏做单测。

输入约定：文本框可以是 `(<text>, x, y, w, h)` 元组，也可以是带 `.name/.x/.y/.width/.height`
的引擎 Box 对象。坐标是**帧像素**。
"""

from __future__ import annotations

import re

_PLUS_RE = re.compile(r'^\+\s*\d+$')        # 完整的 '+25' / '+0'
_DIGITS_RE = re.compile(r'^\d{1,2}$')       # 被拆出来的 '25' / '5'
_BARE_PLUS = '+'


def _box_tuple(b):
    """统一成 (text, x, y, w, h)。"""
    if hasattr(b, 'name'):
        return (str(getattr(b, 'name', '') or ''), int(b.x), int(b.y),
                int(b.width), int(b.height))
    text, x, y, w, h = b
    return str(text), int(x), int(y), int(w), int(h)


def merge_badge_marks(texts, roi=None) -> list[tuple[int, int]]:
    """OCR 文本框 → 角标中心 `[(cx, cy), ...]`（按 y 再 x 排序，已去重）。

    - 完整 `+25`：直接取框中心；
    - 拆成 `+` + `25`（小窗口常见）：把右侧紧邻、同一行的数字框并起来；
    - 其余文本忽略；`roi=(x0,y0,x1,y1)` 只保留中心落在区域内的（挡掉右侧详情面板自己的 +25）；
    - 距中心 < 10px 的重复检测只留一个（两路 OCR 的结果会重叠）。
    """
    items = [_box_tuple(b) for b in texts]
    plus_boxes = [(x, y, w, h) for t, x, y, w, h in items if t.strip() == _BARE_PLUS]
    digit_boxes = [(x, y, w, h) for t, x, y, w, h in items if _DIGITS_RE.match(t.strip())]
    used_digits: set[int] = set()
    centers: list[tuple[float, float]] = []

    for t, x, y, w, h in items:
        text = t.strip()
        if _PLUS_RE.match(text):
            centers.append((x + w / 2.0, y + h / 2.0))

    # 拆框合并：'+' 与它右边同一行的数字框
    for px, py, pw, ph in plus_boxes:
        pcx, pcy = px + pw / 2.0, py + ph / 2.0
        best = None
        for i, (dx, dy, dw, dh) in enumerate(digit_boxes):
            if i in used_digits:
                continue
            dcy = dy + dh / 2.0
            if abs(dcy - pcy) > max(6.0, 0.7 * ph):
                continue
            gap = dx - (px + pw)          # 数字框在 '+' 右侧多远
            if -max(2.0, 0.3 * pw) <= gap <= max(10.0, 1.2 * pw):
                if best is None or abs(gap) < best[0]:
                    best = (abs(gap), i, dx, dcy, dw)
        if best is not None:
            _, i, dx, dcy, dw = best
            used_digits.add(i)
            centers.append(((pcx + dx + dw / 2.0) / 2.0, (pcy + dcy) / 2.0))

    # 去重（两路 OCR 重叠）
    centers.sort(key=lambda p: (p[1], p[0]))
    merged: list[tuple[int, int]] = []
    for cx, cy in centers:
        if roi is not None:
            x0, y0, x1, y1 = roi
            if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                continue
        if any(abs(cx - mx) < 10 and abs(cy - my) < 10 for mx, my in merged):
            continue
        merged.append((int(round(cx)), int(round(cy))))
    return merged


def cluster_axis(values, tol: float) -> list[tuple[float, int]]:
    """一维聚类：相邻差 ≤ tol 归为同一簇，返回 `[(中心, 成员数), ...]`（按中心排序）。"""
    vals = sorted(float(v) for v in values)
    clusters: list[list[float]] = []
    for v in vals:
        if clusters and v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [(sum(c) / len(c), len(c)) for c in clusters]


def infer_axis_centers(clusters, lo: float, hi: float,
                       max_count: int | None = None,
                       pitch_hint: float | None = None) -> list[float]:
    """在等间距网格上补全缺失的列/行中心。

    `clusters` 是 `cluster_axis` 的返回；`lo/hi` 是合法范围（帧像素，超出不补，
    避免把表头/按钮当成格子）；`pitch_hint` 用于「本屏只剩 1 行/1 列」时沿用上一屏的间距。
    """
    if not clusters:
        return []
    # 成员数 ≥2 的簇才可信；全屏只有单簇时退回全部
    solid = [c for c, n in clusters if n >= 2] or [c for c, _ in clusters]
    solid = sorted(solid)
    if max_count is not None and len(solid) > max_count:
        counts = dict(clusters)
        solid = sorted(sorted(solid, key=lambda c: -counts.get(c, 0))[:max_count])
    if len(solid) >= 2:
        diffs = [b - a for a, b in zip(solid, solid[1:]) if b - a > 1]
        pitch = min(diffs) if diffs else pitch_hint
    else:
        pitch = pitch_hint
    if not pitch or pitch <= 1:
        return solid
    out = list(solid)
    while max_count is None or len(out) < max_count:
        cand = out[0] - pitch
        if cand < lo:
            break
        out.insert(0, cand)
    while (max_count is None or len(out) < max_count):
        cand = out[-1] + pitch
        if cand > hi:
            break
        out.append(cand)
    return out


def cells_from_marks(marks, grid_rect, row_tol: float, col_gap: float,
                     max_cols: int = 6, max_rows: int = 12,
                     row_pitch_hint: float | None = None,
                     col_pitch_hint: float | None = None) -> list[tuple[float, float]]:
    """角标中心 → 完整网格点（先按行、行内按列排序）。

    `grid_rect=(x0, y0, x1, y1)` 是允许外推的范围（帧像素）。返回的是**点击坐标**：
    用检测到的角标中心（真实点击点在角标上即可选中格子，实测有效），缺列/缺行按等间距补。
    """
    if not marks:
        return []
    x0, y0, x1, y1 = grid_rect
    xs = infer_axis_centers(cluster_axis([m[0] for m in marks], col_gap),
                            x0, x1, max_count=max_cols, pitch_hint=col_pitch_hint)
    ys = infer_axis_centers(cluster_axis([m[1] for m in marks], row_tol),
                            y0, y1, max_count=max_rows, pitch_hint=row_pitch_hint)
    return [(x, y) for y in ys for x in xs]


def axis_pitch(centers) -> float | None:
    """等间距估计（用于跨屏沿用）。"""
    vals = sorted(centers)
    if len(vals) < 2:
        return None
    diffs = [b - a for a, b in zip(vals, vals[1:]) if b - a > 1]
    return min(diffs) if diffs else None
