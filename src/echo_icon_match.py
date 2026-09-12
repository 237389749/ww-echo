"""
详情面板套装图标识别 — 声骸名多义/OCR 错字时消歧的硬信号。

为什么需要: 181 个声骸名中 120 个属 ≥2 套装, 加上 OCR 错字, 名字层无法唯一确定套装
(实证见 CHANGELOG 阶段十一); 详情面板里等级 `+25` 右侧的套装图标是唯一硬信号。

方法(离线 219 张 debug 数据集实测, 见 CHANGELOG 阶段十二):
- 图标区在详情面板中位置固定, 与网格滚动无关(实测 bbox 波动 ≤±3px) → 归一化坐标裁剪
- 34 个模板同构(彩色圆环 + 白底 + 深色图案), 整体缩小后轮廓主导 → 颜色/环色特征不可分
  (实测环色 top1 命中仅 28/183), 改用**灰度 ZNCC**
- 两端同分辨率 1:1 比: 模板 76px → 29px(尺度 1.05, 实测最优)中心裁 28, 游戏图标归一化到 28x28
- ±2px 平移搜索消除 bbox 抖动(不搜索时 s1 从 0.85 掉到 0.23); 圆形 mask(r≤12)排除外发光与面板背景
- 实测: 217/219 张 s1 ≥ 0.6(中位 0.855); 该子集与声骸名候选 100% 一致, 其中 15 张纠正了名字层错配
  (梦魔·青羽鹭/咕咕河豚 → 息界同调之律); 2 张详情面板无图标 → s1 ≈ 0.28, 由调用方回退名字候选

模板图像即 `assets/echo_icons/{套装名}.png`(34 个, 76x76, 套装名 = 文件名)。
"""

import glob
import os

import cv2
import numpy as np
from ok import Logger

logger = Logger.get_logger(__name__)

# 详情面板套装图标区(整帧归一化)。1920x1200 实测 (1402,199)-(1430,227), 与视觉模型在同一批
#   debug 图上核对的 detail.png 坐标 (135,79)-(163,107) 一致; 图标直径约 28px(含 2px 外发光)
ICON_BOX = (0.7302, 0.1658, 0.7448, 0.1892)
# 统一比较尺寸(px): 模板与游戏内图标都归一到该尺寸后 1:1 比
ICON_SIZE = 28
# 模板缩放: 模板图标外径占 76px 画布的 ~0.95(72/76), 游戏图标铺满 28 → 76→29 实测对齐最优
TEMPLATE_SCALE = 1.05
# 平移搜索半径(px): bbox 抖动实测 ≤±3px, ±2 足够且不引入误配
SHIFT = 2
# 圆形 mask 半径(px, 圆心在画布中心 13.5): 12 ≈ 白底内圈, 排除外发光与面板背景
MASK_R = 12.0
# 高置信下限: 实测正确匹配 s1 ≥ 0.6(1 分位 0.736); 面板无图标/图标未收录 ≈ 0.28
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
    """模板 → 灰度(透明区合成到白底)。cv2.imread 不支持非 ASCII 路径(套装名是中文) → imdecode。"""
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * a + 255.0 * (1.0 - a)).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def _to_canvas(gray, size: int, canvas: int = ICON_SIZE) -> np.ndarray:
    """模板缩放到 size×size 后居中放到 canvas×canvas(size > canvas 时中心裁到 canvas)。"""
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


def crop_icon(frame):
    """整帧 → 图标区灰度 28x28(按帧尺寸换算归一化区, 分辨率无关); 无效帧返回 None。"""
    if frame is None or getattr(frame, 'size', 0) == 0:
        return None
    h, w = frame.shape[:2]
    x1, y1 = int(ICON_BOX[0] * w), int(ICON_BOX[1] * h)
    x2, y2 = int(ICON_BOX[2] * w), int(ICON_BOX[3] * h)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    sub = frame[y1:y2, x1:x2]
    gray = sub if sub.ndim == 2 else cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (ICON_SIZE, ICON_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)


def match_icon(frame):
    """详情面板套装图标 → (套装名 | None, 最佳 ZNCC, 与次优的间隔)。

    置信不足(ZNCC < MIN_SCORE 或与次优间隔 < MIN_MARGIN)返回 (None, …) ——
    例如详情面板没有套装图标时, 由调用方回退"声骸名 → 套装候选"。
    """
    names, matrix, norms, sel = _bank()
    gray = crop_icon(frame)
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
