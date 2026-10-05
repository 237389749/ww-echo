"""官方配置表(BinData)与本地化文本(Textmaps)的读取层。

数据是**离线导出的游戏配置表**（客户端 dump 或服务端 bindata），不是运行时读游戏文件/内存 ——
运行时读的仍然是屏幕。用途是用官方表生成 `assets/gamedata/*.json`，见 `tools/gen_echo_data.py`。

用法::

    bd = BinData(r"...\\WutheringWaves_Data-3.7\\BinData")   # 目录或 zip 均可
    rows = bd.table("PhantomItem")                           # 表名大小写不敏感, 后缀可省
    tm = load_textmaps(r"...\\Textmaps\\zh-Hans")
    tm.get("PhantomFetter_36_Name")                          # -> "衔梦照世之心"

只依赖标准库；不 import ok-script，便于 tools/tests 独立运行。
"""
from __future__ import annotations

import base64
import glob
import json
import os
import re
import zipfile

__all__ = ["BinData", "load_textmaps", "parse_plan_bin", "read_version"]


class BinData:
    """一次导出的配置表集合：可按表名取行。

    同一份逻辑表在不同来源里有两种序列化（都实测过）：
    客户端 dump 用 `[{Key: ..., Value: ...}]`，服务端 bindata 用 `{"k": v}`
    —— 用 `BinData.pairs()` 统一。
    """

    def __init__(self, path: str):
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        self._index: dict[str, str] = {}
        if os.path.isdir(path):
            for p in glob.glob(os.path.join(path, "**", "*.json"), recursive=True):
                self._index.setdefault(os.path.basename(p).lower(), p)
        else:
            self._zip = zipfile.ZipFile(path)
            for n in self._zip.namelist():
                self._index.setdefault(os.path.basename(n).lower(), n)

    def has(self, name: str) -> bool:
        return self._key(name) is not None

    def _key(self, name: str) -> str | None:
        base = os.path.basename(name).lower()
        if not base.endswith(".json"):
            base += ".json"
        return self._index.get(base)

    def table(self, name: str) -> list[dict]:
        """取一张表的行（`{Id: {...}}` 形式会自动展平成行的列表）。"""
        key = self._key(name)
        if key is None:
            sample = sorted(k for k in self._index if name.split(".")[0].lower() in k)[:8]
            raise FileNotFoundError(f"表不存在: {name} (来源 {self.path}); 相近: {sample}")
        if self._zip is not None:
            with self._zip.open(key) as f:
                raw = json.loads(f.read().decode("utf-8"))
        else:
            with open(key, encoding="utf-8") as f:
                raw = json.load(f)
        return list(raw.values()) if isinstance(raw, dict) else raw

    @staticmethod
    def pairs(value) -> list[tuple]:
        """`[{Key,Value}]` / `{k: v}` / None → `[(k, v)]`。"""
        if not value:
            return []
        if isinstance(value, dict):
            return [(k, v) for k, v in value.items()]
        return [(x.get("Key"), x.get("Value")) for x in value if isinstance(x, dict)]


def load_textmaps(path: str) -> dict[str, str]:
    """本地化文本目录 → {文本键: 中文}。

    两种形态都收：`[{Id, Content}]`（Arikatsu 3.6/3.7 的嵌套目录）与
    纯字符串键的 dict（如 `{"PhantomFetter_36_Name": "…"}`）。
    **全数字键的 dict 会跳过** —— 那些是"按行 Id 索引"的表（如 property/ 下的 Id 空间与
    PropId 无关），混进来会用错 id 空间覆盖真文本键。
    """
    out: dict[str, str] = {}
    for p in glob.glob(os.path.join(path, "**", "*.json"), recursive=True):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            for r in data:
                if isinstance(r, dict) and "Id" in r and "Content" in r:
                    out.setdefault(str(r["Id"]), r["Content"])
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and not str(k).isdigit():
                    out.setdefault(str(k), v)
    return out


# PhantomManagePlanV2 的 BinData 是 FlatBuffers，字段序见客户端
# `Core/Define/Config/PhantomManagePlanV2.js`: {Id, FetterId, Cost, LockGroup, DiscardGroup}。
# 未写入的字段在 vtable 里 offset=0（FlatBuffers 省略默认值）→ 缺失即空。
_PLAN_FIELDS = ("Id", "FetterId", "Cost", "LockGroup", "DiscardGroup")
_MAX_VEC = 64


def parse_plan_bin(blob: bytes) -> dict:
    """解 `PhantomManagePlanV2.BinData`（FlatBuffers）→ {Id, FetterId, Cost, LockGroup, DiscardGroup}。

    已验证：客户端 3.7 表 109 行全部解出，且与服务端 3.7.1.0 的显式字段表
    **100/100 行完全一致**（锁定/丢弃组与 Id 都相同）。
    """
    if isinstance(blob, str):
        blob = base64.b64decode(blob)
    if len(blob) < 8:
        raise ValueError(f"BinData 过短: {len(blob)}")

    def u32(o: int) -> int:
        if o < 0 or o + 4 > len(blob):
            raise ValueError(f"偏移越界: {o} (len={len(blob)})")
        return int.from_bytes(blob[o:o + 4], "little")

    root = u32(0)
    if not 0 < root < len(blob):
        raise ValueError(f"root 越界: {root}")
    vt = root - int.from_bytes(blob[root:root + 4], "little", signed=True)
    vt_size = int.from_bytes(blob[vt:vt + 2], "little")      # voffset_t 是 u16
    if vt_size < 4 or vt_size > 64:
        raise ValueError(f"vtable 长度异常: {vt_size}")

    out: dict = {}
    for i in range((vt_size - 4) // 2):
        name = _PLAN_FIELDS[i] if i < len(_PLAN_FIELDS) else f"field{i}"
        off = int.from_bytes(blob[vt + 4 + 2 * i:vt + 6 + 2 * i], "little")
        if off == 0:
            out[name] = None
            continue
        pos = root + off
        if name in ("LockGroup", "DiscardGroup"):
            vec = pos + u32(pos)
            n = u32(vec)
            if n > _MAX_VEC or vec + 4 + 4 * n > len(blob):
                raise ValueError(f"{name} 向量长度异常: {n}")
            out[name] = [u32(vec + 4 + 4 * k) for k in range(n)]
        else:
            out[name] = u32(pos)
    return out


def read_version(textmaps_dir: str) -> str | None:
    """从数据仓库根的 README 里读游戏版本（如 `Game Version: 3.7.0`）；读不到返回 None。"""
    for up in ("..", os.path.join("..", "..")):
        p = os.path.join(textmaps_dir, up, "README.md")
        try:
            with open(p, encoding="utf-8") as f:
                m = re.search(r"Game Version:\s*([0-9][0-9.]*)", f.read())
        except OSError:
            continue
        if m:
            return m.group(1)
    return None
