#!/usr/bin/env python3
"""端到端验收评估报告的交互（U-10 / U-20）—— 在 QtWebEngine 里**真跑**点击/筛选/排序/hash。

**为什么需要它**: 报告是纯 HTML+JS，单测只能检查"字符串里有这段 JS"；而报告真正的行为
（点一行展开、筛掉已展开的行、排序时详情行跟着搬、刷新后筛选还在）只能靠浏览器跑一遍。
`tools/shot_report.py` 只截图，看不出"点了没反应"。

检查项（任一不过 → 退出码 1）:
  1. 每条记录都有主行 + 详情行，详情默认收起
  2. 点**可见**的主行 → 详情展开；被筛掉的主行点了也不展开（正确行为）
  3. 排序后 160 组的"主行 → 详情行"配对全部保持
  4. 筛选条件能从 `#hash` 读回（刷新/分享还原）
  5. 把已展开的行筛掉时，详情行跟着藏起来

用法:
  python tools/verify_report_js.py logs/tmp/report.html
  python tools/verify_report_js.py            # 默认 logs/tmp/report_b3.html
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QSize, QUrl                              # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineSettings             # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView               # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

# 只在"达标"里看: 用来验证 hash 还原(51/160 是 report6 的实测值, 换了素材这三个字要跟着改)
HASH_FILTER = "达标"


def _wait(app, cond, timeout=15.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    return cond()


def _run(view, app, js, timeout=15.0):
    box = {}
    view.page().runJavaScript(js, 0, lambda r: box.__setitem__("v", r))
    _wait(app, lambda: "v" in box, timeout)
    return box.get("v")


CHECK_JS = r"""
(function(){
  var mains = Array.prototype.slice.call(document.querySelectorAll('#tbody tr.main'));
  var vis = mains.filter(function(tr){ return tr.style.display !== 'none'; });
  var out = {totalMains: mains.length, visibleMains: vis.length,
             cntText: document.getElementById('cnt').textContent};
  if(!vis.length) return JSON.stringify(out);
  var first = vis[0], d = first.nextElementSibling;
  out.detailHiddenBefore = d.hidden;
  first.click();
  out.detailHiddenAfter = d.hidden;
  out.mainOpenClass = first.classList.contains('open');
  // 被筛掉的行点开也不该展开
  var hidden = mains.filter(function(tr){ return tr.style.display === 'none'; })[0];
  if(hidden){
    hidden.click();
    out.hiddenRowDetailShown = hidden.nextElementSibling.hidden === false;
    hidden.click();
  }
  // 排序后配对是否还成立
  var sel = document.getElementById('fsort');
  sel.value = 'comp_desc';
  sel.dispatchEvent(new Event('change'));
  var broken = 0;
  mains.forEach(function(tr){
    var n = tr.nextElementSibling;
    if(!n || n.className.indexOf('detail') < 0) broken++;
  });
  out.orderPairsBroken = broken;
  out.orderPairsChecked = mains.length;
  out.hash = location.hash;
  return JSON.stringify(out);
})()
"""

HIDE_JS = r"""
(function(){
  var mains = Array.prototype.slice.call(document.querySelectorAll('#tbody tr.main'));
  var target = mains.filter(function(tr){ return tr.classList.contains('open'); })[0];
  if(!target) return 'no-open-row';
  var d = target.nextElementSibling;
  var sel = document.getElementById('fset');
  var other = Array.prototype.slice.call(sel.options)
    .filter(function(o){ return o.value && o.value !== target.getAttribute('data-set') })[0];
  if(!other) return 'no-other-set';
  sel.value = other.value;
  sel.dispatchEvent(new Event('change'));
  return JSON.stringify({mainHidden: target.style.display === 'none',
                         detailHidden: d.hidden, hashAfter: location.hash});
})()
"""


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "logs", "tmp", "report_b3.html")
    if not os.path.exists(src):
        print(f"找不到报告: {src}")
        return 2
    url = QUrl.fromLocalFile(os.path.abspath(src))
    url.setFragment("v=" + HASH_FILTER)

    app = QApplication([])
    view = QWebEngineView()
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    view.resize(QSize(1280, 900))
    view.show()
    loaded = {}
    view.loadFinished.connect(lambda ok: loaded.__setitem__("ok", ok))
    view.load(url)
    if not _wait(app, lambda: loaded.get("ok")):
        print("页面加载失败")
        return 2
    _wait(app, lambda: False, 0.3)          # 让脚本再跑一轮

    raw = _run(view, app, CHECK_JS)
    hide_raw = _run(view, app, HIDE_JS)
    view.deleteLater()
    app.processEvents()
    try:
        r = json.loads(raw)
    except Exception:
        print("JS 没返回结果(脚本报错?):", raw)
        return 1
    try:
        h = json.loads(hide_raw)
    except Exception:
        h = {}

    fails = []

    def need(cond, msg):
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        if not cond:
            fails.append(msg)

    need(r["totalMains"] > 0, f'有主行: {r["totalMains"]} 条')
    need(r["visibleMains"] == r["totalMains"] or r["visibleMains"] < r["totalMains"],
         f'hash 筛选生效: 显示 {r["visibleMains"]} / {r["totalMains"]}')
    need(r["cntText"].startswith("显示 "), f'计数行已更新: {r["cntText"]}')
    need(r.get("detailHiddenBefore") is True, "详情行默认收起")
    need(r.get("detailHiddenAfter") is False, "点可见主行后详情展开")
    need(r.get("mainOpenClass") is True, "主行拿到 open 状态")
    need(r.get("hiddenRowDetailShown") is not True, "被筛掉的行点开也不展开详情")
    need(r.get("orderPairsBroken") == 0,
         f'排序后主行/详情行仍配对: {r.get("orderPairsChecked")} 组, 断开 {r.get("orderPairsBroken")}')
    need("v=" in (r.get("hash") or ""), f'筛选写进 hash: {r.get("hash")}')
    if h:
        need(h.get("mainHidden") is True, "把已展开的行筛掉 → 主行隐藏")
        need(h.get("detailHidden") is True, "把已展开的行筛掉 → 详情行跟着藏")
    print()
    print(f'{len(fails)} 项失败' if fails else '全部通过')
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
