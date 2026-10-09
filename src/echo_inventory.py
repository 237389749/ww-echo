"""
声骸**库存导入** —— 把既有的评估产物变成 `EchoItem` 列表, 供组合穷举(`src/echo_combos.py`)使用。

两个来源(与评估阶段的落盘约定一致):
1. `logs/eval_debug/<时间戳>/`(**推荐**, 数据最全): `image_report.md` 提供
   名字 / 等级 / COST / 主属性 2 行 / 副词条 5 条; 套装用同目录 `<tag>_full.png` 的详情面板图标识别
   (`src/echo_icon_match`, 高置信优先) → 与线上评估同一套消歧口径。
2. 评估 JSON(顶层 `results`: `evaluate_one` 的记录): 直接取 `name/set/cost/main_props/stats`。

**主属性 2 行**(实测 219 张面板, 见 `logs/eval_debug/20260911_110817/image_report.md`):
- 第 1 行 = 声骸的主属性(暴击/暴伤/属伤/共效/治疗/攻·生·防 的百分比…), COST/套装决定可选范围;
- 第 2 行 = **COST 固有属性**, 与套装无关, 与等级成比例: COST1 → 生命(满级 2280)、COST3 → 攻击(满级 100)、
  COST4 → 攻击(满级 150)(取值网格来自生成物 `main_props`, 与面板实测完全一致)。
两行**都算面板贡献**(它们就是面板上高亮的两条)。

`攻击/生命/防御` 这一个名字同时有"固定值"与"百分比"两个变体, 所以导入时要判定用哪个:
报告路径按数值里的 `%` 判(与 `EnhanceEchoTask._normalize_stat` 一致), JSON 路径按**官方取值网格**
(`src/echo_main_prop`)判 —— 词条档位表里固定值与百分比区间不重叠(攻击 30~60 vs 6.4~11.6), 判定唯一。

**5★**: 评估产物里没有稀有度字段 —— 导入即视为 5★(契约"只用 5★"由用户口径保证: 只练 5★)。
"""
from __future__ import annotations

import glob
import json
import os
import re

import cv2
import numpy as np

from src.echo_combos import EchoItem
from src.echo_icon_match import match_icon
from src.echo_main_prop import candidates as main_prop_candidates
from src.echo_set_templates import get_set_by_echo, get_sets_by_echo, load_gamedata
from src.echo_stats import is_stat_match
from src.task.EnhanceEchoTask import EnhanceEchoTask, parse_number

_ROOM = "logs/eval_debug"


def latest_debug_dir() -> str:
    """`logs/eval_debug/` 下最新的素材目录(无则返回空串)。"""
    dirs = sorted(glob.glob(os.path.join(_ROOM, "*")), key=os.path.getmtime)
    return dirs[-1] if dirs else ""


def imread(path: str):
    """读图 —— `cv2.imread` 读不了中文路径(项目已知坑), 回退 `imdecode`。"""
    img = cv2.imread(path)
    if img is None:
        try:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except (OSError, ValueError):
            img = None
    return img


def parse_report(path: str) -> dict:
    """`image_report.md` → {tag: [详情文字行...]}(与线下重放工具同一份解析)。"""
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^### (\S+)\n(.*?)(?=^### |\Z)", text, re.S | re.M):
        body = re.search(r"\*\*【详情文字】\*\*\n((?:- .*\n)+)", m.group(2))
        if body:
            out[m.group(1)] = [ln[2:].strip() for ln in body.group(1).strip().split("\n")]
    return out


def split_rows(lines: list) -> tuple:
    """复刻 `read_detail`: 名字=首个中文行; `+25`/`Z | C` 等面板非属性行丢掉;
    `COST n` 行取角标; 属性行取 `名 | 值`(按**最后一个** `|` 切分, 前缀留给清洗)。→ (name, props, cost)"""
    name, props, cost = "", [], None
    for ln in lines:
        if not ln or ln.startswith("+") or ln.startswith("Z"):
            continue
        if ln.startswith("COST"):
            m = re.search(r"COST\s*([134])", ln)
            if m and cost is None:
                cost = int(m.group(1))
            continue
        if ln.startswith("声骸技能"):
            break
        if "|" in ln:
            head, _, tail = ln.rpartition("|")
            props.append((head.strip(), tail.strip()))
        elif not name and re.search(r"[\u4e00-\u9fff]", ln):
            name = ln
    return name, props, cost


def parse_level(lines: list) -> int | None:
    """详情文字里的 `+25` → 25(等级决定主属性/固有属性的取值网格)。"""
    for ln in lines:
        m = re.match(r"^\+(\d+)$", ln.strip())
        if m:
            return int(m.group(1))
    return None


def _levels(level: int | None, tier: int | None = None) -> list[int]:
    """主属性数值的等级窗口: 知道等级就取那一点(网格唯一); 否则用词条数推出的窗口。"""
    if level is not None:
        return [min(25, max(0, level))]
    n = max(0, int(tier or 0))
    return list(range(min(25, 5 * n), 26))


def _grid_says_pct(name: str, value: float, levels) -> bool | None:
    """按官方网格判 `名 值` 是百分比变体还是固定变体; 两边都不中/都中 → None(不表态)。"""
    cands = main_prop_candidates(name, levels)
    if not cands:
        return None
    pct = any(p and abs(v - value) <= tol for v, tol, p, _std in cands)
    flat = any(not p and abs(v - value) <= tol for v, tol, p, _std in cands)
    if pct == flat:
        return None
    return pct


# COST **固有属性**(面板第 2 行)的官方固定值变体: COST1 生命(std 456) / COST3 攻击(std 20) /
# COST4 攻击(std 30)。显示值 = std × PhantomGrowth倍率/10000, 所以这里只存 std, 值由官方网格按等级算。
# 依据: 两批真实面板(219 张 20260911 + 135 张 20261008)满级分别是 生命 2280 / 攻击 100 / 攻击 150。
_FIXED_MAIN_STD: dict[int, tuple[str, float]] = {1: ("生命", 456.0), 3: ("攻击", 20.0), 4: ("攻击", 30.0)}


def infer_cost(main_props, level: int | None = None, tier: int | None = None) -> int | None:
    """COST 角标没读到(OCR 抖动)时, 用**第 2 行 COST 固有属性**反推 COST; 不唯一 → None(不猜)。

    `main_props` = 已归一化的 `[(键, 值), …]`(见 `normalize_main_prop`)。
    为什么能反推: 每个 COST 档的固有属性不同(1C 生命 / 3C·4C 攻击), 值按官方曲线随等级走 ——
    名字 + 值 + 官方变体 std 三者一比即可定位唯一 COST(3C/4C 都是攻击, 靠 std 20/30 区分)。
    """
    props = list(main_props)
    if len(props) < 2:
        return None
    key, value = props[1]
    levels = _levels(level, tier)
    hits: set[int] = set()
    for cost, (vname, std) in _FIXED_MAIN_STD.items():
        if vname != key:
            continue
        for cand, tol, pct, cstd in main_prop_candidates(vname, levels):
            if pct or abs(cstd - std) > 1e-6:
                continue
            if abs(cand - float(value)) <= tol:
                hits.add(cost)
                break
    return hits.pop() if len(hits) == 1 else None


def resolve_cost(cost, main_props, level=None, tier=None) -> tuple[int, bool]:
    """→ `(COST, 是否靠第 2 行反推)`。角标读到就用角标(权威); 没读到才反推(本批数据实测缺 27/135)。"""
    if cost in (1, 3, 4):
        return int(cost), False
    guess = infer_cost(main_props, level, tier)
    return (guess, True) if guess else (0, False)


def normalize_main_prop(raw_name: str, value, level: int | None = None, tier: int | None = None) -> str:
    """主属性行(名 + 值) → 面板键: 认名(官方 `main_prop_names` 最长子串) + 判"固定/百分比"。

    认不出名字返回原文(会被 `echo_panel` 记进 `unknown`, 不静默吞掉)。

    `level`(报告里的 `+25`)最准; 只有词条数时传 `tier`, 用 `[5·tier, 25]` 窗口收窄网格 ——
    **这一步是必需的**: 放开全等级比较时 `攻击 30.0` 会同时命中"百分比(满级 30.0)"与"固定值(+0 30)",
    判定不了就会把满级 4C/3C 的 `攻击% 30.0` 误当固定值(实测踩过)。
    """
    gd = load_gamedata() or {}
    names = gd.get("main_prop_names") or {}
    raw = str(raw_name)
    key = max((k for k in names if k in raw), key=len, default=None)
    if key is None:
        return raw
    if key not in ("攻击", "生命", "防御"):
        return key
    pct = "%" in str(value) or "％" in str(value)
    if not pct:
        try:
            num = float(str(value).replace("%", "").replace("％", ""))
        except ValueError:
            num = None
        if num is not None:
            verdict = _grid_says_pct(key, num, _levels(level, tier))
            if verdict is not None:
                pct = verdict
    return key + "百分比" if pct else key


def substat_key(name: str, value: float) -> str:
    """评估 JSON 里的副词条(名 + 数值) → 规范词条名。

    JSON 里的数值已丢掉 `%`, 所以 `攻击/生命/防御` 用**词条档位表**判固定还是百分比
    (区间不重叠: 攻击 30~60 vs 6.4~11.6; 生命 320~580 vs 6.4~11.6; 防御 40~70 vs 8.1~14.7)。
    """
    name = str(name)
    if name in ("攻击", "生命", "防御"):
        if is_stat_match(name + "百分比", value) and not is_stat_match(name, value):
            return name + "百分比"
    return name


def resolve_set(echo_name: str, frame=None) -> tuple:
    """声骸 → (套装, 来源, 图标分): 图标识别优先(高置信直接用), 否则名字候选, 否则"通用"。"""
    cands = get_sets_by_echo(echo_name)
    score = None
    if frame is not None:
        icon_set, score, _margin = match_icon(frame)
        if icon_set:
            return icon_set, "icon", score
    return (get_set_by_echo(echo_name, prefer="通用") or "通用"), ("name" if cands else "default"), score


def _subs_from_props(props: list, main_n: int = 2) -> tuple:
    """属性行 → 副词条(排除前 2 行主属性; 走与线上同一套档位过滤)。"""
    out = []
    for raw_n, v_str in props[main_n:]:
        norm = EnhanceEchoTask._normalize_stat(raw_n, v_str)
        val = parse_number(v_str)
        if norm and is_stat_match(norm, val):
            out.append((norm, val))
    return tuple(out[:5])


def item_from_report(tag: str, lines: list, frame=None) -> EchoItem | None:
    """一组详情文字(+ 可选整帧) → `EchoItem`; 0 级(无词条)返回 None。"""
    name, props, cost = split_rows(lines)
    if not name or not props:
        return None
    subs = _subs_from_props(props)
    if not subs:
        return None                       # 0 级: 无词条, 不入库存(与评估报告一致)
    level = parse_level(lines)
    main = tuple((normalize_main_prop(n, v, level, len(subs)), parse_number(v)) for n, v in props[:2])
    set_name, src, score = resolve_set(name, frame)
    cost, inferred = resolve_cost(cost, main, level, len(subs))
    tail = f"{tag}|{src}" + (f"|s1={score:.3f}" if score is not None else "") + \
        ("|cost=反推" if inferred else "")
    return EchoItem(name=name, cost=cost, set_name=set_name,
                    stats=tuple(main) + subs, main=main, level=level, source=tail)


def item_from_record(rec: dict) -> EchoItem | None:
    """评估 JSON 的一条记录(`evaluate_one` 的输出) → `EchoItem`; 无词条返回 None。"""
    name = str(rec.get("name") or "")
    stats = rec.get("stats") or []
    subs = tuple((substat_key(s.get("name"), float(s.get("value") or 0)), float(s.get("value") or 0))
                 for s in stats if s.get("name") is not None)
    if not name or not subs:
        return None
    tier = len(subs)
    main = tuple((normalize_main_prop(m.get("name"), m.get("value"), None, tier),
                  float(m.get("value") or 0)) for m in (rec.get("main_props") or []))
    cost, inferred = resolve_cost(rec.get("cost"), main, None, tier)
    return EchoItem(name=name, cost=cost,
                    set_name=str(rec.get("set") or "通用"), stats=main + subs, main=main,
                    level=None, source=f"json#{rec.get('index', '')}" + ("|cost=反推" if inferred else ""))


def load_inventory(path: str = "", use_icons: bool = True) -> list[EchoItem]:
    """导入库存: 目录(评估素材) / `image_report.md` / 评估 JSON → `[EchoItem]`(已去重)。

    素材目录里没有整帧(`*_full.png`)时 `use_icons` 自动失效 → 只能按名字候选定套装
    (多义名字会退到"通用" —— 这种只会在离线裁剪过素材时出现)。
    """
    path = path or latest_debug_dir()
    if not path:
        raise FileNotFoundError("找不到评估素材: logs/eval_debug/ 为空(先跑一次评估模式)")
    if os.path.isdir(path):
        report = os.path.join(path, "image_report.md")
        frames = {os.path.basename(p).replace("_full.png", ""): p
                  for p in glob.glob(os.path.join(path, "*_full.png"))} if use_icons else {}
        if os.path.exists(report):
            return _load_report(report, frames)
        jsons = sorted(glob.glob(os.path.join(path, "*.json")))
        if jsons:
            return _load_json(jsons[-1])
        raise FileNotFoundError(f"目录里既没有 image_report.md 也没有评估 JSON: {path}")
    if path.lower().endswith(".json"):
        return _load_json(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return _load_report(path, {})


def drop_exact_duplicates(items: list[EchoItem]) -> list[EchoItem]:
    """丢掉**完全同一个实例**的重复记录(名字/套装/COST/词条全同)。

    评估侧本来有 `dedup_key` 去重, 但 OCR 抖动会溜过去(实测: 同一只 `双极·渊陨重锋` 因名字里的
    间隔号被读成 `・` 而记了两次 → 组合穷举给出成对同分组合)。契约里"同名多只 = 同一只的多个词条版本",
    所以词条也全同的两条对排名没有任何贡献, 直接折成一条。
    """
    seen, out = set(), []
    for it in items:
        key = (it.name, it.set_name, it.cost, tuple(sorted(it.stats)))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _load_report(report_path: str, frames: dict) -> list[EchoItem]:
    report = parse_report(report_path)
    seen, items = set(), []
    for tag in sorted(report):
        lines = report[tag]
        name, props, _cost = split_rows(lines)
        if not name or not props:
            continue
        key = EnhanceEchoTask.dedup_key(name, props)      # 跨屏重叠的重复记录(与评估同一份去重)
        if key in seen:
            continue
        seen.add(key)
        frame = imread(frames[tag]) if tag in frames else None
        item = item_from_report(tag, lines, frame)
        if item is not None:
            items.append(item)
    return drop_exact_duplicates(items)


def _load_json(json_path: str) -> list[EchoItem]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("results") if isinstance(data, dict) else data
    items = [item_from_record(r) for r in (records or [])]
    return drop_exact_duplicates([i for i in items if i is not None])


def summarize(items: list[EchoItem]) -> dict:
    """库存概览(UI/CLI 展示用): 只数 / 名字数 / 按套装·COST 分布 / 有套装的只数。"""
    by_set: dict[str, int] = {}
    by_cost: dict[int, int] = {}
    for i in items:
        by_set[i.set_name] = by_set.get(i.set_name, 0) + 1
        by_cost[i.cost] = by_cost.get(i.cost, 0) + 1
    return {"total": len(items), "names": len({i.name for i in items}),
            "by_set": dict(sorted(by_set.items(), key=lambda kv: -kv[1])),
            "by_cost": dict(sorted(by_cost.items()))}
