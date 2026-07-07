"""
声骸词条档位数据与评分工具。

档位值来自社区解包数据，从高到低排列。
"""

# fmt: off
# 副词条档位表 (从高到低)
_TIERS: dict[str, list[float]] = {
    "暴击率":                   [10.5, 9.9, 9.3, 8.7, 8.1, 7.5, 6.9, 6.3],
    "暴击伤害":                 [21.0, 19.8, 18.6, 17.4, 16.2, 15.0, 13.8, 12.6],
    "共鸣效率":                 [12.4, 11.6, 10.8, 10.0, 9.2, 8.4, 7.6, 6.8],
    "百分比攻击":               [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "百分比生命":               [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "百分比防御":               [14.7, 13.8, 12.8, 11.8, 10.9, 10.0, 9.0, 8.1],
    "普攻伤害加成":             [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "重击伤害加成":             [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣技能伤害加成":         [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "共鸣解放伤害加成":         [11.6, 10.9, 10.1, 9.4, 8.6, 7.9, 7.1, 6.4],
    "固定数值生命":             [580, 540, 510, 470, 430, 390, 360, 320],
    "固定数值攻击":             [60, 50, 40, 30],
    "固定数值防御":             [70, 60, 50, 40],
}
# fmt: on

# 均值缓存
_MEANS: dict[str, float] = {}


def _compute_means() -> dict[str, float]:
    """计算每个词条的平均值（所有档位取平均）。"""
    if not _MEANS:
        for name, tiers in _TIERS.items():
            _MEANS[name] = sum(tiers) / len(tiers)
    return _MEANS


def get_mean(stat_name: str) -> float | None:
    """获取词条均值。"""
    return _compute_means().get(stat_name)


def snap_to_tier(stat_name: str, raw_value: float) -> float | None:
    """将 OCR 读出的原始值修正为最接近的合法档位值。"""
    tiers = _TIERS.get(stat_name)
    if not tiers:
        return None
    return min(tiers, key=lambda t: abs(t - raw_value))


def score_stat(stat_name: str, raw_value: float) -> float:
    """
    计算单个词条的"词条当量"得分。

    得分 = 档位修正值 / 均值
    不在已知词条表中则返回 0。
    """
    tier_value = snap_to_tier(stat_name, raw_value)
    if tier_value is None:
        return 0.0
    mean = get_mean(stat_name)
    if mean is None or mean == 0:
        return 0.0
    return tier_value / mean


# 默认权重：所有词条均等
DEFAULT_WEIGHTS: dict[str, float] = {
    "暴击率": 1.0,
    "暴击伤害": 1.0,
    "共鸣效率": 1.0,
    "百分比攻击": 1.0,
    "百分比生命": 1.0,
    "百分比防御": 1.0,
    "普攻伤害加成": 1.0,
    "重击伤害加成": 1.0,
    "共鸣技能伤害加成": 1.0,
    "共鸣解放伤害加成": 1.0,
    "固定数值生命": 1.0,
    "固定数值攻击": 1.0,
    "固定数值防御": 1.0,
}
