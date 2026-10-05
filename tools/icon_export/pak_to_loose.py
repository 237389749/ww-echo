#!/usr/bin/env python3
"""客户端 pak → 松散文件树（只取匹配的资产），供 `IconExport`(CUE4Parse) 解成 PNG。

复用旁仓 `ww-explore/scripts/pak_extract.py` 的 WuWa pak 解析（位重排 / CustomData / 部分加密 / Oodle），
只把它的 `ClientZip` 换成"真实 pak 文件"适配层（同一 read/read_tail 接口）。

用法::

    python tools/icon_export/pak_to_loose.py --client "<游戏根目录>" --ww-explore ..\\search\\ww-explore
    # 只列不导
    python tools/icon_export/pak_to_loose.py --client "<游戏根目录>" --ww-explore ... --list

产物目录结构 = pak 内挂载路径去掉 `Client/Content/` 前缀（如
`<out>/Aki/UI/UIResources/Common/Image/IconElementAttri/T_IconElementAttriIce.uasset`），
正是 CUE4Parse 松散文件提供者要求的布局。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


class PakFile:
    """单个 .pak 文件 → PakIndex 需要的随机读接口。"""

    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "rb")
        self._size = path.stat().st_size

    def read(self, name, offset, size):
        if offset < 0 or size < 0 or offset + size > self._size:
            raise ValueError(f"越界 {self.path.name}: {offset}+{size} > {self._size}")
        self._fh.seek(offset)
        return self._fh.read(size)

    def read_tail(self, name, n):
        n = min(n, self._size)
        return self.read(name, self._size - n, n)


def load_parser(ww_explore: Path):
    """从 ww-explore 载入 pak 解析器（它是本工具唯一的外部代码依赖）。"""
    scripts = ww_explore / "scripts"
    if not (scripts / "pak_extract.py").exists():
        raise SystemExit(f"找不到 {scripts / 'pak_extract.py'}（用 --ww-explore 指定 ww-explore 仓库根）")
    sys.path.insert(0, str(scripts))
    import pak_extract as P  # noqa: PLC0415
    return P


def find_paks(client_root: Path) -> Path:
    """<游戏根> 或 <Content/Paks> 都能接受。"""
    for cand in (client_root, client_root / "Client/Content/Paks", client_root / "Content/Paks"):
        if cand.is_dir() and any(cand.glob("*.pak")):
            return cand
    raise SystemExit(f"在 {client_root} 下找不到 *.pak（传游戏根目录或 Content/Paks）")


def main() -> int:
    ap = argparse.ArgumentParser(description="客户端 pak → 松散文件树（默认只取 IconElementAttri*）")
    ap.add_argument("--client", required=True, help="游戏根目录(含 Client/Content/Paks) 或 Paks 目录本身")
    ap.add_argument("--ww-explore", default=r"..\search\ww-explore", help="ww-explore 仓库根")
    ap.add_argument("--keys", default=None, help="wuwa-keys.json（默认取 <ww-explore>/wuwa-keys.json）")
    ap.add_argument("--grep", default=r"IconElementAttri", help="资产路径正则")
    ap.add_argument("--out", default="icon_loose", help="松散树输出目录")
    ap.add_argument("--list", action="store_true", help="只列命中，不导出")
    a = ap.parse_args()

    ww = Path(a.ww_explore).resolve()
    P = load_parser(ww)
    key_file = Path(a.keys) if a.keys else ww / "wuwa-keys.json"
    key = bytes.fromhex(json.loads(key_file.read_text(encoding="utf-8"))["mainKey"][2:])

    paks_dir = find_paks(Path(a.client).resolve())
    paks = sorted(paks_dir.glob("*.pak"))
    pat = re.compile(a.grep)
    print(f"pak 目录: {paks_dir}\n  {len(paks)} 个 pak；匹配正则: {pat.pattern}")

    out = Path(a.out)
    hits: list[tuple[str, str]] = []
    t0 = time.time()
    for i, pk in enumerate(paks, 1):
        try:
            idx = P.PakIndex(PakFile(pk), pk.name, key)
        except Exception as exc:                       # noqa: BLE001
            print(f"  [跳过] {pk.name}: {exc}")
            continue
        got = [p for p in idx.entries if pat.search(p)]
        if got:
            hits += [(pk.name, p) for p in got]
            print(f"  [{i}/{len(paks)}] {pk.name}: 命中 {len(got)}")
    print(f"共命中 {len(hits)} 个文件，扫描用时 {time.time() - t0:.0f}s")
    if a.list or not hits:
        for pak, p in hits[:40]:
            print(f"  [{pak}] {p}")
        return 0 if hits else 1

    # 每个 pak 只建一次索引，再逐个读文件
    by_pak: dict[str, list[str]] = {}
    for pak, p in hits:
        by_pak.setdefault(pak, []).append(p)
    oodle, ok, fail = None, 0, 0
    for pak, paths in by_pak.items():
        idx = P.PakIndex(PakFile(paks_dir / pak), pak, key)
        for p in paths:
            if oodle is None:
                oodle = P.Oodle()
            try:
                data = idx.read_file(PakFile(paks_dir / pak), oodle, p)
            except Exception as exc:                   # noqa: BLE001
                print(f"  ✗ {p}: {exc}")
                fail += 1
                continue
            rel = idx._normalize(p).removeprefix("Client/Content/")
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            ok += 1
    print(f"导出完成: 成功 {ok} / 失败 {fail} → {out.resolve()}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
