r"""键盘遍历可行性探针（真机，需管理员运行）。

输入: 游戏已启动、停在**背包 → 声骸列表**界面（任意排序），窗口可见
输出: 控制台逐步日志 + `%TEMP%/probe_kbd/step_*.png`（每一步的详情面板裁剪）
支撑结论: 评估能否改成「点第一格 → 方向键逐格 → 每格读右侧面板」的**零坐标遍历**
（不再依赖 +xx 角标 OCR / 分辨率坐标；配合「等级顺序」排序还能早停）。

运行（管理员 cmd）:
    cd /d C:\Users\admin\Downloads\ww-echo
    C:\\Users\\admin\\AppData\\Local\\Temp\\ww-echo-venv313\\Scripts\\python.exe tools\\analysis\\probe_keyboard_nav.py

判读:
    step 记录里 title 每次变化 = 方向键能移格；
    按 → 越过最后一列 / 按 ↓ 越过最后一行后，网格是否整体位移 = 边界能否自动滚屏。
"""
import os
import re
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

OUT = os.path.join(os.environ['TEMP'], 'probe_kbd')
os.makedirs(OUT, exist_ok=True)


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
executor.paused = False

from src.task.EnhanceEchoTask import EnhanceEchoTask  # noqa: E402
from src import echo_grid  # noqa: E402

task = executor.get_task_by_class(EnhanceEchoTask)


def grab():
    f = None
    t0 = time.time()
    while f is None and time.time() - t0 < 8:
        f = dm.capture_method.get_frame()
        if f is None:
            time.sleep(0.1)
    return f


def panel_info(frame):
    """读右侧详情：返回 (标题, 行列表)。仅用于探针判读，不参与评估逻辑。"""
    texts = task.ocr(0.66, 0.09, 0.995, 0.70, frame=frame)
    rows = []
    for b in texts:
        name = str(getattr(b, 'name', '') or '').strip()
        if name and len(re.findall(r'[\u4e00-\u9fff]', name)) >= 2:
            rows.append((int(b.y), name))
    rows.sort()
    title = ''
    for y, name in rows:
        if len(name) >= 3:
            title = name
            break
    return title, [n for _, n in rows]


def grid_cells(frame):
    """复用评估的网格几何：两路 OCR 并集 + 推断，返回像素点击点。"""
    fh, fw = frame.shape[:2]
    grid_box = (0.10, 0.15, 0.72, 0.92)
    sx0, sx1, sy0, sy1 = 0.075 * fw, 0.655 * fw, 0.10 * fh, 0.90 * fh
    texts = list(task.ocr(*grid_box, frame=frame)) + list(task.ocr(0, 0, 1, 1, frame=frame))
    marks = echo_grid.merge_badge_marks(texts, roi=(sx0, sy0, sx1, sy1))
    cells = echo_grid.cells_from_marks(marks, (sx0, sy0, sx1, sy1),
                                       row_tol=max(20.0, fh * 0.03),
                                       col_gap=max(50.0, fw * 0.046))
    return cells


def save_step(tag, frame):
    path = os.path.join(OUT, f'step_{tag}.png')
    try:
        import cv2
        cv2.imwrite(path, frame)
    except Exception as e:
        log(f'  保存截图失败: {e}')
    return path


frame = grab()
if frame is None:
    log('[x] 抓不到画面, 退出')
    os._exit(1)
fh, fw = frame.shape[:2]
log(f'frame: {frame.shape}')

count = [(str(b.name), round(float(getattr(b, 'confidence', 0) or 0), 2))
         for b in task.ocr(0.02, 0.02, 0.25, 0.09, frame=frame)]
log(f'页面锚点: {count}')
if not any('声骸' in n for n, _ in count):
    log('[x] 左上没看到「声骸N/3000」: 请先停在背包声骸列表界面再跑本探针')
    og.exit_event.set()
    app.quit()
    os._exit(1)

cells = grid_cells(frame)
log(f'网格标定: {len(cells)} 格; 第一格={cells[0] if cells else None}')
if not cells:
    log('[x] 网格为空, 退出')
    os._exit(1)

first = cells[0]
task.click(first[0] / fw, first[1] / fh, after_sleep=1.0)
frame = grab()
title0, rows0 = panel_info(frame)
log(f'点击第一格后: 标题={title0!r} 行数={len(rows0)} 行={rows0[:6]}')
save_step('00_first', frame)

# 1) 逐格右移
prev = (title0, tuple(rows0))
for i in range(1, 7):
    task.send_key('right', after_sleep=0.9)
    frame = grab()
    title, rows = panel_info(frame)
    changed = (title, tuple(rows)) != prev
    log(f'右移#{i}: 标题={title!r} changed={changed} 行={rows[:5]}')
    save_step(f'right_{i}', frame)
    prev = (title, tuple(rows))

# 2) 下移（测跨行）
for i in range(1, 4):
    task.send_key('down', after_sleep=0.9)
    frame = grab()
    title, rows = panel_info(frame)
    changed = (title, tuple(rows)) != prev
    log(f'下移#{i}: 标题={title!r} changed={changed} 行={rows[:5]}')
    save_step(f'down_{i}', frame)
    prev = (title, tuple(rows))

# 3) 滚屏测试: 连续下移, 看网格整体有没有位移（自动滚屏?）
before = grid_cells(grab()) or []
for i in range(4):
    task.send_key('down', after_sleep=0.4)
time.sleep(1.0)
after_frame = grab()
after = grid_cells(after_frame) or []
log(f'连续下移后网格: before={before[:2]} after={after[:2]}')
if before and after:
    dy = after[0][1] - before[0][1]
    dx = after[0][0] - before[0][0]
    log(f'首格位移: dx={dx} dy={dy}  ("列表自动滚屏"应表现为 dy 明显 != 0)')
save_step('after_scroll', after_frame)

log(f'截图目录: {OUT}')
dm.stop_hwnd()
og.exit_event.set()
app.quit()
log('probe done', flush=True)
os._exit(0)
