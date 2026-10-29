"""把 ww-echo 需要的 4 处补丁打到已安装的 ok-script 上（幂等、可重放）。

背景：ok-script **<=1.0.159 在 PyPI 上钉了 `Requires-Python ==3.12.*`；1.0.160 起改为 `>=3.11`**，
而两者的 `ok/` 代码逐字节一致（只改了 dist-info 元数据）—— 所以升级到 1.0.160 是"去掉 3.12 限制"的最短路径。
代价是：升级/重装会抹掉 site-packages 里的手工补丁。本脚本把这些补丁变成可重放的步骤。

用法（项目根目录，装好 ok-script 之后）:
    python tools/patches/apply_patches.py                 # 打补丁（已在位则跳过）
    python tools/patches/apply_patches.py --dry-run       # 只报告会改什么
    python tools/patches/apply_patches.py --site <dir>    # 指定 site-packages（如某个 venv）

规则：
- 每处补丁带 `[ww-echo ... patch]` 标记；
- 插入型：标记已在 → 跳过；否则要求锚点**唯一**后插入；
- 替换型：原文还在 → 替换（`all_occurrences` 时全替换）；原文不在 → 有标记算已打，无标记报错；
- 任何"锚点找不到/不唯一"都**不猜**，退出码 1。
"""

import argparse
import os


class Patch:
    def __init__(self, rel, old, new, marker, label, *, insert=True, all_occurrences=False):
        self.rel, self.old, self.new = rel, old, new
        self.marker, self.label = marker, label
        self.insert, self.all_occurrences = insert, all_occurrences


PATCHES = (
    # ── 1. StartController：用户点"开始"才把窗口拉前；start_exe=False 时仍等设备就绪 ──
    Patch("ok/gui/StartController.py",
          "        self.start_method = windows_config.get('start_method', WINDOWS_START_METHOD_START)\n",
          "        self.start_method = windows_config.get('start_method', WINDOWS_START_METHOD_START)\n"
          "        # [ww-echo cloud patch] only auto-bring the game window to the foreground\n"
          "        # when the user actually pressed start (task is not None), never on app boot.\n"
          "        self._auto_bring_to_front = False\n",
          "ww-echo cloud patch] only auto-bring", "标志位（init）"),
    Patch("ok/gui/StartController.py",
          "    def do_start(self, task=None, exit_after=False):\n",
          "    def do_start(self, task=None, exit_after=False):\n"
          "        # [ww-echo cloud patch] auto-bring-to-front only when a task start was requested\n"
          "        self._auto_bring_to_front = task is not None\n",
          "ww-echo cloud patch] auto-bring-to-front only", "do_start 置标志"),
    Patch("ok/gui/StartController.py",
          "                logger.info('windows.start_exe is False, skip start_device')\n",
          "                logger.info('windows.start_exe is False, skip start_device')\n"
          "                # [ww-echo patch] cloud mode: never auto-launch the game exe, but still\n"
          "                # wait until the already-connected window is device-ready (auto-bring-to-front).\n"
          "                if not self._wait_until_device_ready():\n"
          "                    return False\n",
          "ww-echo patch] cloud mode: never auto-launch", "start_exe=False 仍等就绪"),
    Patch("ok/gui/StartController.py",
          "    def _wait_until_device_ready(self):\n"
          "        wait_until = time.time() + self.start_timeout\n"
          "        while not self.exit_event.is_set():\n",
          "    def _wait_until_device_ready(self):\n"
          "        wait_until = time.time() + self.start_timeout\n"
          "        while not self.exit_event.is_set():\n"
          "            # [ww-echo cloud patch] when the user pressed start (task), auto bring\n"
          "            # the game window to the foreground (also restoring it from minimized)\n"
          "            # before each device check; on plain app boot this is skipped.\n"
          "            hwnd_window = getattr(og.device_manager, 'hwnd_window', None)\n"
          "            if self._auto_bring_to_front and hwnd_window is not None and hwnd_window.hwnd:\n"
          "                try:\n"
          "                    hwnd_window.bring_to_front()\n"
          "                except Exception as e:\n"
          "                    logger.error(f'bring_to_front in wait_until_device_ready failed: {e}')\n",
          "ww-echo cloud patch] when the user pressed start", "等待就绪时每轮拉前"),

    # ── 2. 可见性 = 未最小化（BitBlt 能抓后台窗口） ──
    Patch("ok/device/capture_methods/hwnd_window.py",
          "                    visible = self.is_foreground()\n",
          "                    # [ww-echo patch] visible = window is not minimized (capturable),\n"
          "                    # NOT whether it is the foreground window: BitBlt_RenderFull can capture\n"
          "                    # background/occluded windows fine. Foreground is only required by the\n"
          "                    # Pynput click layer (_ensure_clickable), which auto-brings to front.\n"
          "                    visible = not win32gui.IsIconic(self.hwnd)\n",
          "ww-echo patch] visible = window is not minimized", "可见性判定", insert=False),

    # ── 3. pynput：动作前自动拉前；主循环不被前台门控 ──
    Patch("ok/device/interaction_methods/pynput.py",
          "    def _parse_key(self, key):\n",
          "    def _ensure_clickable(self):\n"
          "        \"\"\"[ww-echo cloud patch] ensure the target window is in the foreground before\n"
          "        an actual action (click/key/scroll); auto brings it to front instead of failing.\"\"\"\n"
          "        if self.clickable():\n"
          "            return True\n"
          "        try:\n"
          "            self.hwnd_window.bring_to_front()\n"
          "        except Exception as e:\n"
          "            logger.error(f'pynput _ensure_clickable bring_to_front failed: {e}')\n"
          "        time.sleep(0.2)\n"
          "        return self.clickable()\n"
          "\n"
          "    def _parse_key(self, key):\n",
          "ww-echo cloud patch] ensure the target window", "新增 _ensure_clickable"),
    Patch("ok/device/interaction_methods/pynput.py",
          "        if not self.clickable():\n",
          "        if not self._ensure_clickable():\n",
          "ww-echo cloud patch] ensure the target window", "动作前拉前（7 处）",
          insert=False, all_occurrences=True),
    Patch("ok/device/interaction_methods/pynput.py",
          "    def should_capture(self):\n        return self.clickable()\n",
          "    def should_capture(self):\n"
          "        # [ww-echo patch] do not gate the whole task loop on the window being in the\n"
          "        # foreground (that made the task freeze whenever the user switched away).\n"
          "        # Actual clicks/keys auto bring the window to front via _ensure_clickable.\n"
          "        return True\n",
          "ww-echo patch] do not gate the whole task loop", "should_capture", insert=False),

    # ── 4. find_hwnd：空 exe 项 = 不做进程过滤（云模式 selected_exe=''） ──
    Patch("ok/util/window.py",
          "    if isinstance(exe_names, str):\n        exe_names = [exe_names]\n",
          "    if isinstance(exe_names, str):\n        exe_names = [exe_names]\n"
          "    # [ww-echo patch] empty exe entries mean \"no process filter\" (e.g. selected_exe=''\n"
          "    # in cloud mode must not make every window fail the exe match)\n"
          "    exe_names = [e for e in (exe_names or []) if e]\n",
          "ww-echo patch] empty exe entries mean", "find_hwnd 过滤空 exe"),
)


def find_site() -> str:
    import ok
    return os.path.dirname(os.path.dirname(os.path.abspath(ok.__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="", help="site-packages 目录（默认从已安装的 ok 推导）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        site = args.site or find_site()
    except ImportError:
        print("[X] 找不到 ok-script: 先 pip install -r requirements.txt")
        return 2
    print(f"site-packages: {site}")

    applied = skipped = 0
    failed, touched = [], set()
    for p in PATCHES:
        path = os.path.join(site, *p.rel.split("/"))
        if not os.path.exists(path):
            failed.append(f"{p.rel}: 文件不存在")
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()

        present = p.old in text
        marked = p.marker in text
        if p.insert:
            if marked:
                skipped += 1
                continue
            if not present or text.count(p.old) != 1:
                failed.append(f"{p.rel}: 锚点{'不存在' if not present else '不唯一'}({p.label})")
                continue
            out = text.replace(p.old, p.new, 1)
        else:
            if present:
                if not p.all_occurrences and text.count(p.old) != 1:
                    failed.append(f"{p.rel}: 锚点不唯一({p.label})")
                    continue
                out = text.replace(p.old, p.new) if p.all_occurrences else text.replace(p.old, p.new, 1)
            elif marked:
                skipped += 1
                continue
            else:
                failed.append(f"{p.rel}: 锚点不存在({p.label}) —— ok-script 版本/结构变了?")
                continue

        if args.dry_run:
            print(f"  [WOULD] {p.rel}: {p.label}")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"  [APPLY] {p.rel}: {p.label}")
        applied += 1
        touched.add(p.rel)

    if failed:
        print(f"\n[X] {len(failed)} 处失败:")
        for m in failed:
            print("   -", m)
        return 1
    print(f"\n[OK] 应用 {applied} 处, 跳过(已在位) {skipped} 处, 涉及 {len(touched)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
