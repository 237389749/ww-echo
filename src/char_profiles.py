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
from src.logging_utils import get_logger

logger = get_logger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "assets", "char_profiles.json")

# 门槛参数的默认值(与 `PlanRequest` 保持一致; 存预设时只写非默认值, 保持 json 精简)
ENERGY_DEFAULTS = {"min": 120.0, "slope": 0.30, "floor": 0.85}
CRIT_DEFAULTS = {"target": 100.0, "slope": 0.40, "floor": 0.80}


class ProfileFileError(Exception):
    """预设文件**存在却读不出来**(BOM/半截写/手工改坏)。

    写路径必须抛这个而不是"读成空": `upsert` 是"读全量 → 改一条 → 写全量", 把坏文件当成
    空文件就会用 1 条覆盖掉用户其余全部角色(2026-11-22 后端审查 A2, 有复现)。
    """


def load_all(path: str = "") -> dict[str, dict]:
    """读全部预设 → {角色名: 预设}; 文件不存在/坏掉 → 空(不抛, 预设丢了不该挡住计算)。

    **只适合展示**: "坏掉"也返回空, 于是"坏文件 + 全量写回"会抹掉用户数据。写路径
    (`upsert` / `delete`)一律走 `_read_for_write`。
    """
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"角色预设读取失败(展示按空处理, 写入会被拒绝): {path} — {e}")
        return {}
    chars = data.get("chars") if isinstance(data, dict) else None
    return chars if isinstance(chars, dict) else {}


def _read_for_write(path: str) -> dict[str, dict]:
    """写路径专用: 文件存在却读不出来 → 抛 `ProfileFileError`(宁可失败, 不要静默覆盖)。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ProfileFileError(f"角色预设文件读不出来, 已拒绝覆盖(先修好或删掉它): {path} — {e}") from e
    chars = data.get("chars") if isinstance(data, dict) else None
    if not isinstance(chars, dict):
        raise ProfileFileError(f"角色预设文件结构不对(缺 chars 字典), 已拒绝覆盖: {path}")
    return chars


def save_all(chars: dict[str, dict], path: str = "") -> str:
    """写回全部预设(顺带保证目录存在), 返回落盘路径。

    **原子写**: 先写 `<path>.tmp` 再 `os.replace` —— 崩在中间时旧文件完好, 不会留下半截
    JSON(半截文件会被 `_read_for_write` 判为坏文件, 于是下一次保存全部失败)。
    """
    path = path or PATH
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "chars": chars}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def upsert(name: str, profile: dict, path: str = "") -> str:
    """新增/覆盖一个角色预设, 返回落盘路径。坏文件 → `ProfileFileError`(不静默覆盖全量)。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("角色名不能为空")
    path = path or PATH
    chars = _read_for_write(path)
    chars[name] = profile
    return save_all(chars, path)


def delete(name: str, path: str = "") -> bool:
    """删除一个角色预设; 返回是否真的删掉了。坏文件 → `ProfileFileError`(不静默清空)。"""
    path = path or PATH
    chars = _read_for_write(path)
    if name not in chars:
        return False
    chars.pop(name)
    save_all(chars, path)
    return True


def to_request_kwargs(profile: dict) -> dict:
    """预设 → `PlanRequest` 的字段(只给该预设真的有的字段, 其余交调用方/默认值)。

    这里把"存储用的短键"翻译成引擎/dataclass 的字段名, 是预设与引擎之间**唯一**的翻译层 ——
    CLI 与 UI 都应当只经由它(或 `apply_thresholds`)取字段, 不要再手写第二份映射:
    2026-11-22 的 A3 就是"CLI 手写一份、漏了 energy/crit/max_level_only"造成的。
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


# CLI 参数名(去掉 `--`)→ `PlanRequest` 字段。**只列"门槛 + 满级开关"**: 配装/专伤/裸面板
# 在 CLI 里已经是另一条路径(bare/corrections/allowed_bonus), 不走这里。
THRESHOLD_FIELDS: tuple[tuple[str, str], ...] = (
    ("energy-min", "energy_min"), ("energy-slope", "energy_slope"),
    ("energy-floor", "energy_floor"), ("crit-target", "crit_target"),
    ("crit-slope", "crit_slope"), ("crit-floor", "crit_floor"),
)


def apply_thresholds(ns, profile: dict, given=None) -> list[str]:
    """把预设里的**门槛 / 满级开关**写回 argparse 命名空间; 显式命令行优先。

    为什么要有这个函数(A3, 2026-11-22 后端审查): CLI 原来只搬 bare/补正/专伤/配装,
    门槛一律读 argparse 默认值 → `--save-profile` 存下来的门槛在 `--profile` 载入时被**静默丢弃**,
    于是"复现同一个角色"其实算的是另一套数(排名/A/B 判定全变, 输出看起来却完全正常)。

    `given(flag)` = 该参数是否被显式给出(CLI 传 `lambda f: _given(a, f)`); None 表示一律听预设。
    返回实际生效的字段名(测试与日志都用它)。
    """
    kw = to_request_kwargs(profile or {})
    applied: list[str] = []
    for flag, attr in THRESHOLD_FIELDS:
        if attr not in kw:
            continue
        if given is not None and given(flag):
            continue
        setattr(ns, attr, float(kw[attr]))
        applied.append(attr)
    if "max_level_only" in kw and not (given is not None and given("all-levels")):
        # CLI 里是反向开关 `--all-levels`; 预设存的是 `max_level_only`
        ns.all_levels = not bool(kw["max_level_only"])
        applied.append("all_levels")
    return applied


def _derived_json(d: DerivedBonus) -> dict:
    """`DerivedBonus` → 可存 JSON 的 dict。

    **`cap` 是 `inf` 时不写这个键**（C2）：`json.dump` 默认 `allow_nan=True` 会写出 `Infinity`，
    而 RFC 8259 不认这个字面量 —— 文件会变成"只有 Python 读得懂"的 JSON。
    `derived_of` 对缺失的 cap 给的默认值就是 `inf`，所以不写等价于"无上限"。
    """
    out = {"source": d.source, "threshold": d.threshold, "per_point": d.per_point,
           "key": d.key, "label": d.label}
    if d.cap != float("inf"):
        out["cap"] = d.cap
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
                  plan: dict | None = None, max_level_only: bool = True,
                  specialty_src: str = "explicit") -> dict:
    """把当前输入装配打成一个预设(UI「保存为…」/ CLI `--save-profile` 用)。

    门槛参数只写**非默认值** —— 让 json 一眼能看出"这个角色和常规有什么不同"。
    `specialty_src`（C17）: `"explicit"` = 用户显式指定(如 `--specialty 重击`);
    `"template"` = 由套装模板推断出来的并集 —— 后者只是"当时的默认值"，换套装后不该继续钉死。
    """
    prof: dict = {"scaling": str(scaling), "bare": {str(k): float(v) for k, v in (bare or {}).items()}}
    prof["corrections"] = [{"key": c.key, "value": float(c.value), "source": c.source}
                           for c in corrections]
    prof["derived"] = [_derived_json(d) for d in derived]
    if specialty:
        prof["specialty"] = [normalize_bonus_key(s) for s in specialty]
        prof["specialty_src"] = "explicit" if specialty_src == "explicit" else "template"
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
