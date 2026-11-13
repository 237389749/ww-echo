"""
声骸属性文本的纯解析 —— OCR 文本 → 数值 / 规范词条名 / 去重签名(domain 层)。

2026-11-13 耦合 P1 从 `src/task/EnhanceEchoTask` 抽出的三个纯函数:

- `parse_number(text)`           `12.4%` / `12.4％` → `12.4`; 读不出 → `0.0`(不抛)
- `normalize_stat(name, v_str)`  OCR 词条名 → 规范词条名(逐字白名单 → 精确子串链 → 最长公共子串回退)
  (task 侧原名 `_normalize_stat`, 这里按公有函数命名; 静态方法薄封装仍在 `EnhanceEchoTask`)
- `dedup_key(name, paired_all)`  声骸名 + 全部属性行的档位值 → 去重签名(跨屏重叠去重用)

**为什么单独成模块**: 这三段是纯文本逻辑, 与 Qt/任务运行时无关, 原先却挂在 task adapter 上 →
`src.echo_inventory`(domain) 只能反向 `from src.task.EnhanceEchoTask import ...`, 顺带把
`tools/echo_plan` 拖进 PySide6/engine(import ≈0.85 s, 见 `docs/COUPLING.md` §6)。
抽出来后 domain→task_adapter = 0; `EnhanceEchoTask` 保留**同名静态方法薄封装**(调用面不变),
线上评估 / 离线重放 / 工具仍共享这一份实现 —— 改容错规则只改这里。
"""

import re

from src.echo_stats import snap_to_tier

# OCR 词条名拆字污染的公共子串回退候选(优先级同 normalize_stat 分支链)
_TIERS_ORDER = ['共鸣技能伤害加成', '共鸣解放伤害加成', '普攻伤害加成', '重击伤害加成', '暴击伤害',
                '共鸣效率', '攻击百分比', '生命百分比', '防御百分比', '攻击', '生命', '防御', '暴击']

# 逐字白名单: 全部标准词条名 + 常见主属性名的单字并集。
# OCR 把属性图标误识成汉字(艾攻击/众共鸣…)或拆字(共呜效率)时, 不在字典的字直接剥离。
_STAT_CHARS = set(''.join(_TIERS_ORDER) + '治疗效果加成')

# 声骸名里的"间隔号/空白/中点"(OCR 变体: ·/・/./空格) —— 只用于去重签名的相等性比较
_NAME_PUNCT_RE = re.compile(r'[\s·・•․∙.\-—_]')


def parse_number(text: str) -> float:
    """OCR 数值串 → `float`(`％` 视同 `%` 并剥掉百分号); 解析失败返回 `0.0`, 不抛。"""
    try:
        return float(text.replace('％', '%').split('%')[0])
    except (ValueError, IndexError):
        return 0.0


def _strip_stat_chars(raw: str) -> str:
    """逐字剥离白名单外的字符(OCR 杂字/图标误读), 返回清洗后词条名; 清洗后空/过短返回原文不猜。"""
    cleaned = ''.join(ch for ch in raw if ch in _STAT_CHARS)
    return cleaned if len(cleaned) >= 2 else raw


def _lcs_len(a: str, b: str) -> int:
    """最长公共连续子串长度(词条名 ≤10 字, 暴力窗口足够)"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > best:
                best = k
    return best


def normalize_stat(raw_name: str, value_str: str) -> str:
    """将 OCR 原始名统一为规范化词条名。

    子项拆解回退: 精确子串链未命中(OCR 拆字污染, 如 共呜效率/共鸣技难伤害加成)时,
    与候选词条名做**最长公共子串**匹配——公共子串 **≥3 字** 直接回退(平手按 _TIERS_ORDER
    概率优先); **=2 字仅当候选唯一**才回退(如 共呜效率→效率 唯一, 而 伤害 命中多个不猜);
    <2 字(攻击/暴击共享"击")拒绝, 返回原文由档位匹配自然丢弃。不确定一律不猜。
    """
    p = _strip_stat_chars(raw_name)   # 逐字白名单清洗: 图标误读/杂字(艾攻击/共呜/众共鸣…)直接剥离
    if '暴击伤害' in p: return '暴击伤害'
    if '暴击' in p: return '暴击'
    if '攻击' in p: return '攻击百分比' if ('%' in value_str or '％' in value_str) else '攻击'
    if '生命' in p: return '生命百分比' if ('%' in value_str or '％' in value_str) else '生命'
    if '防御' in p: return '防御百分比' if ('%' in value_str or '％' in value_str) else '防御'
    if '效率' in p: return '共鸣效率'
    if '普攻' in p: return '普攻伤害加成'
    if '重击' in p: return '重击伤害加成'
    if '解放' in p: return '共鸣解放伤害加成'
    if '技能' in p: return '共鸣技能伤害加成'
    best_len, best_name, tie = 0, '', 0
    for cand in _TIERS_ORDER:
        l = _lcs_len(p, cand)
        if l > best_len:
            best_len, best_name, tie = l, cand, 1
        elif l == best_len and l >= 2:
            tie += 1            # 等长候选数(平手)>1 时不猜
    if best_len >= 3 or (best_len == 2 and tie == 1):
        return best_name
    return p


def dedup_key(echo_name, paired_all):
    """去重签名 = 声骸名 + 全部属性行的档位值(主属性+词条), 档位值稳定不受 OCR 抖动影响。
    全量 OCR 文本签名(含原始数值)对同一只每次识别会因个别字符抖动而不同 → 跨屏重叠时
    seen_sigs 拦不住 → 重复记录; 档位值是离散集合, 同一声骸多次识别结果一致。
    **评估遍历与 tools/offline_eval_report 共用这一份**(以前两边各写一遍, 改一处漏一处)。

    名字里的**间隔号/空白/中点**先去掉: OCR 会把 `双极·渊陨重锋` 读成 `双极・渊陨重锋`(全角中点),
    名字不同 → 同一只被记两次(实测 20261008 那批 #38/#44 就是同一只两次, 让组合穷举出现成对的同分组合)。
    这里只做"相等性比较"用, 不做名字查表, 所以去掉标点是安全的。
    """
    parts = [_NAME_PUNCT_RE.sub('', str(echo_name))]
    for raw_n, v_str in paired_all:
        norm = normalize_stat(raw_n, v_str)
        v = parse_number(v_str)
        tier_v = snap_to_tier(norm, v)
        parts.append(f'{norm}={tier_v if tier_v is not None else round(v, 2)}')
    return '|'.join(parts)
