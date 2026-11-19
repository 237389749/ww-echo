"""详情面板「长截图」：把面板每次滚动后的裁剪图按实测位移拼成一张长图。

为什么需要（2026-11-19 用户口径）：套装名在面板**下半截**，而面板滚动条是**所有声骸共用**的 ——
一次真机评估要十分钟，面板这块却既看不到全貌、也没法复现。把每一步的裁剪图存下来拼成长图：
① 人眼一眼看出"滚到底有没有套装名、名字长什么样"；② 离线反复重放，不用再开游戏。

位移估计不依赖 px/格 的先验，也不要求两帧对齐（滚动动画可能没停）：
用 **matchTemplate** 在上一帧里找当前帧的一条横带，命中位置差 = 实际滚动像素；
过不了相关度门槛就**不拼**（宁可少拼，不要拼错 —— 错位会让长图完全没法看）。

纯 cv2/numpy，不依赖引擎（离线工具与评估任务共用同一份实现）。
"""
from __future__ import annotations

import os

import numpy as np

try:
    import cv2
except ImportError:            # pragma: no cover - 无 cv2 的环境
    cv2 = None


def imwrite_unicode(path: str, img) -> bool:
    """落盘图片，**支持中文路径**。

    `cv2.imwrite` 在 Windows 上按 ANSI 码页处理路径 → 中文文件名会写成乱码名字（文件"消失"）。
    项目已有同类坑：`cv2.imread('assets/echo_icons/雪落无声之愿.png')` 返回 None。
    所以统一 encode 成内存字节再写文件。
    """
    if cv2 is None or img is None:
        return False
    ext = os.path.splitext(path)[1] or '.png'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    with open(path, 'wb') as f:
        f.write(buf.tobytes())
    return True


def _gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def _offset_for_band(prev, cur, lo, hi, min_score, min_corr, strip_h=56):
    """在 `cur` 的 [lo,hi] 高度处取横带，在 `prev` 里找它 → (位移, 匹配分)。"""
    h = min(prev.shape[0], cur.shape[0])
    w = min(prev.shape[1], cur.shape[1])
    if h < strip_h * 3 or w < 40:
        return None
    a = _gray(prev[:h, :w])
    b = _gray(cur[:h, :w])
    x0, x1 = int(w * 0.12), int(w * 0.88)
    y0 = int(h * lo)
    y1 = min(h, y0 + max(strip_h, int(h * (hi - lo))))
    strip = b[y0:y1, x0:x1]
    if strip.shape[0] < 16 or strip.shape[1] < 16:
        return None
    res = cv2.matchTemplate(a[:, x0:x1], strip, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < min_score:
        return None
    dy = int(loc[1]) - y0
    if abs(dy) > h * 0.9 or abs(dy) < 4:      # 越界 / 基本没动：这一带不可用
        return None
    if dy > 0:
        ov_a, ov_b = a[dy:, :], b[:h - dy, :]
    else:
        ov_a, ov_b = a[:h + dy, :], b[-dy:, :]
    if ov_a.shape[0] < h * 0.2 or ov_a.size == 0:
        return None
    fa, fb = ov_a.ravel().astype(np.float32), ov_b.ravel().astype(np.float32)
    if fa.std() < 1e-3 or fb.std() < 1e-3:
        return None
    corr = float(np.corrcoef(fa, fb)[0, 1])
    if not np.isfinite(corr) or corr < min_corr:
        return None
    return dy, score


def vertical_offset(prev: np.ndarray, cur: np.ndarray, min_score: float = 0.55,
                    min_corr: float = 0.45, bands=((0.30, 0.50), (0.45, 0.65), (0.20, 0.40))):
    """`cur` 相对 `prev` **向下滚了多少像素**（正数 = 画面内容向上移）。

    **必须避开不滚动的区域**：游戏详情面板的**名字/等级/COST 是固定表头**（实测顶部 ~30% 在三个
    滚动位置逐像素不动），只在 0.18~0.48 取样会一直匹到"位移 0"→ 长图永远只有一帧。
    所以这里在**若干个候选带**里各试一次（都落在表头之下），取匹配分最高的那个"确实动过"的结果。

    判不出来（静止、重叠太小、相关度低）返回 None —— 调用方跳过这一帧，不要硬拼。
    """
    if cv2 is None or prev is None or cur is None:
        return None
    cands = []
    for lo, hi in bands:
        r = _offset_for_band(prev, cur, lo, hi, min_score, min_corr)
        if r:
            cands.append(r)
    if not cands:
        return None
    dy, _score = max(cands, key=lambda c: c[1])
    return dy


def _moving_band(prev, cur, thresh: int = 25, min_ratio: float = 0.05):
    """两帧之间"确实在动的行"区间 `(r0, r1)`；没动返回 None。

    详情面板的裁剪图里**上下都有不动的部分**：顶部是固定表头(名字/+25/COST)，底部是 HUD
    (培养按钮那一片)。滚动只发生在中间 —— 长图只能拼这一段，否则会把页脚一遍遍重复追加
    (2026-11-19 真实数据上就这么错了一次)。
    """
    if cv2 is None or prev is None or cur is None:
        return None
    h = min(prev.shape[0], cur.shape[0])
    w = min(prev.shape[1], cur.shape[1])
    a = _gray(prev[:h, :w]).astype(np.int16)
    b = _gray(cur[:h, :w]).astype(np.int16)
    rows = (np.abs(a - b) > thresh).mean(axis=1)
    idx = np.where(rows > min_ratio)[0]
    if idx.size == 0:
        return None
    return int(idx[0]), int(idx[-1]) + 1


def stitch(images, max_height: int = 12000):
    """把多张面板裁剪按实测位移拼成一张长图；拼不动就跳过该帧。

    做法：先估帧间位移，再找出**会滚动的内容带**（`_moving_band`），长图 = 首帧(表头+内容带)
    + 各帧在内容带底部新露出的那 `dy` 行 + 末帧的静态页脚。返回
    `(长图, 用了第几帧的列表, 每步实测位移)`；一张都拼不上时返回 `(None, [], [])`。
    """
    frames = [im for im in (images or []) if im is not None and getattr(im, "size", 0)]
    if not frames:
        return None, [], []
    w = min(im.shape[1] for im in frames)
    keep = [im[:, :w] for im in frames]
    h = min(im.shape[0] for im in keep)

    offsets, used = [], [0]
    for i in range(1, len(keep)):
        dy = vertical_offset(keep[i - 1], keep[i])
        offsets.append(dy)
        if dy is not None and dy > 2:
            used.append(i)
    if len(used) == 1:
        return keep[0][:h], [0], []                 # 没测到位移 → 不拼

    # 会滚动的行区间：取所有有效帧对的并集
    r0, r1 = h, 0
    for i in used[1:]:
        band = _moving_band(keep[i - 1], keep[i])
        if band:
            r0, r1 = min(r0, band[0]), max(r1, band[1])
    if r1 <= r0:
        return keep[0][:h], [0], []

    out = keep[0][:r1].copy()                       # 表头 + 第一屏的内容带
    kept_offsets = []
    for i in used[1:]:
        dy = offsets[i - 1]
        if dy is None or dy <= 2:
            continue
        if out.shape[0] + dy > max_height:
            break
        top = max(r0, r1 - dy)                      # 内容带底部"刚露出来"的那几行
        out = np.vstack([out, keep[i][top:r1]])
        kept_offsets.append(dy)
    out = np.vstack([out, keep[used[-1]][r1:h]])    # 静态页脚(不跟着滚)
    return out, used, kept_offsets


def stitch_and_save(path: str, images, max_height: int = 12000):
    """拼长图并落盘；返回 `(路径 or '', 用了几个步, 长图高)`。"""
    img, used, _ = stitch(images, max_height=max_height)
    if img is None:
        return '', 0, 0
    if not imwrite_unicode(path, img):
        return '', 0, 0
    return path, len(used), int(img.shape[0])
