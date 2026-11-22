#!/usr/bin/env python3
r"""离屏渲染评估报告 HTML（QtWebEngine），用于 UI 评审/回归对比。

输入:
  - 一份评估报告 HTML（默认 `eval_report6.html`；离线重放可用 `logs/tmp/replay6.html`）
输出:
  - `logs/ui_audit/report/<名字>_<宽>_{top,mid,table}.png`
支撑:
  - `docs/UI_REVIEW_2026-11-22.md`（报告行密度/判定色/1024 退化的证据）
  - `docs/UI_FIX_HANDOFF.md`（改报告后的目检基线）
用法:
  python tools/shot_report.py eval_report6.html 1440 1024
  python tools/shot_report.py logs/tmp/replay6.html --widths 1440
"""
from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu --no-sandbox')

from PySide6.QtCore import QSize, QUrl                       # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineSettings      # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView       # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shoot(app, src: str, width: int, out_dir: str, height: int = 1000) -> None:
    view = QWebEngineView()
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    view.resize(QSize(width, height))
    view.show()
    loaded = {'ok': False}
    view.loadFinished.connect(lambda ok: loaded.__setitem__('ok', ok))
    view.load(QUrl.fromLocalFile(os.path.abspath(src)))
    deadline = time.time() + 20
    while not loaded['ok'] and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)

    name = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    for tag, js in (('top', 'window.scrollTo(0,0)'),
                    ('mid', 'window.scrollTo(0, 900)'),
                    ('table', 'window.scrollTo(0, 1600)')):
        view.page().runJavaScript(js)
        app.processEvents()
        time.sleep(0.15)
        app.processEvents()
        path = os.path.join(out_dir, f'{name}_{width}_{tag}.png')
        view.grab().save(path)
        print('saved', path)
    view.deleteLater()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('report', nargs='?', default=os.path.join(ROOT, 'eval_report6.html'))
    ap.add_argument('--widths', nargs='+', type=int, default=[1440, 1024])
    ap.add_argument('--out', default=os.path.join(ROOT, 'logs', 'ui_audit', 'report'))
    ap.add_argument('--height', type=int, default=1000)
    args = ap.parse_args()
    app = QApplication([])
    for width in args.widths:
        shoot(app, args.report, width, args.out, args.height)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
