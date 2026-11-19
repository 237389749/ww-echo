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

import math
import re
import statistics

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
    """等级条顶边的金色亮段 → `(列中心列表, {'left': 中心, 'right': 中心})`。

    两处**离群过滤**（2026-11-14 真机 7 列视图暴露，都会把整行列点带偏）：
    ① 贴边段不进列中心：段在 ROI 边界被截断时，段中心不是格子中心
       （实测第一格金条只剩 21px、中心 104.5，真值 70.5 —— 差 34px ≈ 三分之一列距）；
       但**这恰好证明那一格存在**，所以把它的中心回传给调用方，由等间距格点补回整列；
    ② 长度离群丢弃：段被图标/角标挡掉一半时同样偏（< 0.6 × 中位长度）。
    剩下的中心再按"同一列在多行各出现一次"聚类。
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 45) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 120))
    min_len = max(16, int((x1 - x0) * 0.03))
    hits: list[tuple[float, int]] = []      # (中心 x, 段长)
    edges: dict[str, list[float]] = {'left': [], 'right': []}
    for row in rows:
        b0, b1 = max(0, int(row) - 2), int(row) + 5
        prof = gold[b0:b1, x0:x1].sum(axis=0)
        for a, b in _runs(prof > 0, min_len):
            if a <= 0 or b >= prof.size:    # ① 被 ROI 截断 → 记下位置, 不算列中心
                edges['left' if a <= 0 else 'right'].append((a + b) / 2.0 + x0)
                continue
            hits.append(((a + b) / 2.0 + x0, b - a))
    if not hits:
        return [], {'left': None, 'right': None}
    lengths = sorted(h[1] for h in hits)
    med_len = lengths[len(lengths) // 2]
    hits = [h for h in hits if h[1] >= 0.6 * med_len]      # ② 长度离群
    xs = sorted(h[0] for h in hits)
    # 聚类：同一列在多行各出现一次（容差按列距的 15%），只保留 ≥2 行支持的列
    tol = max(10.0, (x1 - x0) * 0.015)
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    centers = [sum(c) / len(c) for c in clusters if len(c) >= 2]
    edge = {side: (statistics.median(v) if v else None) for side, v in edges.items()}
    return centers, edge


def fit_lattice(values, tol=0.2, min_keep=3):
    """一维等间距拟合 → `(anchor, pitch, 完整格点列表)`；失败返回 `(None, None, values)`。

    **为什么不用端点**：真机帧里 7 个候选列中第 1 个偏了 34px（金条被 ROI 截断）。
    `(末-首)/(n-1)` 会算出列距 107（真值 113）、锚点 104.5（真值 70.5）→ 整行点击点最多偏 36px
    ≈ 三分之一列距，表现为"点选未切换/点到隔壁"。
    做法：**相位法**（所有真实列在 `x mod 列距` 上同相，中位相位抗个别离群）→ 丢离群 →
    最小二乘重拟合 anchor/pitch → 用整数索引补齐中间缺失的列（漏一段金线不该整列消失）。
    """
    xs = sorted(float(v) for v in values)
    if len(xs) < min_keep:
        return None, None, xs
    diffs = [b - a for a, b in zip(xs, xs[1:]) if b - a > 1]
    if not diffs:
        return None, None, xs
    pitch = statistics.median(diffs)
    kept = xs
    for _ in range(2):
        if pitch <= 1:
            return None, None, xs
        phase = statistics.median([x % pitch for x in xs])
        cand = [x for x in xs
                if abs(x - (phase + round((x - phase) / pitch) * pitch)) <= tol * pitch]
        if len(cand) < min_keep:
            return None, None, xs
        kept = cand
        d2 = [b - a for a, b in zip(kept, kept[1:]) if b - a > 1]
        if not d2:
            return None, None, xs
        pitch = statistics.median(d2)
    # 最小二乘：x = anchor + k × pitch
    ks = [round((x - kept[0]) / pitch) for x in kept]
    n = len(kept)
    sk, sx = sum(ks), sum(kept)
    skk = sum(k * k for k in ks)
    skx = sum(k * x for k, x in zip(ks, kept))
    den = n * skk - sk * sk
    if den == 0:
        return None, None, xs
    pitch = (n * skx - sk * sx) / den
    anchor = (sx - pitch * sk) / n
    if pitch <= 1:
        return None, None, xs
    k_lo, k_hi = min(ks), max(ks)
    return anchor, pitch, [anchor + k * pitch for k in range(k_lo, k_hi + 1)]


def _click_dy_ratio(frame_bgr, rows, pitch, x0, x1):
    """行线上、下哪一侧是卡片 → 点击点相对行线的偏移（行距的比例）。

    **为什么需要**：行线是"等级条"的横边，它在两版布局里含义不同 ——
    普通背包列表里条在卡片底部（点条下方 0.08 行距仍落在卡内），
    批量管理里行线就是卡片底边（再往下 0.08 行距 = 11px 已经落进格子之间的空隙，点了不切换）。
    真机实测两帧都是**卡片在行线上方**；这里用亮度投票判断，卡片侧更亮。
    """
    if cv2 is None or np is None:
        return 0.08
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape[:2]
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    up_vals, down_vals = [], []
    for r in rows:
        for (lo, hi), acc in (((r - 0.45 * pitch, r - 0.25 * pitch), up_vals),
                              ((r + 0.05 * pitch, r + 0.25 * pitch), down_vals)):
            a, b = int(round(lo)), int(round(hi))
            if a < 0 or b > h or b - a < 4:
                continue
            acc.append(float(gray[a:b, x0:x1].mean()))
    if not up_vals or not down_vals:
        return 0.08
    up, down = statistics.mean(up_vals), statistics.mean(down_vals)
    return -0.30 if up > down + 8.0 else 0.08


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
    cols, edge = _detect_cols_gold(frame_bgr, rows, x0, x1)
    anchor, pitch, lattice = fit_lattice(cols)
    if anchor is not None and len(lattice) >= 5:
        cols = lattice          # 等间距 + 抗离群；补回中间漏检的列
        # 贴边被截断的格子：金条跨过 ROI 边界 → 中心落在 ROI 外/边界上。
        # 用等间距格点补回整列（真机 7 列视图第一列就是这种，之前整列漏点 = 每屏少 5 只）
        for side, sign in (('left', -1), ('right', 1)):
            c = edge.get(side)
            if c is None:
                continue
            cand = cols[0] - pitch if sign < 0 else cols[-1] + pitch
            if abs(c - cand) <= pitch * 0.75:
                cols = [cand] + cols if sign < 0 else cols + [cand]
    if len(cols) < 5:
        return None
    return {'rows': rows, 'cols': cols, 'row_pitch': row_pitch, 'col_pitch': pitch,
            'click_dy': _click_dy_ratio(frame_bgr, rows, row_pitch, x0, x1)}


def cells_from_structure(struct, click_dy_ratio=None):
    """结构标定结果 → 点击点（列中心 × 行线附近；行优先排序）。

    点击偏移优先用标定给出的 `click_dy`（卡片在行线上/下方由亮度判定），
    没给就退回旧口径 +0.08 行距（等级条顶边 → 点条下方一点）。
    """
    if not struct:
        return []
    dy_ratio = struct.get('click_dy') if click_dy_ratio is None else click_dy_ratio
    if dy_ratio is None:
        dy_ratio = 0.08
    dy = (struct.get('row_pitch') or 0) * dy_ratio
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
        """从一次完整结构检测（detect_grid_structure 的返回）建立模型。

        列一律走 `fit_lattice`（抗离群 + 最小二乘 + 补漏列），**不要用端点算列距**：
        真机 7 列帧里第一个金段被 ROI 截断，端点法会让整行点偏三分之一列距。
        """
        if not frame_width:
            return None
        anchor, pitch, lattice = fit_lattice(struct.get('cols') or [])
        if anchor is None or pitch is None or len(lattice) < 5:
            return None
        rows = struct.get('rows') or []
        if len(rows) < 2:
            return None
        return cls(pitch / frame_width, struct['row_pitch'] / frame_width,
                   len(lattice), anchor / frame_width,
                   click_dy_ratio=struct.get('click_dy', 0.08))

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


def estimate_row_shift(before_bgr, after_bgr, rect, pitch, max_rows=8, min_overlap=20):
    """用已知行距估两帧之间的竖向滚动量（行数，带亚行细化）。

    返回 `(rows, diff)`：`rows>0` 表示内容**向上滚了约 rows 行**（列表向下翻）；
    `diff` 是最佳对齐后的灰度平均差（越小越可信，参考：>18 说明没对齐/画面还在动）。

    **搜索范围必须够大**（2026-11-14 真机教训）：旧实现把 k 限在 `(高-80)/行距`
    （1254x889 帧 = 4 行），而一次兜底滚屏实际能走 5~6 行 → 估不出来就返回 0.0，
    调用方误判成"滚动受阻"，接着又叠一次拖拽，越滚越远、整行整行地漏。
    现在放宽到 `(高-min_overlap)/行距`，并允许调用方用 `frame_change_ratio` 区分
    "没动" 与 "动了但超出可测范围"。
    """
    if cv2 is None or np is None or before_bgr is None or after_bgr is None:
        return 0.0, 1e9
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    h, w = before_bgr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 - x0 < 32 or y1 - y0 < 32 or pitch <= 1:
        return 0.0, 1e9
    before = cv2.cvtColor(before_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    after = cv2.cvtColor(after_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    if before.shape != after.shape:
        return 0.0, 1e9
    height = before.shape[0]
    max_k = int(min(max_rows, max(0, (height - min_overlap) // max(1.0, pitch))))

    def _diff(dy_int):
        if dy_int < 0:
            a = after[-dy_int:]
            b = before[:height + dy_int]
        else:
            a = after[:height - dy_int]
            b = before[dy_int:]
        if a.shape[0] < min_overlap:
            return 1e9
        return float(np.abs(a - b).mean())

    best_k, best_diff = 0, _diff(0)
    for k in range(1, max_k + 1):
        d = _diff(int(round(k * pitch)))
        if d < best_diff:
            best_k, best_diff = k, d
    # 亚行细化：在 best_k*pitch ± pitch/2 内 4px 步长
    best_dy = best_k * pitch
    lo = int(best_k * pitch - pitch / 2)
    hi = int(best_k * pitch + pitch / 2)
    for dy in range(max(-height + min_overlap, lo), min(height - min_overlap, hi) + 1, 4):
        d = _diff(dy)
        if d < best_diff:
            best_dy, best_diff = dy, d
    return best_dy / pitch, best_diff


def row_shift_by_lines(before_bgr, after_bgr, rect, pitch, max_rows=1.2):
    """用**等级条行线**量两帧之间的小位移(< max_rows 行) → (rows, cost)。

    为什么要它（2026-11-19 真机）：`estimate_row_shift` 的图像相关在这台机器上残差常年 27~34
    （对不齐），代码只好"按已滚动处理"，于是 **px/格 永远学不到、也纠正不了** —— 实际每格滚得
    比模型假设的远一倍，每次都多滚一截、整行被跳过(43/146 就是这么来的)。
    行线是**结构信号**：每格一条、等间距，两帧只差一个平移；只要位移 < 1 个行距就没有"周期歧义"，
    所以拿它做**开局小步标定**(滚 6 格)最可靠。

    rows > 0 = 内容向上走了(列表往下翻)。cost = 平均最近邻误差(像素, 越小越可信, 参考 <6)。
    """
    if cv2 is None or np is None or before_bgr is None or after_bgr is None or pitch <= 1:
        return 0.0, 1e9
    rows_b, _ = detect_row_lines(before_bgr, rect)
    rows_a, _ = detect_row_lines(after_bgr, rect)
    if len(rows_b) < 2 or len(rows_a) < 2:
        return 0.0, 1e9
    max_s = int(round(max(0.0, float(max_rows)) * float(pitch)))
    best_s, best_cost = 0, 1e9
    for s in range(0, max_s + 1):
        shifted = [y + s for y in rows_a]
        dists = sorted(min(abs(y - z) for z in rows_b) for y in shifted)
        # 用**中位数**而不是均值: 视口边缘常多出一条(半截行)或吃掉一条, 均值会被它带偏;
        # 中位数只要求"过半行线对得上"就认, 正好匹配"位移 < 1 个行距"的标定场景。
        cost = float(dists[len(dists) // 2])
        if cost < best_cost - 0.5:          # 明显更好才换(抗噪声, 平手取更小的位移)
            best_s, best_cost = s, cost
    return best_s / float(pitch), best_cost


def frame_change_ratio(before_bgr, after_bgr, rect, thresh=25):
    """两帧在 rect 内的"变化像素占比" —— **不依赖对齐**，用来判"画面到底动没动"。

    为什么需要它：滚动动画没停/位移超出可测范围时，`estimate_row_shift` 的残差会很高
    （实测 27~32），此时"估不出位移"和"没滚动"看起来一样；而滚动 ≥1 行会让大半个网格区
    变化（实测占比 >0.35），只换选中框/悬停高光时 <0.15。两者用占比就能分开。
    """
    if cv2 is None or np is None or before_bgr is None or after_bgr is None:
        return 1.0
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    h, w = before_bgr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 - x0 < 32 or y1 - y0 < 32:
        return 1.0
    a = cv2.cvtColor(before_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    b = cv2.cvtColor(after_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    if a.shape != b.shape:
        return 1.0
    return float((np.abs(a - b) > thresh).mean())


class ScrollModel:
    """滚轮距离模型：用布局行距算"滚 k 行需要几格"，再用实测 px/格 校正。

    抽象点：距离 = k × 行距(布局模型) / 每格像素(实测)；调用方不再猜 notches。

    **px/格 不随窗口缩放**（2026-11-14 真机二次实测，改口）：此前按 `8.0 × 帧宽/1920` 缩放，
    1254 宽帧算出 5.2；真机日志反推实际是 **8.2~10.4 px/格**（64 格滚了约 4 行 = 552px），
    也就是和 1920 帧的 8.0 基本一致 —— 游戏内滚轮步长跟 UI 缩放无关。用错的 5.2 会把
    3 行的距离算成 80 格，实际滚出 5~6 行，**整行被跳过**（真机 115/153 就是这么来的）。
    """

    PX_PER_NOTCH = 8.0          # 1920/1254 实测都≈8（详见 docstring）

    def __init__(self, frame_width=1920.0, px_per_notch=None, min_notches=3, max_notches=160):
        self.px_per_notch = float(px_per_notch) if px_per_notch else float(self.PX_PER_NOTCH)
        self.frame_width = float(frame_width)
        self.min_notches = int(min_notches)
        self.max_notches = int(max_notches)
        self.observations = 0       # 实测校正次数(0 = 还没量过, 首滚要保守)

    def notches_for(self, rows, row_pitch):
        """滚 `rows` 行需要多少格（按当前 px/格 估计，限幅；向上取整防欠滚）。"""
        target = max(1.0, float(rows) * float(row_pitch))
        n = int(math.ceil(target / max(0.5, self.px_per_notch)))
        return max(self.min_notches, min(self.max_notches, n))

    def observe(self, notches, moved_px, weight=0.5):
        """用一次实测（notches 格实际移动 moved_px 像素）更新 px/格（指数平滑）。"""
        notches, moved = abs(int(notches)), abs(float(moved_px))
        if notches <= 0 or moved < 1.0:
            return
        ratio = moved / notches
        # 学习值必须落在**物理上可能**的区间里: 真机实测 8~15 px/格; 一次错测(比如把"没动"量成 0.2 行)
        # 会把 px/格 拉到 1 → 下次 notches 直接顶到 max_notches(160) → 一屏滚到底、整片漏扫。
        ratio = max(4.0, min(30.0, ratio))
        self.px_per_notch = (1.0 - weight) * self.px_per_notch + weight * ratio
        self.observations += 1
