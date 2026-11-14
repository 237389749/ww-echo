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

# ---------------------------------------------------------------------------
# 结构标定（2026-11-14）：不识别任何文字，直接找「网格结构」
#
# 真机的格子底部有一条**等级条**（金色顶边 + 白色 "+25"），它在每一格都出现、
# 而且 6 格的顶边在同一条水平线上。于是：
#   行 = 等级条顶边的横边（Sobel-y 投影的强峰，5 行等间距）；
#   列 = 等级条顶边金线的横向亮段（每格一段，段中心≈格子中心，6 段等间距）。
# 这样每屏都能重新定位（滚动后相位自然跟着变），且与窗口分辨率/DPI 无关。
# 检测失败时调用方回退到「角标 OCR 并集 + 推断」。
# ---------------------------------------------------------------------------
try:  # 纯逻辑单测环境可能没有 cv2/numpy，此时结构标定不可用
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None


def _runs(mask_1d, min_len):
    """一维布尔序列 → [(start, end)] 连续 True 段（长度 ≥ min_len）。"""
    out = []
    start = None
    for i, v in enumerate(mask_1d):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(mask_1d) - start >= min_len:
        out.append((start, len(mask_1d)))
    return out


def _estimate_period(profile, lo, hi):
    """自相关估间距（行距/列距），返回像素周期或 None。"""
    p = np.asarray(profile, dtype=np.float32)
    p = p - p.mean()
    if not np.any(p):
        return None
    ac = np.correlate(p, p, 'full')[len(p) - 1:]
    lo, hi = max(1, int(lo)), min(len(ac) - 1, int(hi))
    if hi <= lo:
        return None
    lag = int(np.argmax(ac[lo:hi])) + lo
    return float(lag) if ac[lag] > 0 else None


def _fit_lattice(profile, lo, hi, pitch, step=0.5):
    """在一维剖面上做等间距格点拟合（相位搜索），返回格点位置。"""
    profile = np.asarray(profile, dtype=np.float32)
    n = profile.size
    best = None
    phase = 0.0
    while phase < pitch:
        k_max = int((hi - lo) / pitch) + 2
        pos = lo + phase + pitch * np.arange(k_max)
        pos = pos[pos <= hi]
        if pos.size >= 2:
            score = float(profile[np.clip(np.round(pos).astype(int), 0, n - 1)].sum())
            if best is None or score > best[0]:
                best = (score, pos)
        phase += step
    return [] if best is None else [float(p) for p in best[1]]


def _detect_rows(gray, x0, x1, y0, y1):
    """Sobel-y 投影找等级条顶边 → 行线（像素 y）与行距。"""
    roi = cv2.GaussianBlur(gray[y0:y1, x0:x1].astype(np.float32), (3, 3), 0)
    gy = np.abs(cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3))
    prof = gy.mean(axis=1)
    h = prof.size
    pitch = _estimate_period(prof, h * 0.05, h * 0.45)
    if not pitch or pitch < 20:
        return [], None
    lines = _fit_lattice(prof, 0, h - 1, pitch)
    if len(lines) < 3:
        return [], pitch
    # 拟合必须落在"强横边"上（等级条顶边），否则是锁到了杂物
    strong = sum(1 for line in lines if prof[int(round(line))] > prof.mean() * 2.0)
    if strong < max(3, len(lines) - 1):
        return [], pitch
    return [line + y0 for line in lines], pitch


def _detect_cols_gold(frame_bgr, rows, x0, x1):
    """等级条顶边的金色亮段 → 列中心（每格一段；同一段在多行重复 → 去重）。"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 45) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 120))
    min_len = max(16, int((x1 - x0) * 0.03))
    hits = []
    for row in rows:
        b0, b1 = max(0, int(row) - 2), int(row) + 5
        prof = gold[b0:b1, x0:x1].sum(axis=0)
        for a, b in _runs(prof > 0, min_len):
            hits.append((a + b) / 2.0 + x0)
    if not hits:
        return []
    # 聚类：同一列在多行各出现一次（容差按列距的 15%），只保留 ≥2 行支持的列
    hits.sort()
    tol = max(10.0, (x1 - x0) * 0.015)
    clusters = []
    for x in hits:
        if clusters and x - clusters[-1][-1] <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    centers = [sum(c) / len(c) for c in clusters if len(c) >= 2]
    return centers


def detect_grid_structure(frame_bgr, rect):
    """结构标定：返回 {'rows': [y...], 'cols': [x...], 'row_pitch': float} 或 None。

    `rect=(x0, y0, x1, y1)` 像素，取画面中网格所在区域（避免表头/底部按钮）。
    成功条件：≥3 行、≥5 列。失败返回 None（调用方回退 OCR 方案）。
    """
    if cv2 is None or np is None:
        return None
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame_bgr.shape[1], x1), min(frame_bgr.shape[0], y1)
    if x1 - x0 < 100 or y1 - y0 < 100:
        return None
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    rows, row_pitch = _detect_rows(gray, x0, x1, y0, y1)
    if not rows:
        return None
    cols = _detect_cols_gold(frame_bgr, rows, x0, x1)
    if len(cols) < 5:
        return None
    return {'rows': rows, 'cols': cols, 'row_pitch': row_pitch}


def cells_from_structure(struct, click_dy_ratio=0.08):
    """结构标定结果 → 点击点（列中心 × 行线下方一点点；行优先排序）。"""
    if not struct:
        return []
    dy = (struct.get('row_pitch') or 0) * click_dy_ratio
    return [(float(c), float(r) + dy) for r in struct['rows'] for c in struct['cols']]


# ---------------------------------------------------------------------------
# 布局模型（2026-11-14，用户提议的「结构与比例抽象」）
#
# 实测两张不同难度/不同时间的真实帧（1254x889）后确认：背包网格的几何**只随帧宽缩放**
# （UI scale = 帧宽 / 1920）：
#   列距 176px@1920 / 115px@1254 → 0.0917 × 帧宽
#   行距 212px@1920 / 138px@1254 → 0.110  × 帧宽（不是随帧高！）
# 所以把「比例」和「位置」拆开：
#   比例（列距/行距/列数）—— 一次标定后缓存，跨屏复用；
#   位置（首列中心、行线相位）—— 每屏用结构检测重新取（滚动后相位会变）。
# 这样后续屏幕**只用 Sobel 行检测**（不需要金色，也不依赖 +25），列由模型给出；
# 行检测失败/间距突变时再回退整帧结构检测 → 再回退角标 OCR。
# ---------------------------------------------------------------------------
class GridModel:
    """背包网格的布局模型：比例（相对帧宽）+ 可缓存的列布局。"""

    def __init__(self, col_pitch_ratio, row_pitch_ratio, cols, anchor_col_ratio,
                 click_dy_ratio=0.08):
        self.col_pitch_ratio = float(col_pitch_ratio)
        self.row_pitch_ratio = float(row_pitch_ratio)
        self.cols = int(cols)
        self.anchor_col_ratio = float(anchor_col_ratio)
        self.click_dy_ratio = float(click_dy_ratio)

    @classmethod
    def from_structure(cls, struct, frame_width):
        """从一次完整结构检测（detect_grid_structure 的返回）建立模型。"""
        cols = struct['cols']
        if len(cols) < 2 or not frame_width:
            return None
        col_pitch = (cols[-1] - cols[0]) / (len(cols) - 1)
        return cls(col_pitch / frame_width, struct['row_pitch'] / frame_width,
                   len(cols), cols[0] / frame_width)

    def col_centers(self, frame_width):
        return [(self.anchor_col_ratio + i * self.col_pitch_ratio) * frame_width
                for i in range(self.cols)]

    def cells(self, frame_width, row_lines):
        """模型列 × 给定行线 → 点击点（行优先）。"""
        if not row_lines:
            return []
        dy = self.row_pitch_ratio * frame_width * self.click_dy_ratio
        return [(x, float(r) + dy) for r in row_lines for x in self.col_centers(frame_width)]

    def matches(self, row_pitch, frame_width, tol=0.12):
        """新检测到的行距是否仍符合模型（窗口尺寸变化/UI 改动时判失效）。"""
        if not frame_width or not row_pitch:
            return False
        expect = self.row_pitch_ratio * frame_width
        return abs(row_pitch - expect) <= expect * tol


def detect_row_lines(frame_bgr, rect):
    """只做行检测（Sobel-y，等级条顶边），返回 (rows, pitch) 或 ([], None)。"""
    if cv2 is None or np is None:
        return [], None
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame_bgr.shape[1], x1), min(frame_bgr.shape[0], y1)
    if x1 - x0 < 100 or y1 - y0 < 100:
        return [], None
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return _detect_rows(gray, x0, x1, y0, y1)
