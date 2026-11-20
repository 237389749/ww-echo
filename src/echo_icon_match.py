"""
详情面板套装图标识别 — 声骸名多义/OCR 错字时消歧的硬信号。

为什么需要: 181 个声骸名中 120 个属 ≥2 套装, 加上 OCR 错字, 名字层无法唯一确定套装
(实证见 CHANGELOG 阶段十一); 详情面板里等级 `+25` 右侧的套装图标是唯一硬信号。

方法(离线 219 张 debug 数据集实测, 见 CHANGELOG 阶段十二):
- 图标区在详情面板中位置固定, 与网格滚动无关(实测 bbox 波动 ≤±3px) → 归一化坐标裁剪
- 34 个模板同构(彩色圆环 + 白底 + 深色图案), 整体缩小后轮廓主导 → 颜色/环色特征不可分
  (实测环色 top1 命中仅 28/183), 改用**灰度 ZNCC**
- 两端同分辨率 1:1 比: 模板 76px → 29px(尺度 1.05, 实测最优)中心裁 28, 游戏图标归一化到 28x28
- ±2px 平移搜索消除 bbox 抖动(不搜索时 s1 从 0.9 掉到 0.23); 圆形 mask(r≤12)排除外发光与面板背景
- 实测: 217/219 张 s1 ≥ 0.6(中位 0.894); 该子集与声骸名候选 100% 一致, 其中 15 张纠正了名字层错配
  (梦魔·青羽鹭/啾啾河豚/咕咕河豚 → 息界同调之律, s1=0.93); 2 张详情面板无图标 → s1 ≈ 0.22, 由调用方回退名字候选

模板图像即 `assets/echo_icons/{套装名}.png`(34 个, 76x76, 套装名 = 文件名)。
"""

import glob
import os

import cv2
import numpy as np

from src.logging_utils import get_logger

logger = get_logger(__name__)

# 详情面板套装图标区(整帧归一化, **旧固定区**)。1920x1200 实测 (1402,199)-(1430,227), 与视觉模型在同一批
#   debug 图上核对的 detail.png 坐标 (135,79)-(163,107) 一致; 图标直径约 28px(含 2px 外发光)
# ⚠ **只对 `+25` 面板成立**: 图标跟在等级文字右侧, `+5` 时左移约 10px → 评估链用 `icon_box_at_level`
#   按等级 OCR 框动态锚定; 这个常量只留给没有等级框的旧调用/离线工具。
ICON_BOX = (0.7302, 0.1658, 0.7448, 0.1892)
# 统一比较尺寸(px): 模板与游戏内图标都归一到该尺寸后 1:1 比
ICON_SIZE = 28
# 模板缩放: 模板图标外径占 76px 画布的 ~0.95(72/76), 游戏图标铺满 28 → 76→29 实测对齐最优
TEMPLATE_SCALE = 1.05
# 平移搜索半径(px): bbox 抖动实测 ≤±3px, ±2 足够且不引入误配
SHIFT = 2
# 圆形 mask 半径(px, 圆心在画布中心 13.5): 12 ≈ 白底内圈, 排除外发光与面板背景
MASK_R = 12.0
# 高置信下限: 实测正确匹配 s1 ≥ 0.6(1 分位 0.736); 面板无图标/图标未收录 ≈ 0.22
MIN_SCORE = 0.60
# 与次优模板的间隔下限: 排除两模板同分的歧义(实测正确匹配间隔中位 0.25)
MIN_MARGIN = 0.05

_ICON_SUBDIR = ('assets', 'echo_icons')
_bank_cache: tuple | None = None


def icons_dir() -> str:
    """图标素材目录(支持打包后 exe 与源码运行)。"""
    rel = os.path.join(*_ICON_SUBDIR)
    if os.path.isdir(rel):
        return rel
    alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *_ICON_SUBDIR)
    return alt if os.path.isdir(alt) else rel


def _template_gray(path: str):
    """模板 → 灰度(透明区合成到白底)。cv2.imread 不支持非 ASCII 路径(套装名是中文) → imdecode。
    文件不存在/损坏时返回 None(由 _bank 跳过并告警), 不让单个坏文件拖垮整个模板库。"""
    try:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except OSError:
        return None
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * a + 255.0 * (1.0 - a)).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def _to_canvas(gray, size: int, canvas: int = ICON_SIZE) -> np.ndarray:
    """模板缩放到 size×size 后放进 canvas×canvas; size > canvas 时按 (size-canvas)//2 偏移取窗。
    注意: 76→29 而 canvas=28 时偏移为 0(取左上 28x28, 亚像素偏 0.5px) —— 回归基线即基于此, 勿改。"""
    resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    if size == canvas:
        return resized
    if size > canvas:
        o = (size - canvas) // 2
        return resized[o:o + canvas, o:o + canvas]
    out = np.full((canvas, canvas), 255.0, np.float32)
    o = (canvas - size) // 2
    out[o:o + size, o:o + size] = resized
    return out


def _mask_sel() -> np.ndarray:
    """圆形 mask 的扁平索引(排除图标外的面板背景与 2px 外发光)。"""
    c = (ICON_SIZE - 1) / 2.0
    yy, xx = np.mgrid[0:ICON_SIZE, 0:ICON_SIZE]
    return (np.hypot(xx - c, yy - c) <= MASK_R).reshape(-1)


def _bank():
    """全部模板特征(名字、去均值矩阵、模长、mask 索引), 首次调用构建并缓存。"""
    global _bank_cache
    if _bank_cache is not None:
        return _bank_cache
    sel = _mask_sel()
    names: list[str] = []
    vecs: list[np.ndarray] = []
    for path in sorted(glob.glob(os.path.join(icons_dir(), '*.png'))):
        gray = _template_gray(path)
        if gray is None:
            logger.warning(f'套装图标模板读取失败: {path}')
            continue
        names.append(os.path.splitext(os.path.basename(path))[0])
        vecs.append(_to_canvas(gray, int(round(ICON_SIZE * TEMPLATE_SCALE))).reshape(-1)[sel])
    if vecs:
        matrix = np.stack(vecs).astype(np.float32)
        matrix -= matrix.mean(axis=1, keepdims=True)   # 去均值, 与调用方一起构成 ZNCC
    else:
        logger.warning(f'套装图标模板缺失: {icons_dir()}')
        matrix = np.zeros((0, int(sel.sum())), np.float32)
    _bank_cache = (names, matrix, np.linalg.norm(matrix, axis=1), sel)
    if names:
        logger.info(f'套装图标模板: {len(names)} 个 from {icons_dir()}')
    return _bank_cache


# 图标锚定参数(2026-11-20 实测 1440x900): 图标中心 = 等级 `+NN` 框右缘 + 15px, 半径 11px。
# **必须按等级框锚定**: 图标是跟在等级文字后面的, `+5` 比 `+25` 窄 → 图标整体左移约 10px;
# 旧的固定 ICON_BOX 只对 `+25` 成立(2026-11-14 那批低等级面板因此 0 命中, 误判成"没有图标")。
ICON_GAP_RATIO = 15 / 1440.0        # 等级框右缘 → 图标中心(×帧宽)
ICON_RADIUS_RATIO = 11 / 1440.0     # 图标半径(×帧宽)


def icon_box_at_level(level_x, level_y, level_w, level_h, frame_w):
    """等级 `+NN` 的 OCR 框(像素) → 套装图标裁剪框(像素) `(x0,y0,x1,y1)`。

    图标在等级文字右侧、与文字垂直居中; gap/半径按帧宽缩放, 与分辨率无关。
    """
    gap = ICON_GAP_RATIO * float(frame_w)
    r = ICON_RADIUS_RATIO * float(frame_w)
    cx = float(level_x) + float(level_w) + gap
    cy = float(level_y) + float(level_h) / 2.0
    return (cx - r, cy - r, cx + r, cy + r)


def crop_icon(frame, box=None):
    """整帧 → 图标区灰度 28x28。`box` = 像素 `(x0,y0,x1,y1)`; 不给则用旧固定区 `ICON_BOX`(归一化)。

    **推荐传 box**(`icon_box_at_level` 算出的动态框): 固定框只对 `+25` 面板成立。
    """
    if frame is None or getattr(frame, 'size', 0) == 0:
        return None
    h, w = frame.shape[:2]
    if box is None:
        x1, y1 = int(ICON_BOX[0] * w), int(ICON_BOX[1] * h)
        x2, y2 = int(ICON_BOX[2] * w), int(ICON_BOX[3] * h)
    else:
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    sub = frame[y1:y2, x1:x2]
    gray = sub if sub.ndim == 2 else cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (ICON_SIZE, ICON_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)


def match_icon(frame, box=None):
    """详情面板套装图标 → (套装名 | None, 最佳 ZNCC, 与次优的间隔)。

    置信不足(ZNCC < MIN_SCORE 或与次优间隔 < MIN_MARGIN)返回 (None, …) ——
    例如详情面板没有套装图标时, 由调用方回退"声骸名 → 套装候选"。

    `box` 是**像素**裁剪框(推荐 `icon_box_at_level(...)`); 不给时退回旧固定区 `ICON_BOX`
    —— 固定区只对 `+25` 面板成立, `+5` 会切偏(2026-11-20 实测)。
    """
    names, matrix, norms, sel = _bank()
    gray = crop_icon(frame, box)
    if gray is None or not names:
        return None, 0.0, 0.0
    padded = np.pad(gray, SHIFT, mode='edge')   # 平移取窗, 避免 np.roll 的边界卷绕
    best: dict[str, float] = {}
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            win = padded[SHIFT + dy:SHIFT + dy + ICON_SIZE, SHIFT + dx:SHIFT + dx + ICON_SIZE]
            vec = win.reshape(-1)[sel].astype(np.float32)
            vec -= vec.mean()
            nv = float(np.linalg.norm(vec))
            if nv < 1e-6:
                continue
            for name, score in zip(names, matrix @ vec / (norms * nv)):
                if score > best.get(name, -9.0):
                    best[name] = float(score)
    if not best:
        return None, 0.0, 0.0
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    top1, score1 = ranked[0]
    score2 = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = score1 - score2
    if score1 < MIN_SCORE or margin < MIN_MARGIN:
        logger.debug(f'套装图标低置信: top1={top1} s1={score1:.3f} margin={margin:.3f} → 回退名字候选')
        return None, score1, margin
    return top1, score1, margin


# ---------------------------------------------------------------------------
# 网格卡片徽章环色(2026-11-14 二次): 新 UI 下唯一的套装信号
#
# 背包网格里每个卡片**左下角**有一个 28px 的圆形套装徽章(彩色环 + 深色底 + 白色符号)。
# 它比 76px 模板小且糊(灰度 ZNCC 只有 0.2~0.3, 不可用), 但**环色**非常稳:
# 37 个模板按环色中位 hue 聚成 8 个色组 + 1 个无彩色组(白/灰环)。
# 于是: 名字给出多个候选套装时, 用徽章环色**过滤候选** ——
# 官方数据里 158 个声骸名属 ≥2 套装, 环色能唯一定位其中 135 个(85%)。
# 实测样例: `先锋幼岩` 候选 {不绝余音(h1), 幽夜隐匿之帷(h135), 隐世回光(h41)},
# 徽章环色 41 → 唯一命中 `隐世回光`(名字兜底会错选 `不绝余音`)。
# ---------------------------------------------------------------------------
HUE_REFS = (1.0, 7.0, 18.0, 26.0, 41.0, 77.0, 102.0, 109.0, 135.0)
_hue_cache: dict | None = None


def _ring_hue_bgr(rgb) -> float | None:
    """模板图 → 外环的中位 hue; 环是无彩色(白/灰)返回 None。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dd = np.hypot(xx - (w / 2 - 0.5), yy - (h / 2 - 0.5))
    band = (dd >= 0.62 * w / 2) & (dd <= 0.99 * w / 2)
    hues, sats, vals = hsv[:, :, 0][band], hsv[:, :, 1][band], hsv[:, :, 2][band]
    m = (sats > 100) & (vals > 90)
    if m.sum() < 5:
        return None
    return float(np.median(hues[m]))


def set_hue_map() -> dict:
    """套装名 → 图标环色中位 hue(OpenCV 0~180); 无彩色环(白/灰)为 None。首次调用构建并缓存。"""
    global _hue_cache
    if _hue_cache is not None:
        return _hue_cache
    out = {}
    for path in sorted(glob.glob(os.path.join(icons_dir(), '*.png'))):
        raw = None
        try:
            raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        except OSError:
            raw = None
        if raw is None:
            continue
        if raw.ndim == 3 and raw.shape[2] == 4:
            a = raw[:, :, 3:4].astype(np.float32) / 255.0
            raw = (raw[:, :, :3].astype(np.float32) * a + 255.0 * (1.0 - a)).astype(np.uint8)
        elif raw.ndim == 3:
            raw = raw[:, :, :3]
        out[os.path.splitext(os.path.basename(path))[0]] = _ring_hue_bgr(raw)
    _hue_cache = out
    return out


def hue_group(hue) -> str:
    """环色 → 粗分组标记: 最近的参考色('h41'), 或 'ach'(无彩色)。"""
    if hue is None:
        return 'ach'
    near = min(HUE_REFS, key=lambda r: abs(r - float(hue)))
    return f'h{int(near)}'


def badge_hue(frame, cx, cy, radius):
    """帧上 (cx,cy) 半径 radius 的圆形徽章 → `(hue | None, ok)`。

    `ok=False` 表示**没读到**(裁剪越界/帧为空); `ok=True, hue=None` 表示**无彩色环**(白/灰)。
    环带取 0.62~0.99R(排除内部符号与外部发光), 只统计饱和且够亮的像素的中位 hue。
    """
    if frame is None or getattr(frame, 'size', 0) == 0 or radius < 6:
        return None, False
    h, w = frame.shape[:2]
    r = int(round(radius))
    x0, x1 = max(0, int(round(cx)) - r), min(w, int(round(cx)) + r + 1)
    y0, y1 = max(0, int(round(cy)) - r), min(h, int(round(cy)) + r + 1)
    if x1 - x0 < 2 * r - 2 or y1 - y0 < 2 * r - 2:
        return None, False
    sub = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    hh, ww = hsv.shape[:2]
    yy, xx = np.mgrid[0:hh, 0:ww]
    dd = np.hypot(xx - (ww / 2 - 0.5), yy - (hh / 2 - 0.5))
    band = (dd >= 0.62 * r) & (dd <= 0.99 * r)
    n_band = int(band.sum())
    if n_band < 20:
        return None, False
    hues, sats, vals = hsv[:, :, 0][band], hsv[:, :, 1][band], hsv[:, :, 2][band]
    m = (sats > 100) & (vals > 90)
    if m.sum() < 8:
        return None, True          # 环无彩色(白/灰)
    return float(np.median(hues[m])), True


def filter_by_set_hue(candidates, hue, ok=True):
    """用徽章环色过滤候选套装; 读不到/滤空时**原样返回**(绝不因为读错而丢候选)。"""
    cands = list(candidates or [])
    if not ok or len(cands) < 2:
        return cands
    target = hue_group(hue)
    hues = set_hue_map()
    kept = [c for c in cands if hue_group(hues.get(c)) == target]
    return kept or cands
