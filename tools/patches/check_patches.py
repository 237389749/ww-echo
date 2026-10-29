"""自检 ok-script 的 4 处 `[ww-echo patch]` 是否还在（升级/重装会丢）。

用法（项目根目录）:
    python tools/patches/check_patches.py          # 全在 → 退出码 0
    python tools/patches/check_patches.py -v       # 打印每处命中行

退出码: 0 全在 / 1 有缺失 / 2 找不到 ok-script。
规格见同目录 `ok-script-1.0.159.md`。
"""

import argparse
import os
import sys

# (相对 site-packages 的路径, 期望出现的标记之一, 说明)
CHECKS = (
    ("ok/gui/StartController.py",
     ("[ww-echo cloud patch] only auto-bring",), "auto-bring-to-front 标志(init)"),
    ("ok/gui/StartController.py",
     ("[ww-echo cloud patch] auto-bring-to-front only when a task start was requested",),
     "do_start 里按 task 置标志"),
    ("ok/gui/StartController.py",
     ("[ww-echo cloud patch] when the user pressed start (task), auto bring",),
     "等待就绪时每轮拉前"),
    ("ok/gui/StartController.py",
     ("[ww-echo patch] cloud mode: never auto-launch the game exe",),
     "start_exe=False 时仍等设备就绪"),
    ("ok/device/capture_methods/hwnd_window.py",
     ("[ww-echo patch] visible = window is not minimized",), "可见性 = 未最小化"),
    ("ok/device/interaction_methods/pynput.py",
     ("[ww-echo cloud patch] ensure the target window is in the foreground",), "_ensure_clickable"),
    ("ok/device/interaction_methods/pynput.py",
     ("[ww-echo patch] do not gate the whole task loop",), "should_capture → True"),
    ("ok/util/window.py",
     ("[ww-echo patch] empty exe entries mean",), "find_hwnd 过滤空 exe"),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    try:
        import ok
    except ImportError:
        print("[X] 找不到 ok-script: 先 `pip install -r requirements.txt`(ok-script==1.0.159)")
        return 2
    site = os.path.dirname(os.path.dirname(os.path.abspath(ok.__file__)))   # .../site-packages
    print(f"site-packages: {site}")

    missing = []
    seen = set()
    for rel, markers, label in CHECKS:
        path = os.path.join(site, *rel.split("/"))
        if not os.path.exists(path):
            missing.append(f"{rel}: 文件不存在({label})")
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        hit = next((m for m in markers if m in text), None)
        if hit is None:
            missing.append(f"{rel}: 缺标记({label})")
            continue
        if args.verbose:
            line = text[: text.index(hit)].count("\n") + 1
            print(f"  [OK] {rel}:{line}  {label}")
        seen.add(rel)

    if missing:
        print(f"\n[X] {len(missing)} 处补丁缺失(升级 ok-script 后需要重打; 规格见 tools/patches/ok-script-1.0.159.md):")
        for m in missing:
            print("   -", m)
        return 1
    print(f"[OK] {len(CHECKS)} 处标记全部在位，涉及 {len(seen)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
