"""
主属性**数值**校验(官方表 `main_props`, 见 tools/gen_echo_data.py)。

用途: 面板 OCR 出的主属性行(名 + 值)除了看"类型是否被官方管理方案认可"(check_main_prop),
还可以看"**数值**是否落在官方可能的网格上" —— 能挡住 OCR 误读(如把 `150` 读成 `1500`)。

数值模型(全部来自官方表): `值 = StandardProperty (/100 若百分比) × PhantomGrowth倍率/10000`,
例: 5★ COST4 暴击 `std=440` → +0 `4.4%` → +25(倍率 50000) `22.0%`。

两个实测教训(2026-10 用 219 张真实面板验收后定下的):
1. **等级只能取下界**: 词条数 n 只说明"至少 +5n"(第 n 条词条在 +5n 开), 精确等级未知 ——
   本数据集里就有 `+22` 却已有 5 条词条的声骸; 所以窗口 = `[5n, 25]`, 上界恒为满级。
2. **容差按"能匹配上的那个变体"取**: 同一属性名有固定值/百分比多个变体(`攻击` 既有 `150` 也有 `33.0%`),
   不能拿第一个变体的容差去比全部(否则 `攻击 135` 这种固定值会被 0.11 的百分比容差误判)。
"""
from src.echo_set_templates import load_gamedata

TOL_PCT = 0.11      # 百分比属性: 面板显示 1 位小数
TOL_FLAT = 1.0      # 固定值: 面板显示整数(可能四舍五入/截断)


def _table() -> dict:
    return (load_gamedata() or {}).get("main_props") or {}


def levels_for_tier(tier) -> list[int]:
    """词条数 → 可能等级(只给**下界**: 第 n 条词条在 +5n 出现, 精确等级未知, 上界恒为满级)。"""
    n = max(0, int(tier or 0))
    return list(range(min(25, 5 * n), 26))


def _candidates(name: str, levels) -> list[tuple[float, float, bool]]:
    """→ [(期望值, 容差, 是否百分比)]: 某属性名在给定等级上所有变体 × 等级的候选。"""
    t = _table()
    growth = t.get("growth") or {}
    out: list[tuple[float, float, bool]] = []
    for v in ((t.get("props") or {}).get(name) or []):
        curve = growth.get(str(v.get("growth"))) or []
        pct = bool(v.get("pct"))
        for lv in levels:
            if 0 <= lv < len(curve) and curve[lv]:
                raw = v["std"] / (100 if pct else 1) * curve[lv] / 10000
                out.append((round(raw, 1) if pct else float(round(raw)),
                            TOL_PCT if pct else TOL_FLAT, pct))
    return out


def value_grid(name: str, levels=None) -> list[float]:
    """某主属性在给定等级上**可能出现**的全部数值(多变异并集, 升序去重) —— 主要给测试/排查用。"""
    t = _table()
    if levels is None:
        curve = next(iter((t.get("growth") or {}).values()), [])
        levels = range(len(curve))
    return sorted({v for v, _, _ in _candidates(name, levels)})


def candidates(name: str, levels=None) -> list[tuple[float, float, bool]]:
    """某主属性名在给定等级上的全部候选 `(值, 容差, 是否百分比)`。

    公开给**导入器**判"`攻击/生命/防御` 这一行到底是固定值还是百分比"
    (同一个名字有多个变体, 面板 OCR 的文本里能带 `%`, 评估 JSON 里已经丢掉了)。
    """
    return _candidates(name, _levels_or_all(levels))


def _levels_or_all(levels) -> list[int]:
    if levels is not None:
        return list(levels)
    t = _table()
    curve = next(iter((t.get("growth") or {}).values()), [])
    return list(range(len(curve)))


def check_main_values(main_props, tier=None) -> list[dict]:
    """`[(属性名, 值)]` → `[{name, value, ok, expect, tol}]`。

    `ok=False` = 数值不在官方网格上(疑似 OCR 误读); `ok=None` = 名字不认识或表里没这个属性(不表态)。
    """
    if not main_props:
        return []
    levels = levels_for_tier(tier) if tier is not None else list(range(26))
    out: list[dict] = []
    for name, value in list(main_props)[:2]:
        try:
            val = float(value)
        except (TypeError, ValueError):
            continue
        cands = _candidates(str(name), levels)
        if not cands:
            out.append({"name": str(name), "value": val, "ok": None, "expect": None, "tol": None})
            continue
        # 按"是否落在某个变体的容差内"判定; 报告里给出最接近的那个候选
        hit = next(((exp, tol, pct) for exp, tol, pct in
                    sorted(cands, key=lambda c: abs(c[0] - val)) if abs(exp - val) <= tol), None)
        best = min(cands, key=lambda c: abs(c[0] - val))
        out.append({"name": str(name), "value": val, "ok": hit is not None,
                    "expect": best[0], "tol": best[1]})
    return out
