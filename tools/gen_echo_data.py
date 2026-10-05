#!/usr/bin/env python3
"""用官方配置表生成 `assets/gamedata/echo_data.json`（声骸↔套装 / 主属性方案 / 属性名）。

数据源是**离线导出的游戏配置表**（不是运行时读游戏），表结构见 `src/wuwa_data.py`：
`PhantomItem` / `PhantomFetterGroup` / `PhantomFetter` / `PhantomRarity` /
`PhantomManagePlanV2` / `PropertyIndex`，中文名来自 `Textmaps/zh-Hans`。

用法::

    python tools/gen_echo_data.py \
        --bindata  ..\\search\\wwdata37\\BinData \
        --textmaps ..\\search\\wwdata37\\Textmaps\\zh-Hans

产物（只读，运行时消费；**策略层**如权重/`_core_first` 仍手写在 echo_set_templates.json）::

    assets/gamedata/echo_data.json

约定：
- 有任何**文本键解析不出**就退出码 2 且不写文件（宁可失败也不要静默丢数据）。
- 声骸名按**游戏内显示名**收录（含 `异相·` 前缀），皮肤条目的 `base` 记本体名 ——
  配置里 `异相·X` 有自己的套装，与本体 X 可能不同，所以不能剥前缀复用本体套装。
- `--dry-run` 只打印 diff 不写文件。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.wuwa_data import BinData, load_textmaps, parse_plan_bin, read_version  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "assets", "gamedata", "echo_data.json")
ICON_DIR = os.path.join(REPO, "assets", "echo_icons")
TEMPLATES = os.path.join(REPO, "assets", "echo_set_templates.json")
COST_KEYS = ("4c", "3c", "1c")
# 皮肤名的前缀（游戏内 `异相·X` 是独立声骸；`梦魇·` 是真实前缀, 保留）
SKIN_PREFIXES = ("异相·", "异相")
UNRESOLVED_LIMIT = 30


def strip_skin(name: str) -> str | None:
    for p in SKIN_PREFIXES:
        if name.startswith(p):
            return name[len(p):].lstrip("· ") or None
    return None


class Builder:
    def __init__(self, bd: BinData, tm: dict[str, str]):
        self.bd = bd
        self.tm = tm
        self.unresolved: list[str] = []

    def zh(self, key, what: str) -> str | None:
        if key and key in self.tm:
            return self.tm[key]
        self.unresolved.append(f"{what}={key}")
        return None

    def build(self) -> dict:
        sets = self._sets()
        self._effects(sets)
        echoes = self._echoes(sets)
        self._plan(sets)
        props = self._props()
        return {
            "sets": dict(sorted(sets.items())),
            "echoes": echoes,
            "props": props,
            "main_prop_names": self._main_prop_names(props),
        }

    # ---- 套装 ----
    def _sets(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for g in self.bd.table("PhantomFetterGroup"):
            name = self.zh(g.get("FetterGroupName"), "FetterGroupName")
            if not name:
                continue
            icon = os.path.basename(str(g.get("FetterElementPath") or "")).split(".")[0]
            out[name] = {
                "id": g["Id"],
                "sort_id": g.get("SortId"),
                "icon_asset": icon,                      # 客户端贴图名(将来从 pak 抽图标用)
                "icon_file": f"{name}.png",              # assets/echo_icons/ 下的模板文件名
                "fetter_ids": sorted(v for _, v in self.bd.pairs(g.get("FetterMap"))),
                "echoes": {k: [] for k in COST_KEYS},
                "plan": {},
            }
        return out

    def _effects(self, sets: dict[str, dict]) -> None:
        by_fid = {f["Id"]: f for f in self.bd.table("PhantomFetter")}
        for v in sets.values():
            v["effects"] = {}
            for fid in v["fetter_ids"]:
                row = by_fid.get(fid)
                if row is None:
                    continue
                v["effects"][str(fid)] = {
                    "simple": self.zh(row.get("SimplyEffectDesc"), "SimplyEffectDesc"),
                    "text": self.zh(row.get("EffectDescription"), "EffectDescription"),
                    "params": row.get("EffectDescriptionParam") or [],
                }

    # ---- 声骸 ----
    def _echoes(self, sets: dict[str, dict]) -> dict[str, dict]:
        cost_of_rare = {r["Rare"]: r["Cost"] for r in self.bd.table("PhantomRarity")}
        name_of_id = {v["id"]: n for n, v in sets.items()}
        echoes: dict[str, dict] = {}
        no_set: list[str] = []
        for it in self.bd.table("PhantomItem"):
            if it.get("PhantomType") != 1:               # 1=畸形种(可获得); 2..5=幻象/召唤物
                continue
            raw = it.get("MonsterName")
            name = self.tm.get(raw, raw)
            if not name or "/" in str(name) or str(name).startswith("MonsterInfo_"):
                self.unresolved.append(f"PhantomItem.MonsterName={raw}")
                continue
            cost = cost_of_rare.get(it.get("Rarity"))
            if cost is None:
                self.unresolved.append(f"PhantomRarity.Rare={it.get('Rarity')}")
                continue
            groups = [name_of_id[g] for g in (it.get("FetterGroup") or []) if g in name_of_id]
            if not groups:
                no_set.append(name)
                continue
            entry = echoes.setdefault(name, {"cost": cost, "sets": [], "base": strip_skin(name)})
            if entry["cost"] != cost:
                self.unresolved.append(f"{name} 出现多个 COST: {entry['cost']} vs {cost}")
            for gname in groups:
                if gname not in entry["sets"]:
                    entry["sets"].append(gname)
                bucket = sets[gname]["echoes"][f"{cost}c"]
                if name not in bucket:
                    bucket.append(name)
        for v in sets.values():
            for k in COST_KEYS:
                v["echoes"][k].sort()
        for e in echoes.values():
            e["sets"].sort()
        self.no_set = sorted(set(no_set))
        return dict(sorted(echoes.items()))

    # ---- 官方主属性方案 ----
    def _plan(self, sets: dict[str, dict]) -> None:
        rows = self.bd.table("PhantomManagePlanV2")
        by_id = {v["id"]: v for v in sets.values()}
        for r in rows:
            if "BinData" in r and not r.get("LockGroup"):
                d = parse_plan_bin(r["BinData"])
                if d.get("Id") != r.get("Id") or d.get("FetterId") != r.get("FetterId"):
                    raise ValueError(f"FlatBuffer 解码自检失败: 行 {r} → {d}")
            else:
                d = {"Cost": r.get("Cost"), "LockGroup": r.get("LockGroup"),
                     "DiscardGroup": r.get("DiscardGroup")}
            v = by_id.get(r["FetterId"])
            if v is None:
                continue
            cost = d.get("Cost")
            if cost not in (1, 3, 4):
                self.unresolved.append(f"PhantomManagePlanV2 Cost={cost} (FetterId={r['FetterId']})")
                continue
            v["plan"][str(cost)] = {"lock": sorted(d.get("LockGroup") or []),
                                    "discard": sorted(d.get("DiscardGroup") or [])}

    # ---- 属性名 ----
    def _props(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in self.bd.table("PropertyIndex"):
            name = self.tm.get(p.get("Name"))
            if name:
                out[str(p["Id"])] = {"name": name, "pct": bool(p.get("IsPercent"))}
        return dict(sorted(out.items(), key=lambda kv: int(kv[0])))

    def _main_prop_names(self, props: dict) -> dict[str, int]:
        """主属性可出现的「属性名 → PropId」(面板主属性行 → 官方管理方案用的 PropId)。

        只收**主属性池**(`PhantomMainProperty.PropGroup` → `PhantomMainPropItem`)里出现过的 PropId：
        1C/3C/4C 池用的是 10002/10007/10010(生命/攻击/防御) 与 8/9/11/22~27/35，
        这样不会与 PropertyIndex 里同名的 2/7/10 混淆 —— 官方管理方案的 lock/discard 组正是这套 PropId。
        """
        ids = {pid for row in self.bd.table("PhantomMainProperty")
               for pid in (row.get("PropGroup") or [])}
        items = {r["Id"]: r for r in self.bd.table("PhantomMainPropItem")}
        out: dict[str, int] = {}
        for pid in sorted(ids):
            it = items.get(pid)
            if not it:
                continue
            name = (props.get(str(it["PropId"])) or {}).get("name")
            if name and name not in out:
                out[name] = it["PropId"]
        return out


def diff_vs_templates(data: dict) -> list[str]:
    """生成层 vs 现行 `echo_set_templates.json` 的清单差异（L1 要靠它核对改动面）。"""
    if not os.path.exists(TEMPLATES):
        return ["(无 echo_set_templates.json, 跳过 diff)"]
    with open(TEMPLATES, encoding="utf-8") as f:
        tpl = json.load(f)["sets"]
    cfg, ww = set(data["sets"]), set(tpl)
    cfg_pairs = {(s, n) for s, v in data["sets"].items() for k in COST_KEYS for n in v["echoes"][k]}
    ww_pairs = {(s, n) for s, v in tpl.items()
                for k in COST_KEYS for n in (v.get("_echoes") or {}).get(k, [])}
    missing = sorted(cfg_pairs - ww_pairs)
    extra = sorted(ww_pairs - cfg_pairs)
    out = [
        f"套装: 配置 {len(cfg)} / 模板 {len(ww)}  新增={sorted(cfg - ww)}  模板多余={sorted(ww - cfg)}",
        f"套装-声骸对: 配置 {len(cfg_pairs)} / 模板 {len(ww_pairs)}",
        f"  模板缺 {len(missing)} 对: {missing[:12]}{' …' if len(missing) > 12 else ''}",
        f"  模板多 {len(extra)} 对: {extra[:12]}{' …' if len(extra) > 12 else ''}",
    ]
    skin = {n: e for n, e in data["echoes"].items() if e.get("base")}
    conflict = sorted(n for n, e in skin.items()
                      if e["base"] in data["echoes"]
                      and data["echoes"][e["base"]]["sets"] != e["sets"])
    out.append(f"皮肤条目 {len(skin)} 个, 其中 {len(conflict)} 个与本体套装不同"
               f"（剥前缀即错的那批）: {conflict[:8]}")
    return out


def sync_templates(data: dict, path: str) -> list[str]:
    """把生成物同步进 `echo_set_templates.json`（**策略层**）。

    只补/更新 `_echoes` 与 `_icon`；缺失的套装用 `DEFAULT_WEIGHTS` 播种
    （与旧 `tools/parse_wutherin_echoes.py` 同口径）；**绝不改已有权重与 `_core_first`**。
    """
    from src.echo_stats import DEFAULT_WEIGHTS
    with open(path, encoding="utf-8") as f:
        tpl = json.load(f)
    sets = tpl.setdefault("sets", {})
    added, updated, icon_filled = [], [], []
    for name, v in data["sets"].items():
        echoes = v["echoes"]
        if name not in sets:
            sets[name] = {**DEFAULT_WEIGHTS, "_echoes": echoes, "_icon": v["icon_file"]}
            added.append(name)
            continue
        entry = sets[name]
        if entry.get("_echoes") != echoes:
            entry["_echoes"] = echoes
            updated.append(name)
        if not entry.get("_icon"):
            entry["_icon"] = v["icon_file"]
            icon_filled.append(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    return [f"新增套装 {len(added)}: {added}",
            f"更新 _echoes {len(updated)} 套: {updated}",
            f"补 _icon {len(icon_filled)}: {icon_filled}"]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 assets/gamedata/echo_data.json")
    ap.add_argument("--bindata", required=True, help="BinData 目录或 zip")
    ap.add_argument("--textmaps", required=True, help="Textmaps/<语言> 目录, 如 .../Textmaps/zh-Hans")
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--dry-run", action="store_true", help="只打印, 不写文件")
    ap.add_argument("--sync-templates", action="store_true",
                    help="同时把 _echoes/_icon 同步进 assets/echo_set_templates.json(不动权重)")
    a = ap.parse_args()

    tm = load_textmaps(a.textmaps)
    b = Builder(BinData(a.bindata), tm)
    data = b.build()

    if b.unresolved:
        print(f"[FATAL] {len(b.unresolved)} 个文本键/取值解析不出 —— 不写文件：", file=sys.stderr)
        for u in b.unresolved[:UNRESOLVED_LIMIT]:
            print("   ", u, file=sys.stderr)
        if len(b.unresolved) > UNRESOLVED_LIMIT:
            print(f"    … 另有 {len(b.unresolved) - UNRESOLVED_LIMIT} 条", file=sys.stderr)
        return 2

    data["_source"] = {
        "version": read_version(a.textmaps),
        "bindata": os.path.abspath(a.bindata),
        "textmaps": os.path.abspath(a.textmaps),
        "sets": len(data["sets"]),
        "echoes": len(data["echoes"]),
    }
    data = {"_source": data.pop("_source"), **data}

    missing_icons = [n for n, v in data["sets"].items()
                     if not os.path.exists(os.path.join(ICON_DIR, v["icon_file"]))]
    print(f"生成: {len(data['sets'])} 套 / {len(data['echoes'])} 声骸 / "
          f"{len(b.no_set)} 只无套装被跳过 / 版本 {data['_source']['version']}")
    if b.no_set:
        print(f"  无套装(未收进索引): {b.no_set[:10]}")
    if missing_icons:
        print(f"  缺图标模板 {len(missing_icons)} 个(名字兜底仍可用): {missing_icons}")
    print("\n".join("  " + line for line in diff_vs_templates(data)))

    if a.dry_run:
        print("(--dry-run 未写文件)")
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"已写 {os.path.relpath(a.out, REPO)} "
          f"({os.path.getsize(a.out) / 1024:.0f} KB)")
    if a.sync_templates:
        for line in sync_templates(data, TEMPLATES):
            print("  [模板同步] " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
