"""
**角色预设**(profile) —— 把"算某个角色的声骸组合"所需的一整套输入存下来, 下次一键复用。

为什么需要: 每次手填的东西几乎一样(裸面板 / 一长串补正 / 指定专伤 / 天赋条件补正 / 两个门槛参数),
而它们**只跟角色走**、跟具体跑哪套无关。实测已经手填过 爱弥斯 / 绯雪 / 西格莉卡 / 仇远 四次。

存哪: `assets/char_profiles.json`(与 `echo_set_templates.json` 同级; 纯用户数据, 丢了不影响计算口径)。
结构(键名短、可读、向后兼容靠 `version`; 缺字段一律取默认, 不报错):

    {"version": 1, "chars": {
        "仇远": {
            "scaling": "攻击",
            "bare": {"攻击": 1336, "暴击": 57.3, "暴击伤害": 150, "共鸣效率": 100, "通用增伤": 3},
            "corrections": [{"key": "攻击百分比", "value": 37.5, "source": "配队"}, ...],
            "derived": [{"source": "共鸣效率", "threshold": 125, "per_point": 2, "cap": 50,
                         "key": "通用增伤", "label": "天赋: 共效>125 转增伤"}],
            "specialty": ["重击伤害加成"],
            "energy": {"min": 120, "slope": 0.3, "floor": 0.85},
            "crit": {"target": 100, "slope": 0.4, "floor": 0.8},
            "plan": {"mode": "3+2", "set_a": "息界同调之律", "set_b": "轻云出月", "cost4_owner": "B"}
        }}}

`plan` 段可选(有的角色常用配装固定, 顺手存下来); 不存就只复用"角色侧"的输入。
"""
from __future__ import annotations

import json
import os

from src.echo_panel import Correction, DerivedBonus, normalize_bonus_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "assets", "char_profiles.json")

# 门槛参数的默认值(与 `PlanRequest` 保持一致; 存预设时只写非默认值, 保持 json 精简)
ENERGY_DEFAULTS = {"min": 120.0, "slope": 0.30, "floor": 0.85}
CRIT_DEFAULTS = {"target": 100.0, "slope": 0.40, "floor": 0.80}


def load_all(path: str = "") -> dict[str, dict]:
    """读全部预设 → {角色名: 预设}; 文件不存在/坏掉 → 空(不抛, 预设丢了不该挡住计算)。"""
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    chars = data.get("chars") if isinstance(data, dict) else None
    return chars if isinstance(chars, dict) else {}


def save_all(chars: dict[str, dict], path: str = "") -> str:
    """写回全部预设(顺带保证目录存在), 返回落盘路径。"""
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "chars": chars}, f, ensure_ascii=False, indent=2)
    return path


def upsert(name: str, profile: dict, path: str = "") -> str:
    """新增/覆盖一个角色预设, 返回落盘路径。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("角色名不能为空")
    chars = load_all(path)
    chars[name] = profile
    return save_all(chars, path)


def delete(name: str, path: str = "") -> bool:
    """删除一个角色预设; 返回是否真的删掉了。"""
    chars = load_all(path)
    if name not in chars:
        return False
    chars.pop(name)
    save_all(chars, path)
    return True


def to_request_kwargs(profile: dict) -> dict:
    """预设 → `PlanRequest` 的字段(只给该预设真的有的字段, 其余交调用方/默认值)。

    这里把"存储用的短键"翻译成引擎/dataclass 的字段名, 是预设与引擎之间唯一的翻译层。
    """
    out: dict = {}
    if profile.get("specialty"):
        out["allowed_bonus"] = tuple(normalize_bonus_key(s) for s in profile["specialty"])
    if profile.get("max_level_only") is not None:
        out["max_level_only"] = bool(profile["max_level_only"])
    energy = profile.get("energy") or {}
    for src, dst in (("min", "energy_min"), ("slope", "energy_slope"), ("floor", "energy_floor")):
        if src in energy:
            out[dst] = float(energy[src])
    crit = profile.get("crit") or {}
    for src, dst in (("target", "crit_target"), ("slope", "crit_slope"), ("floor", "crit_floor")):
        if src in crit:
            out[dst] = float(crit[src])
    plan = profile.get("plan") or {}
    for key in ("mode", "set_a", "set_b", "cost4_owner"):
        if plan.get(key):
            out[key] = str(plan[key])
    if profile.get("scaling"):
        out["scaling"] = str(profile["scaling"])
    return out


def corrections_of(profile: dict) -> list[Correction]:
    """预设里的静态补正 → `Correction` 列表。"""
    return [Correction(str(c.get("key", "")), float(c.get("value", 0)),
                       str(c.get("source", "") or "未标来源"))
            for c in (profile.get("corrections") or []) if c.get("key")]


def derived_of(profile: dict) -> list[DerivedBonus]:
    """预设里的条件补正(天赋) → `DerivedBonus` 列表。"""
    out = []
    for d in (profile.get("derived") or []):
        if not d.get("source"):
            continue
        out.append(DerivedBonus(source=str(d["source"]), threshold=float(d.get("threshold", 0)),
                                per_point=float(d.get("per_point", 0)),
                                cap=float(d.get("cap", 0)) or float("inf"),
                                key=str(d.get("key") or "通用增伤"),
                                label=str(d.get("label", ""))))
    return out


def build_profile(scaling: str, bare: dict, corrections, derived, specialty=(),
                  energy: dict | None = None, crit: dict | None = None,
                  plan: dict | None = None, max_level_only: bool = True) -> dict:
    """把当前输入装配打成一个预设(UI「保存为…」/ CLI `--save-profile` 用)。

    门槛参数只写**非默认值** —— 让 json 一眼能看出"这个角色和常规有什么不同"。
    """
    prof: dict = {"scaling": str(scaling), "bare": {str(k): float(v) for k, v in (bare or {}).items()}}
    prof["corrections"] = [{"key": c.key, "value": float(c.value), "source": c.source}
                           for c in corrections]
    prof["derived"] = [{"source": d.source, "threshold": d.threshold, "per_point": d.per_point,
                        "cap": d.cap, "key": d.key, "label": d.label} for d in derived]
    if specialty:
        prof["specialty"] = [normalize_bonus_key(s) for s in specialty]
    e = {k: float(v) for k, v in (energy or {}).items() if float(v) != ENERGY_DEFAULTS.get(k)}
    c = {k: float(v) for k, v in (crit or {}).items() if float(v) != CRIT_DEFAULTS.get(k)}
    if e:
        prof["energy"] = e
    if c:
        prof["crit"] = c
    if plan:
        prof["plan"] = {k: v for k, v in plan.items() if v}
    prof["max_level_only"] = bool(max_level_only)
    return prof
