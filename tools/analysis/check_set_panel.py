r"""离线验证「详情面板找套装」：拿面板截图跑 OCR，看能不能认出套装名 / 合鸣效果。

输入: 一张或多张**详情面板截图**（不需要开游戏；截图可以是用户拍的整块面板）。
输出: 每张图的 OCR 行 + `match_set_text`（套装名，候选/全量两种）+ `match_set_effect`（效果文本匹配）。

支撑结论: "套装名文字"这条路在真实 OCR 输出上到底能不能命中（2026-11-18 用它验证了
用户提供的三张不同滚动位置的面板图：顶部 / 中部 / 底部合鸣效果区）。

用法:
    python tools/analysis/check_set_panel.py shot1.png shot2.png ...
    python tools/analysis/check_set_panel.py shot.png --candidates 雪落无声之愿 轻云出月
"""
import argparse
import os
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from config import config, apply_run_mode, MODE_LOCAL  # noqa: E402
apply_run_mode(MODE_LOCAL)

from ww_engine import OK, og  # noqa: E402

config['check_mutex'] = False
OK(config)
executor, dm = og.executor, og.device_manager

from src.echo_set_templates import (match_set_effect, match_set_text,  # noqa: E402
                                    get_all_set_names)


def log(msg):
    print(msg, flush=True)


def wait_for(pred, timeout=20, step=0.25):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def ocr_image(task, path):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log(f'[x] 读不到图: {path}')
        return None, []
    return img, list(task.ocr(0, 0, 1, 1, frame=img))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('images', nargs='+')
    ap.add_argument('--candidates', nargs='*', default=None,
                    help='限定候选套装(默认放开到全部 37 套)')
    args = ap.parse_args()

    dm.refresh()
    wait_for(lambda: dm.device_dict)
    dm.set_preferred_device()
    wait_for(lambda: dm.capture_method and dm.interaction)
    # `task.ocr()` 在 executor.paused=True 时会 sleep 等待 → 离线跑必须显式放开
    executor.paused = False

    from src.task.EnhanceEchoTask import EnhanceEchoTask
    task = executor.get_task_by_class(EnhanceEchoTask)
    cands = args.candidates or None

    for path in args.images:
        log(f'\n=== {os.path.basename(path)} ===')
        img, texts = ocr_image(task, path)
        if img is None:
            continue
        log(f'帧 {img.shape[1]}x{img.shape[0]}, OCR {len(texts)} 行')
        for b in sorted(texts, key=lambda b: (b.y, b.x)):
            name = str(getattr(b, 'name', '') or '')
            if len([c for c in name if '\u4e00' <= c <= '\u9fff']) >= 2:
                log(f'  y={b.y:4d} x={b.x:4d} conf={getattr(b, "confidence", 0):.2f}  {name!r}')
        named, how = match_set_text(texts, cands)
        log(f'→ 套装名文字: {named!r} ({how})' + ('' if cands is None else f'  候选={cands}'))
        if not named and cands:
            named_all, how_all = match_set_text(texts)
            log(f'→ 放开全部: {named_all!r} ({how_all})')
        cand, s1, s2 = match_set_effect(texts, cands)
        log(f'→ 合鸣效果: {cand!r} (覆盖 {s1:.2f} / 次优 {s2:.2f})')

    log(f'\n全部套装名共 {len(get_all_set_names())} 个')
    dm.stop_hwnd()
    og.exit_event.set()
    app.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
