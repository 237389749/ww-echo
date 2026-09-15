"""
声骸词条档位数据与评分工具 — 键名统一使用 OCR 归一化名。

档位值来自社区解包数据，从高到低排列。
固定数值攻击/防御为 4 档，其余为 8 档（游戏实际设定）。

均值口径: `get_mean` 返回**概率期望档位值** = Σ(档位值 × 官方公示概率), 不是算术平均 ——
官方公示的档位概率并不相等(如暴击最低三档各 23.3333%、最高档仅 3%), 期望因此低于算术平均:
双暴低约 10.4%, 其余低约 2.5%~2.9%。概率表见 `assets/echo_probability.json`;
表缺失/解析失败/档位值对不上(游戏改版)时回退算术平均。
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# fmt: off
_TIERS: dict[str, list[float]] = {
    "暴击":             [10.5, 9.9, 9.3, 8.7, 8.1, 7.5, 6.9, 6.3],
    "暴击伤害":         [21.0, 19.8, 18.6, 17.4, 16.2, 15.0, 13.8, 12.6],
    "共鸣效率":         [12.4, 11.6, 10.8, 10.0, 9.2, 8.4, 7.6, 6.8],
    "攻击百分比":       [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "生命百分比":       [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "防御百分比":       [14.7, 13.8, 12.8, 11.8, 10.9, 10.0, 9.0, 8.1],
    "普攻伤害加成":     [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "重击伤害加成":     [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣技能伤害加成": [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣解放伤害加成": [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "生命":             [580, 540, 510, 470, 430, 390, 360, 320],
    "攻击":             [60, 50, 40, 30],
    "防御":             [70, 60, 50, 40],
}
# fmt: on

_MEANS: dict[str, float] = {}

# 官方档位概率表(assets/echo_probability.json): {词条名: {档位值: 该档概率%}}
_PROB_PATH = os.path.join("assets", "echo_probability.json")
_prob_cache: dict[str, dict[float, float]] | None = None
_prob_mtime: float = 0


def _get_prob_path() -> str:
    """概率表路径(支持打包后的 exe 和源码运行, 与 echo_set_templates 同套路)。"""
    if os.path.exists(_PROB_PATH):
        return _PROB_PATH
    alt = Path(__file__).parent.parent / "assets" / "echo_probability.json"
    return str(alt) if alt.exists() else _PROB_PATH


def _load_tier_probs() -> dict[str, dict[float, float]]:
    """加载官方档位概率表 → {词条名: {档位值: 概率%}}; 缺失/解析失败返回 {}。"""
    global _prob_cache, _prob_mtime
    path = _get_prob_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    if _prob_cache is not None and mtime == _prob_mtime:
        return _prob_cache
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get("tier_prob", {})
        _prob_cache = {n: {float(k): float(v) for k, v in d.items()} for n, d in raw.items()}
    except (OSError, ValueError, AttributeError) as e:
        logger.warning(f"档位概率表不可用({e}); 均值回退算术平均: {path}")
        _prob_cache = {}
    _prob_mtime = mtime
    return _prob_cache


def _expected_tier(name: str, tiers: list[float], probs: dict) -> float | None:
    """概率期望档位值 = Σ(档位值×概率)/Σ概率; 档位值集合对不上(改版)返回 None 交调用方兜底。"""
    p = probs.get(name)
    if not p or len(p) != len(tiers):
        return None
    if any(not any(abs(v - t) < 1e-6 for t in tiers) for v in p):
        return None
    wsum = sum(p.values())
    return sum(v * w for v, w in p.items()) / wsum if wsum > 0 else None


def _compute_means() -> dict[str, float]:
    """词条均值(首次调用后缓存)= 概率期望档位值; 概率表缺该词条或档位值对不上 → 算术平均兜底。
    统一舍入到 1 位小数: 报告的「词条明细」直接展示该值(如 `6.9/7.5×10×1.0=9.20`), 全精度会印出
    `7.530000630000631` 这类浮点尾巴, 且展示的数与真正参与计算的数不一致。"""
    if not _MEANS:
        probs = _load_tier_probs()
        for name, tiers in _TIERS.items():
            exp = _expected_tier(name, tiers, probs)
            _MEANS[name] = round(exp if exp is not None else sum(tiers) / len(tiers), 1)
    return _MEANS


def get_mean(stat_name: str) -> float | None:
    """该词条的**概率期望档位值**(条分的分母); 概率表不可用时为算术平均。"""
    return _compute_means().get(stat_name)


# 通用默认权重(阶段十八: 按**满档词条的边际收益**重排; 套装模板权重优先, 此表仅"通用"兜底):
# 第1代(尺制定稿)是经验值, 把非双暴词条系统性抬高了(爆伤 +29%、大攻 +70%、小攻 +100%)。
# 定值口径: 覆盖**普通链度/命座**的面板(c≈70% / 爆伤≈200%) —— 这也是"通用兜底"该覆盖的档位。
#  爆伤的相对价值 = 2c/d, 随练度提高而回落: c70/d200 → 0.70, c65/d250 → 0.52, c90/d300 → 0.60。
#   暴击 1.00(全场最高, 且满暴击另有"未暴击要重打"的稳定性价值) / 爆伤 0.70 /
#   大攻·大生·大防 0.50(被声骸套装与辅助放大) / 共效 0.60(循环刚需但有阈值, 够用即溢出, 由套装按角色调整) /
#   专伤 0.40(比大攻更小, 且增伤区泛滥时进一步稀释) / 小攻·小生·小防 0.25(恒为对应大值的 0.5 倍, 机制性结论)
# 注: 期望值 = 官方公示概率期望(get_mean, 已舍入 1 位小数), 平均档 = 10.0 分、满档 ≈ 13.1~14.0。
# 有效词条集合均由用户按套装预设(weight>0 即计入)。
DEFAULT_WEIGHTS: dict[str, float] = {
    "暴击": 1.0, "暴击伤害": 0.7,
    "攻击百分比": 0.5, "生命百分比": 0.5, "防御百分比": 0.5,
    "共鸣效率": 0.6,
    "普攻伤害加成": 0.4, "重击伤害加成": 0.4,
    "共鸣技能伤害加成": 0.4, "共鸣解放伤害加成": 0.4,
    "攻击": 0.25, "生命": 0.25, "防御": 0.25,
}


def snap_to_tier(stat_name: str, raw_value: float) -> float | None:
    tiers = _TIERS.get(stat_name)
    if not tiers:
        return None
    return min(tiers, key=lambda t: abs(t - raw_value))


def tier_percentile(stat_name: str, raw_value: float) -> float | None:
    """该档位值在词条分布中的**分位**(0~100, 即"排在前 X%") = 概率表里 >= 该档的概率之和。

    这是唯一**跨词条可比**的质量度量: 官方档位概率不等, 同一个"档位水平 r ≥ 1.0"
    在暴击上覆盖前 53.33%(7.5 起算)、在暴击伤害上只覆盖前 30.00% —— 用分位则口径一致
    (暴击 8.7 与 攻击% 8.6 都约在前 22%)。概率表不可用/档位对不上 → None(调用方不展示)。
    """
    probs = _load_tier_probs().get(stat_name)
    if not probs:
        return None
    tv = snap_to_tier(stat_name, raw_value)
    if tv is None:
        return None
    key = min(probs, key=lambda v: abs(v - tv))
    if abs(key - tv) > 1e-6:
        return None
    return round(sum(p for v, p in probs.items() if v >= key), 2)


def is_stat_match(stat_name: str, raw_value: float, tol: float = 0.8) -> bool:
    """判断 (词条名, 数值) 是否≈该词条档位表中的某个档位值(离散匹配)。

    词条数值只能落在档位集合上(如 攻击 ∈ {30,40,50,60}); 用区间判断会把落在
    档位区间内的非词条值误收(如低等级主属性 攻击54 ∈ [28.5,63] 但不在档位集合)。
    离散匹配: 任一档位值与 OCR 值的差距 <= tol 才算词条。
    """
    tiers = _TIERS.get(stat_name)
    if not tiers:
        return False
    return any(abs(t - raw_value) <= tol for t in tiers)
