#!/usr/bin/env python3
"""把 `IconExport` 导出的官方贴图按 `assets/gamedata/echo_data.json` 覆盖到 `assets/echo_icons/`。

用法::

    python tools/icon_export/swap_icons.py --official .\\icon_png            # 只看差异(不改文件)
    python tools/icon_export/swap_icons.py --official .\\icon_png --apply    # 真覆盖(先备份旧的)

映射关系 = 生成物的 `sets[*].icon_asset`(客户端贴图名) → `sets[*].icon_file`(`{套装名}.png`)，
所以**不会**出现"图对了名字错了"的错配。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GDATA = REPO / "assets" / "gamedata" / "echo_data.json"
ICONS = REPO / "assets" / "echo_icons"


def main() -> int:
    ap = argparse.ArgumentParser(description="官方贴图 → assets/echo_icons/")
    ap.add_argument("--official", required=True, help="IconExport 的输出目录(PNG)")
    ap.add_argument("--apply", action="store_true", help="真覆盖(默认只报告差异)")
    ap.add_argument("--backup", default=None, help="旧模板备份目录(默认 <official>/../echo_icons_before)")
    a = ap.parse_args()

    official = Path(a.official).resolve()
    if not official.is_dir():
        raise SystemExit(f"找不到官方图目录: {official}")
    data = json.loads(GDATA.read_text(encoding="utf-8"))
    sets = data["sets"]

    added, replaced, same, missing = [], [], 0, []
    for name, v in sorted(sets.items()):
        src = official / f"{v['icon_asset']}.png"
        if not src.exists():
            missing.append(f"{name}({v['icon_asset']})")
            continue
        dst = ICONS / v["icon_file"]
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            same += 1
            continue
        (replaced if dst.exists() else added).append(name)
        if a.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if a.apply and (added or replaced):
        backup = Path(a.backup).resolve() if a.backup else official.parent / "echo_icons_before"
        backup.mkdir(parents=True, exist_ok=True)
        # 备份当前(旧)模板: 只在备份目录里还没有同名文件时复制, 避免把刚覆盖的官方图当"旧图"存两份
        for p in ICONS.glob("*.png"):
            if not (backup / p.name).exists():
                shutil.copy2(p, backup / p.name)
        print(f"旧模板备份 -> {backup}")

    print(f"套装 {len(sets)} 套 | 字节相同 {same} | 新增 {len(added)} | 替换 {len(replaced)} | 缺官方图 {len(missing)}")
    if added:
        print(f"  新增: {added}")
    if replaced:
        print(f"  替换: {replaced}")
    if missing:
        print(f"  ⚠ 缺官方图(先确认 pak 里有该资产): {missing}")
    print("(--apply 才会真正覆盖)" if not a.apply else "已覆盖 assets/echo_icons/")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
