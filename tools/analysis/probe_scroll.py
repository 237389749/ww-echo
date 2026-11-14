r"""滚轮实测探针（真机）：量「一格滚轮 = 多少像素」+「动画多久停」。

输入: 游戏已启动、停在**背包 → 声骸列表**界面（窗口可见）。
输出: 控制台报告 + `%TEMP%/probe_scroll/*.png`（抓到的帧）。
支撑结论:
  - `ScrollModel.px_per_notch` 的初值(8.0@1920)与 **窗口缩放** 的关系；
  - 滚动是**动画**还是瞬时 —— 决定 `scroll_grid` 该等多久 / 该怎么判定；
  - `estimate_row_shift` 在真实帧上的可信度(残差 diff)。

两个模式:
    # 只读：抓一帧 + 网格几何报告（不需要管理员，不影响游戏）
    python tools/analysis/probe_scroll.py --capture

    # 真滚轮实测（需要管理员：游戏是高权限，UIPI 会拒普通权限的输入）
    python tools/analysis/probe_scroll.py --scroll
    python tools/analysis/probe_scroll.py --scroll --notches 40 --hold 3.0

判读:
    `t=+0.15s ... +0.60s` 期间位移还在涨 → 滚动有动画，0.6s 采样必然低估；
    `px/格` 各档接近 → 线性模型成立；相差很大 → 有加速度/惯性，要按残余闭环。
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

OUT = os.path.join(os.environ['TEMP'], 'probe_scroll')
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
            time.sleep(0.1)
    return f


def grid_rect(fw, fh):
    return (max(0.0, 0.075 * fw), 0.10 * fh, 0.655 * fw, 0.90 * fh)


def save(tag, frame):
    import cv2
    path = os.path.join(OUT, f'{tag}.png')
    cv2.imwrite(path, frame)
    return path


def report_geometry(frame):
    fh, fw = frame.shape[:2]
    rect = grid_rect(fw, fh)
    rows, pitch = echo_grid.detect_row_lines(frame, rect)
    log(f'帧: {fw}x{fh}  网格ROI: {tuple(int(v) for v in rect)}')
    log(f'行检测: {len(rows)} 行 rows={[round(r, 1) for r in rows]} 行距={pitch and round(pitch, 1)}')
    struct = echo_grid.detect_grid_structure(frame, rect)
    if struct:
        log(f'结构标定: 列={[round(c, 1) for c in struct["cols"]]} '
            f'行={[round(r, 1) for r in struct["rows"]]} 行距={struct["row_pitch"]:.1f}')
        model = echo_grid.GridModel.from_structure(struct, fw)
        if model:
            log(f'比例模型: 列距={model.col_pitch_ratio:.4f}W 行距={model.row_pitch_ratio:.4f}W '
                f'首列={model.anchor_col_ratio:.4f}W 列数={model.cols}')
    else:
        log('结构标定: 失败(空帧/不在背包列表)')
    return rows, pitch, rect


def set_cursor_grid(rel_x=0.52, rel_y=0.5):
    import ctypes
    import win32gui
    hwnd_window = getattr(dm, 'hwnd_window', None)
    if hwnd_window is None or not hwnd_window.hwnd:
        raise RuntimeError('没有 hwnd')
    hwnd_window.bring_to_front()
    time.sleep(0.15)
    target = getattr(hwnd_window, 'top_hwnd', None) or hwnd_window.hwnd
    f = grab()
    fh_, fw_ = f.shape[:2]
    ax, ay = win32gui.ClientToScreen(target, (int(fw_ * rel_x), int(fh_ * rel_y)))
    ctypes.windll.user32.SetCursorPos(int(ax), int(ay))
    time.sleep(0.1)
    return (ax, ay)


def sample_shift(before, rect, pitch, hold=3.0, interval=0.12):
    """滚完后的位移采样曲线：[(t, rows, diff), ...]"""
    out = []
    t0 = time.time()
    while True:
        t = time.time() - t0
        if t > hold:
            break
        f = grab()
        if f is not None and f.shape == before.shape:
            rows, diff = echo_grid.estimate_row_shift(before, f, rect, pitch)
            out.append((t, rows, diff))
        time.sleep(interval)
    return out


def do_scroll(notches, hold):
    from pynput.mouse import Controller
    before = grab()
    if before is None:
        log('[x] 抓不到画面')
        return
    save('before', before)
    rows0, pitch, rect = report_geometry(before)
    if not pitch:
        log('[x] 没检测到行距，可能不在背包列表')
        return
    set_cursor_grid()
    log(f'发滚轮: {notches} 格 (向下)')
    Controller().scroll(0, -int(notches))
    curve = sample_shift(before, rect, pitch, hold=hold)
    log(f'--- 位移曲线 (行距={pitch:.1f}px) ---')
    for t, r, d in curve:
        log(f'  t=+{t:4.2f}s  位移={r:+.2f} 行 ({r * pitch:+7.1f} px)  残差diff={d:5.1f}')
    if not curve:
        return
    final = curve[-1][1]
    log(f'--- 结论 ---')
    log(f'  {notches} 格 → 最终 {final:+.2f} 行 = {final * pitch:+.0f} px'
        f'  ⇒ {abs(final * pitch) / max(1, notches):.2f} px/格')
    for frac in (0.25, 0.5, 0.75, 1.0):
        idx = min(len(curve) - 1, int(len(curve) * frac) - 1)
        if idx >= 0:
            log(f'  动画进度参考: t={curve[idx][0]:.2f}s 时完成 {curve[idx][1] / final * 100 if final else 0:.0f}%')
    settle = [t for t, r, _ in curve if abs(r - final) < 0.1]
    if settle:
        log(f'  首次稳定在最终值: t={settle[0]:.2f}s (此后无变化)')
    after = grab()
    save('after', after)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', action='store_true', help='只抓帧做几何报告（只读，不需管理员）')
    ap.add_argument('--scroll', action='store_true', help='真滚轮实测（需管理员）')
    ap.add_argument('--notches', type=int, default=20)
    ap.add_argument('--hold', type=float, default=3.0, help='滚完后采样秒数')
    args = ap.parse_args()

    frame = grab()
    if frame is None:
        log('[x] 抓不到画面（游戏窗口在吗？）')
        return 1
    save('frame', frame)
    rows, pitch, rect = report_geometry(frame)
    log(f'截图: {OUT}')

    if args.scroll:
        do_scroll(args.notches, args.hold)
    dm.stop_hwnd()
    og.exit_event.set()
    app.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
