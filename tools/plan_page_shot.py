#!/usr/bin/env python3
"""「组合穷举」页的**填充态**离屏渲染 —— 改结果表 / 动作条 / 汇总后必跑。

**输入**：一份评估产物 JSON（库存）。默认按 `src.echo_inventory.latest_inventory_path()` 找
（与「导入最新素材」同一套逻辑）；也可 `--inventory <路径>`。
**输出**：一张 PNG（默认 `logs/ui_fix/plan_filled.png`）+ stdout 的行数/列宽/状态。
**支撑**：CLAUDE「组合穷举·排名表列宽」与「改结果表后必须跑一次填充页渲染」两条结论。

**为什么必须单独有它**：`tools/ui_shot.py` / `ui_page_shot.py` 只渲染**空页面** —— 结果表 0 行时
`_render()` 根本不会被执行，那里的错误（踩过 `NameError`、列宽算错导致整表 `125...`）它们都抓不到。
这个工具会真的导入库存、跑一次穷举、滚到结果表再抓图。

用法：
    python tools/plan_page_shot.py                          # 自动选库存与套装
    python tools/plan_page_shot.py --set 轻云出月 --size 1120x760
    python tools/plan_page_shot.py --inventory logs/tmp/replay6.json --mode 3+2 --cost4 A
    python tools/plan_page_shot.py --list-sets              # 看库存里各套装的可选件数

退出码：抓到 **0 行** → 2（说明这套装没候选，别拿空表当验收）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtGui import QFont, QFontDatabase                     # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
        if os.path.exists(f):
            QFontDatabase.addApplicationFont(f)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    return app


def _pump(app, times=6):
    for _ in range(times):
        app.processEvents()


def main() -> int:
    ap = argparse.ArgumentParser(description="组合穷举页填充态离屏截图")
    ap.add_argument("--inventory", default="", help="评估产物 JSON（默认找最新素材）")
    ap.add_argument("--set", default="", help="套装 A（默认取满级件最多的那套）")
    ap.add_argument("--set-b", default="", help="套装 B（3+2 时用）")
    ap.add_argument("--mode", default="5", choices=("5", "3+2"))
    ap.add_argument("--cost4", default="", choices=("", "A", "B"), help="3+2 时的 4C 归属")
    ap.add_argument("--size", default="1120x760", help="页面尺寸 WxH")
    ap.add_argument("--out", default=os.path.join("logs", "ui_fix", "plan_filled.png"))
    ap.add_argument("--list-sets", action="store_true", help="只列库存里各套装的可选件数")
    a = ap.parse_args()

    from src.echo_combos import is_max_level
    from src.echo_inventory import latest_inventory_path, load_inventory

    src = a.inventory or latest_inventory_path()
    if not src or not os.path.exists(src):
        print("找不到库存：请先用「运行」页跑一次评估并保存报告（会顺手写出同名 .json），"
              "或显式给 --inventory <路径>")
        return 2
    items = load_inventory(src)
    if not items:
        print(f"库存为空: {src}")
        return 2

    by_set = Counter(i.set_name for i in items if is_max_level(i))
    if a.list_sets:
        print(f"来源: {src}")
        for name, n in by_set.most_common():
            print(f"  {name}: {n} 只满级")
        return 0
    set_a = a.set or (by_set.most_common(1)[0][0] if by_set else "")
    if not set_a:
        print("库存里没有满级件，无法穷举（可先取消「只用满级件」再跑真界面）")
        return 2

    app = _app()
    from ui.plan_tab import PlanTab

    tab = PlanTab()
    w, h = (int(x) for x in a.size.lower().split("x"))
    tab.resize(w, h)
    tab.show()
    _pump(app)

    tab._import(src)
    tab.mode_combo.setCurrentText(a.mode)
    tab.set_a_combo.setCurrentText(set_a)
    if a.set_b:
        tab.set_b_combo.setCurrentText(a.set_b)
    if a.cost4:
        tab.cost4_combo.setCurrentText(a.cost4)
    _pump(app, 3)

    tab._start()
    deadline = time.time() + 60
    while tab._worker is not None and tab._worker.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    _pump(app, 10)

    rows = tab.result_table.rowCount()
    print(f"套装 {set_a} · 模式 {a.mode} → {rows} 行 · 状态: {tab.status.text()}")
    if rows:
        widths = [tab.result_table.columnWidth(c) for c in range(tab.result_table.columnCount())]
        print(f"列宽 {widths} · 视口 {tab.result_table.viewport().width()}")
        try:
            tab.scroll.ensureWidgetVisible(tab.result_table)
            _pump(app)
        except Exception:                                   # noqa: BLE001 - 滚不动也要出图
            pass

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    tab.update()
    app.processEvents()
    tab.grab().save(a.out)
    print(f"saved {a.out}  ({tab.width()}x{tab.height()})")

    # 主动销毁顶层窗口（进程里 import 过 ww_engine 时, 退出期与仍存活的窗口抢顺序会段错误）
    tab.hide()
    tab.deleteLater()
    _pump(app, 2)

    if not rows:
        # 注意: 控制台是 GBK, print 里不能出现 ⚠/→ 这类非 GBK 字符(有守卫 tests/test_gbk_output.py)
        print("注意: 0 行 —— 这套装没有候选组合，别拿这张空表当验收")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
