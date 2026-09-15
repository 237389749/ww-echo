"""整只声骸的分数分布(蒙特卡洛) —— 回答"这一只在随机群体里排第几"。

按官方概率(`assets/echo_probability.json`)模拟满级声骸: 5 条副词条 **无放回**(13 种里选 5, 互不重复,
对应"已激活的词条不会重复出现"), 每条按该词条的官方档位概率抽档位; 条分按套装权重求和
(与 `EnhanceEchoTask.compute_weighted_score` 同口径: 档位值÷期望值×10×权重)。
**套装不认的词条照样占一个词条位**(只是记 0 分) —— 这是"5 条里有几条有用"的真实来源。
于是任意一只实际声骸的得分可换算成 **"击败 X% 的随机声骸"**, 比逐条分位更贴近"这只好不好"。

成本: 每个套装首次调用跑 N 次抽样(默认 5 万, 约 1 秒), 结果按套装缓存; 只对本次报告出现的套装计算。
自检: E[分数] = 5 × 10 × Σw(套装) / 13(未认词条计入 13 种的分母)。
"""

import bisect
import itertools
import random

from src.echo_set_templates import get_set_weights
from src.echo_stats import DEFAULT_WEIGHTS, _TIERS, _load_tier_probs, get_mean

SAMPLES = 50000        # 每个套装的抽样次数: 分位误差约 ±0.7%, 约 1 秒
_cache: dict[str, list[float]] = {}


def _contrib_table(set_name: str | None) -> dict[str, tuple[list[float], list[float]]]:
    """{词条名: (档位贡献列表, 累积概率列表)}, **13 种词条全覆盖**。

    套装不认的词条(权重 0) → 单点分布 `([0.0], [1.0])`, 仍占一个类型位(参与"类型不重复"约束);
    认的词条 → 各档位的贡献 = 档位值 ÷ 期望值 × 10 × 权重(与 compute_weighted_score 同式)。
    """
    probs = _load_tier_probs()
    weights = get_set_weights(set_name) if (set_name and set_name != '通用') else None
    table: dict[str, tuple[list[float], list[float]]] = {}
    for name, tiers in _TIERS.items():
        weight = weights.get(name, 0.0) if weights is not None else DEFAULT_WEIGHTS.get(name, 0.0)
        mean, prob = get_mean(name), probs.get(name)
        if not mean or not prob:
            continue
        pairs = [(v, prob[v]) for v in tiers if v in prob]
        if weight <= 0 or not pairs:                        # 不认 → 恒 0 分, 但仍占类型位
            table[name] = ([0.0], [1.0])
            continue
        table[name] = ([v / mean * 10 * weight for v, _ in pairs],
                       list(itertools.accumulate(p for _, p in pairs)))
    return table


def score_distribution(set_name: str | None, samples: int = SAMPLES, seed: int = 0) -> list[float]:
    """该套装下"随机满级声骸"的分数分布(升序列表)。按套装缓存。"""
    key = set_name or '通用'
    if key in _cache:
        return _cache[key]
    table = _contrib_table(None if key == '通用' else key)
    names = list(table)
    if len(names) < 5:
        _cache[key] = []
        return _cache[key]
    rng = random.Random(seed)
    scores = []
    for _ in range(samples):
        total = 0.0
        for nm in rng.sample(names, 5):                     # 无放回: 词条类型互不重复
            contribs, cum = table[nm]
            total += rng.choices(contribs, cum_weights=cum)[0]
        scores.append(total)
    scores.sort()
    _cache[key] = scores
    return scores


def score_percentile(set_name: str | None, score: float) -> float | None:
    """该得分"击败 X% 的随机声骸"(0~100); 套装没有一个可认词条 → None。"""
    dist = score_distribution(set_name)
    if not dist:
        return None
    return round(bisect.bisect_left(dist, score) / len(dist) * 100, 1)


def max_score(set_name: str | None) -> float:
    """该套装的"理想毕业上限" = 权重最高的 5 个词条各自满档的分数之和(未认的记 0)。

    用作"完成度"的分母 —— 它是**固定基准**(只取决于套装配置), 所以跨件可比。
    """
    weights = get_set_weights(set_name) if (set_name and set_name != '通用') else None
    w = weights if weights is not None else DEFAULT_WEIGHTS
    top = sorted(((v, n) for n, v in w.items() if v > 0), reverse=True)[:5]
    total = 0.0
    for v, n in top:
        tiers, mean = _TIERS.get(n), get_mean(n)
        if not tiers or not mean:
            continue
        total += max(tiers) / mean * 10 * v
    return total


def completeness(set_name: str | None, score: float) -> float | None:
    """**完成度** = 该只得分 ÷ 该套装"Top-5 全满档"的分数 × 100(0~100+)。

    100% = 毕业(5 条理想词条全满档)。它同时含"有效条数"与"档位高低":
    只出 3 条有效的件上限天然只有约 72%(分母是 5 条)。
    与 `score_percentile` 的区别: 后者以"随机产出"为基准, 对"抽到几条有效词条"远比"档位多高"敏感
    (认/不认 的贡献差是 0 → ~10 分, 而档位只让单条在 6.9~14.0 间波动), 于是"击败 97%~100%"挤成一团,
    不适合当玩家看到的"好/差"标尺 —— 报告主指标因此用完成度。
    """
    mx = max_score(set_name)
    if mx <= 0:
        return None
    return round(score / mx * 100, 1)
