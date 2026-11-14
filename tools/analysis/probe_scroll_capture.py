r"""滚动实拍探针（只读，不需要管理员）：连续抓帧，用真滚动的帧对反推位移。

输入: 游戏停在**背包 → 声骸列表**界面，窗口可见；运行期间**用鼠标滚轮滚一下列表**（滚 3~5 格即可）。
输出: `%TEMP%/scroll_seq/frame_XX.png` + 控制台表格（每帧相对第 0 帧的 `estimate_row_shift` 结果、
      画面变化占比，以及用模板匹配算出的**真值位移**）。
支撑结论: 真机上 `estimate_row_shift` 到底准不准、动画要等多久才停、残差为什么高。

运行（普通权限即可，截图不受 UIPI 影响）:
    python tools/analysis/probe_scroll_capture.py --seconds 8 --fps 6

判读:
    - 真值列（模板匹配）在变化过程中应该单调增加，最后稳定在 N.xx 行；
    - 若"估计"那一列与真值差很远 → 估计器在真实帧上不可用，要换算法；
    - 最后一帧与最早一帧的差值就是这次滚动的真实位移（用它校准 px/格）。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.getcwd())

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from config import config, apply_run_mode, MODE_LOCAL  # noqa: E402
apply_run_mode(MODE_LOCAL)

from ww_engine import OK, og  # noqa: E402

config['check_mutex'] = False
OK(config)
executor, dm = og.executor, og.device_manager

OUT = os.path.join(os.environ['TEMP'], 'scroll_seq')
os.makedirs(OUT, exist_ok=True)

from src import echo_grid  # noqa: E402


def log(msg):
    print(msg, flush=True)


def wait_for(pred, timeout=20, step=0.25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


dm.refresh()
wait_for(lambda: dm.device_dict)
dm.set_preferred_device()
wait_for(lambda: dm.capture_method and dm.interaction)


def grab():
    f = None
    t0 = time.time()
    while f is None and time.time() - t0 < 8:
        f = dm.capture_method.get_frame()
        if f is None:
            time.sleep(0.05)
    return f


def grid_rect(fw, fh):
    return (max(0.0, 0.075 * fw), 0.10 * fh, 0.655 * fw, 0.90 * fh)


def template_shift(before, after, rect, pitch, rows=6):
    """**真值**估计：拿 before 底部几块卡片图，在 after 里做竖直模板匹配，取中位位移。

    为什么不用整块灰度差(estimate_row_shift)：卡片大面积是平坦色，整块均值差对
    10~30px 的小位移不敏感；单卡纹理(图标/角标/边框)匹配能给出确定的行位移。
    返回 (dy_px, 匹配置信度) 或 (None, 0)。
    """
    import cv2
    import numpy as np
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    g0 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    h, w = g0.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    max_dy = int(rows * pitch)
    cands = []
    # 在 before 的下部取几块「卡片图标区」当模板（滚动后它们会出现在上方）
    for frac in (0.72, 0.82, 0.92):
        ty = int(y0 + (y1 - y0) * frac) - 30
        for tx in (x0 + 20, x0 + (x1 - x0) // 2, x1 - 140):
            tpl = g0[ty:ty + 60, tx:tx + 60]
            if tpl.shape[0] < 20 or tpl.shape[1] < 20:
                continue
            # 在 after 的同一列、向上 max_dy 范围内搜
            sy0 = max(0, ty - max_dy - 20)
            sy1 = min(h, ty + 20)
            if sy1 - sy0 < tpl.shape[0]:
                continue
            region = g1[sy0:sy1, tx:tx + tpl.shape[1]]
            if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
                continue
            res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)
            if maxv >= 0.60:
                cands.append((ty - (sy0 + maxloc[1]), maxv))   # 正 = 内容向上移
    if not cands:
        return None, 0.0
    cands.sort(key=lambda c: c[0])
    mid = cands[len(cands) // 2]
    return float(mid[0]), float(mid[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=8.0)
    ap.add_argument('--fps', type=float, default=6.0)
    args = ap.parse_args()

    base = grab()
    if base is None:
        log('[x] 抓不到画面')
        return 1
    fh, fw = base.shape[:2]
    rect = grid_rect(fw, fh)
    rows, pitch = echo_grid.detect_row_lines(base, rect)
    log(f'帧 {fw}x{fh}  行检测 {len(rows)} 行 行距={pitch}')
    if not pitch:
        log('[x] 没检测到网格行线 —— 请先停在背包声骸列表再跑')
        return 1
    log(f'现在开始 {args.seconds:.0f}s 抓帧，**请用滚轮滚一下列表**（不用很猛，3~5 格即可）…')

    import cv2
    frames = []
    t0 = time.time()
    interval = 1.0 / max(1.0, args.fps)
    while time.time() - t0 < args.seconds:
        f = grab()
        if f is not None:
            idx = len(frames)
            frames.append(f)
            cv2.imwrite(os.path.join(OUT, f'frame_{idx:02d}.png'), f)
        time.sleep(interval)

    log(f'抓到 {len(frames)} 帧 → {OUT}')
    log('相对于第 0 帧：')
    log(f'  {"帧":>3} {"估计(行)":>9} {"残差":>6} {"变化":>6} {"真值(行)":>9} {"模板s1":>7}')
    for i in range(1, len(frames)):
        rows_i, diff = echo_grid.estimate_row_shift(frames[0], frames[i], rect, pitch)
        change = echo_grid.frame_change_ratio(frames[0], frames[i], rect)
        dy, conf = template_shift(frames[0], frames[i], rect, pitch)
        truth = f'{dy / pitch:+.2f}' if dy is not None else '   -'
        log(f'  {i:>3} {rows_i:>+9.2f} {diff:>6.1f} {change:>6.0%} {truth:>9} {conf:>7.2f}')

    # 相邻帧之间的变化：判断动画什么时候停（最后一列应该趋近 0）
    log('相邻帧变化（趋近 0% 即画面已停）：')
    for i in range(1, len(frames)):
        ch = echo_grid.frame_change_ratio(frames[i - 1], frames[i], rect)
        log(f'  {i - 1}→{i}: {ch:.1%}')

    dm.stop_hwnd()
    og.exit_event.set()
    app.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
