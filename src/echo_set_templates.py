"""
声骸套装模板 — 从 JSON 文件加载套装预期词条及其权重。

JSON 格式 (assets/echo_set_templates.json):
{
  "version": 1,
  "sets": {
    "套装名": {
      "词条名": 权重, ...,
      "_core_first": ["词条名", ...]   // 可选: Lv5 首条必须命中的核心词条; 缺省=全部有效词条
    },
    ...
  }
}

每个套装的权重字典同时定义:
1. 预期有效词条列表 (字典的键)
2. 各词条的独立权重 (字典的值, 渐进式评分时使用)
3. _core_first(可选): 首条核心词条集合——Lv5/10 结构判定只认这些词条; 强化与评估配置通用
"""

import json
import os
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

# 游戏中实际存在的 13 个副词条名称(白名单)。**展示顺序也以这里为唯一来源** ——
# 套装配置表格(ui/set_config_tab) 与强化配置下拉(EnhanceEchoTask) 都直接用 STAT_ORDER, 不再各抄一份。
STAT_ORDER: tuple[str, ...] = (
    "暴击", "暴击伤害",
    "攻击百分比", "攻击",
    "生命百分比", "生命",
    "防御百分比", "防御",
    "共鸣效率",
    "普攻伤害加成", "重击伤害加成",
    "共鸣解放伤害加成", "共鸣技能伤害加成",
)
VALID_STAT_NAMES: frozenset[str] = frozenset(STAT_ORDER)

# 套装模板特殊键: Lv5 首条核心词条集合(可选, 缺省=全部有效词条)
_CORE_FIRST = '_core_first'
# 套装模板特殊键: 该套装包含的声骸清单 {"4c": [名...], "3c": [...], "1c": [...]}
_ECHOES = '_echoes'
_COST_KEYS = ('4c', '3c', '1c')
# 套装模板特殊键: 套装图标名(wuther.in IconElementAttri{名}; 供按图标识别/数据核对)
_ICON = '_icon'

# JSON 模板文件路径
_TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")
# 官方配置表生成物(见 tools/gen_echo_data.py): 声骸↔套装 / 皮肤本体名 / 官方主属性方案。
# 存在时声骸↔套装以它为准(含 3.7 新套装与皮肤条目), 模板的 `_echoes` 只作回退。
_GAMEDATA_PATH = os.path.join("assets", "gamedata", "echo_data.json")

# 缓存
_template_cache: dict | None = None
_cache_mtime: float = 0
# 声骸名 → [套装名,...] 反向索引(随模板缓存重建; 一个声骸可属多个套装)
_echo_index: dict[str, list[str]] | None = None
# 所有声骸名的汉字字符集(逐字白名单, 参照词条过滤 _STAT_CHARS): 用于剥离 OCR 错字/杂字
_echo_chars: set[str] = set()
# 皮肤声骸名(如 `异相·巡游骑士`) → 本体名(`巡游骑士`); 仅来自生成物
_skin_bases: dict[str, str] = {}
# 生成物缓存
_gamedata_cache: dict | None = None
_gamedata_mtime: float = 0
# 声骸名"皮肤前缀"——`异相·X` 在配置里是**独立声骸, 有自己的套装**;
# 「梦魇·」是真实前缀(独立声骸), 保留。仅在生成物缺失时退回"剥前缀复用本体套装"的旧口径。
_ECHO_SKIN_PREFIXES = ('异相·', '异相')


def _get_template_path() -> str:
    """获取模板文件绝对路径（支持打包后的 exe 和源码运行）。"""
    # 尝试相对于当前工作目录
    if os.path.exists(_TEMPLATE_PATH):
        return _TEMPLATE_PATH
    # 尝试相对于源码目录
    src_dir = Path(__file__).parent.parent
    alt_path = src_dir / "assets" / "echo_set_templates.json"
    if alt_path.exists():
        return str(alt_path)
    return _TEMPLATE_PATH


def _validate_and_filter(sets: dict) -> dict[str, dict]:
    """校验并过滤套装模板: 去除非白名单词条, 去重, 报告无效条目。
    返回 {套装名: {'weights': {词条:权重}, 'core_first': [词条,...]|None,
                    'echoes': {'4c': [...], '3c': [...], '1c': [...]}}}。"""
    cleaned: dict[str, dict] = {}
    total_dropped = 0

    for set_name, stats in sets.items():
        if not isinstance(stats, dict):
            logger.warning(f"[模板校验] 套装 '{set_name}' 格式错误(非字典), 跳过")
            continue

        valid_stats: dict[str, float] = {}
        core_first = None
        icon = ''
        echoes = {k: [] for k in _COST_KEYS}
        for stat_name, weight in stats.items():
            if stat_name == _CORE_FIRST:
                core_first = [s for s in weight if s in VALID_STAT_NAMES]
                continue
            if stat_name == _ECHOES:
                if isinstance(weight, dict):
                    for k in _COST_KEYS:
                        v = weight.get(k)
                        if isinstance(v, (list, tuple)):
                            echoes[k] = [str(n) for n in v if str(n).strip()]
                continue
            if stat_name == _ICON:
                icon = str(weight).strip()
                continue
            if stat_name not in VALID_STAT_NAMES:
                logger.warning(
                    f"[模板校验] 套装 '{set_name}' 中的 '{stat_name}' 不是合法词条, 已过滤"
                )
                total_dropped += 1
                continue
            if stat_name in valid_stats:
                logger.warning(
                    f"[模板校验] 套装 '{set_name}' 中的 '{stat_name}' 重复, 保留后者"
                )
            valid_stats[stat_name] = float(weight)

        cleaned[set_name] = {'weights': valid_stats, 'core_first': core_first,
                             'echoes': echoes, 'icon': icon}

    if total_dropped:
        logger.warning(
            f"[模板校验] 共过滤 {total_dropped} 个无效词条"
            f" (合法词条共 {len(VALID_STAT_NAMES)} 个: {sorted(VALID_STAT_NAMES)})"
        )
    logger.info(f"[模板校验] {len(cleaned)} 个套装通过校验")
    return cleaned


def load_templates(force: bool = False) -> dict[str, dict]:
    """加载套装模板, 返回 {套装名: {'weights':…, 'core_first':…, 'echoes':…}}。自动过滤无效词条。"""
    global _template_cache, _cache_mtime, _echo_index

    path = _get_template_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0

    if not force and _template_cache is not None and mtime == _cache_mtime:
        return _template_cache

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_sets = data.get("sets", {})
        _template_cache = _validate_and_filter(raw_sets)
        _cache_mtime = mtime
        _echo_index = None   # 模板变化 → 反向索引失效, 下次 get_set_by_echo 重建
        logger.info(f"加载套装模板: {len(_template_cache)} 个套装 from {path}")
        return _template_cache
    except FileNotFoundError:
        logger.warning(f"套装模板文件不存在: {path}, 使用空配置")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"套装模板 JSON 解析失败: {e}, 使用空配置")
        return {}


def _get_gamedata_path() -> str:
    """生成物路径(与模板同套路: 支持打包后的 exe 和源码运行)。"""
    if os.path.exists(_GAMEDATA_PATH):
        return _GAMEDATA_PATH
    alt = Path(__file__).parent.parent / "assets" / "gamedata" / "echo_data.json"
    return str(alt) if alt.exists() else _GAMEDATA_PATH


def load_gamedata(force: bool = False) -> dict | None:
    """加载官方配置表生成物 `assets/gamedata/echo_data.json`; 缺失/损坏返回 None(退回模板口径)。"""
    global _gamedata_cache, _gamedata_mtime, _echo_index
    path = _get_gamedata_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if not force and _gamedata_cache is not None and mtime == _gamedata_mtime:
        return _gamedata_cache
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(f"生成物不可用({e}), 声骸↔套装退回模板 _echoes: {path}")
        return None
    _gamedata_cache, _gamedata_mtime = data, mtime
    _echo_index = None            # 生成物变化 → 反向索引失效
    logger.info(f"加载官方数据: {len(data.get('sets', {}))} 套装 / "
                f"{len(data.get('echoes', {}))} 声骸 from {path}")
    return data


def get_set_echoes(set_name: str | None) -> dict[str, list[str]] | None:
    """获取指定套装包含的声骸清单 {'4c': [...], '3c': [...], '1c': [...]}; 通用/未知返回 None。

    有生成物时以官方表为准(含 3.7 新套装与皮肤条目), 否则退回模板的 `_echoes`。
    """
    if not set_name or set_name == "通用":
        return None
    gd = load_gamedata()
    if gd and set_name in gd.get("sets", {}):
        return gd["sets"][set_name]["echoes"]
    info = load_templates().get(set_name)
    return info.get("echoes") if info else None


def _strip_echo_prefix(name: str) -> str:
    """剥离声骸名皮肤前缀「异相」(异相·双极·星升辉铳 → 双极·星升辉铳)。"""
    for p in _ECHO_SKIN_PREFIXES:
        if name.startswith(p):
            return name[len(p):].lstrip('· ')
    return name


def _lcs_len(a: str, b: str) -> int:
    """最长公共连续子串长度。"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > best:
                best = k
    return best


def _substring_hits(candidate: str, index: dict) -> list[str]:
    """candidate 与模板名互为子串的模板名列表。"""
    return [t for t in index if len(candidate) >= 2 and len(t) >= 2
            and (candidate in t or t in candidate)]


def _match_echo_key(name: str, index: dict, chars: set, skins: dict | None = None) -> str | None:
    """声骸名(可能是 OCR 错字) → **索引里的规范声骸名**; 匹配不到返回 None。

    三级容错(参照词条过滤 _normalize_stat): ① 精确 ② 逐字白名单清洗
    (只留声骸名字符集内汉字, 剥 OCR 错字/杂字) ③ 子串(唯一候选) ④ 最长公共子串 LCS(≥3 字且唯一)。

    有生成物时(`skins` 非空) **皮肤名与本体名分池匹配**: 配置里 `异相·X` 是独立声骸、有自己的套装,
    与本体 X 不同者实测 13 例, 所以皮肤名只在皮肤池里找、本体名只在本体池里找 —— **绝不跨池回退**,
    跨池回退正是"剥前缀复用本体套装"那个错。生成物缺失时退回旧口径(剥前缀后用全表)。
    """
    if not name:
        return None
    skins = skins or {}
    is_skin = any(name.startswith(p) for p in _ECHO_SKIN_PREFIXES)
    if skins:
        pool = {k: v for k, v in index.items() if (k in skins) == is_skin}
        variants = (name,)
    else:
        pool = index
        variants = (_strip_echo_prefix(name), name)
    for v in variants:
        if v and v in pool:
            return v
    for v in variants:
        if not v:
            continue
        cleaned = ''.join(ch for ch in v if ch in chars)
        for candidate in (cleaned, v):
            if len(candidate) < 2:
                continue
            if candidate in pool:
                return candidate
            hits = _substring_hits(candidate, pool)
            if len(hits) == 1:
                return hits[0]
    # LCS 回退
    for v in variants:
        if not v:
            continue
        cleaned = ''.join(ch for ch in v if ch in chars)
        base = cleaned if len(cleaned) >= 2 else v
        scored = [(l, t) for l, t in ((_lcs_len(base, t), t) for t in pool) if l >= 3]
        if scored:
            best = max(l for l, _ in scored)
            top = [t for l, t in scored if l == best]
            if len(top) == 1:
                return top[0]
    return None


def _get_echo_index() -> tuple[dict, set, dict]:
    """声骸名 → 套装列表 的反向索引 + 声骸名汉字集 + 皮肤名→本体名(随生成物/模板缓存重建)。"""
    global _echo_index, _echo_chars, _skin_bases
    if _echo_index is None:
        idx: dict[str, list[str]] = {}
        chars: set[str] = set()
        skins: dict[str, str] = {}
        gd = load_gamedata()
        if gd:
            for n, e in (gd.get("echoes") or {}).items():
                idx[n] = list(e.get("sets") or [])
                if e.get("base"):
                    skins[n] = e["base"]
                chars.update(ch for ch in n if '\u4e00' <= ch <= '\u9fff')
        else:
            for set_name, info in load_templates().items():
                for names in (info.get("echoes") or {}).values():
                    for n in names:
                        lst = idx.setdefault(n, [])
                        if set_name not in lst:
                            lst.append(set_name)
                        chars.update(ch for ch in n if '\u4e00' <= ch <= '\u9fff')
        _echo_index, _echo_chars, _skin_bases = idx, chars, skins
    return _echo_index, _echo_chars, _skin_bases


def normalize_echo_name(echo_name: str) -> str | None:
    """OCR 声骸名 → 模板里的**规范名**(如 `冠顶械集` → `冠顶械隼`); 拿不准时返回 None。

    供报告显示用: 套装映射本来就走了这条容错链(所以判定是对的), 但显示若沿用 OCR 原文,
    就会把错字带进报告 —— 用户看到的名字与实际声骸不符。
    **拿不准就不换**: 名字层的子串抢跑(阶段十一已知失效, 如 `梦魔·青羽鹭` 会命中作为独立声骸
    存在的 `青羽鹭`)不该把错误名字带进报告 —— 只在"剥掉错字后命中、且命中名不比清洗名短"时替换。
    """
    index, chars, skins = _get_echo_index()
    key = _match_echo_key(echo_name, index, chars, skins)
    if key is None or key == echo_name:
        return key
    cleaned = ''.join(ch for ch in _strip_echo_prefix(echo_name) if ch in chars)
    return key if len(key) >= len(cleaned) else None


def get_sets_by_echo(echo_name: str) -> list[str]:
    """声骸名 → 所属套装名列表(一个声骸可属多个套装; 按索引声明顺序)。未录入返回 []。

    有生成物时索引来自官方配置表(229 个显示名, 含皮肤条目各自独立的套装);
    否则退回模板 `_echoes` + 剥「异相」前缀的旧口径。索引随生成物/模板缓存重建。
    """
    index, chars, skins = _get_echo_index()
    key = _match_echo_key(echo_name, index, chars, skins)
    return list(index[key]) if key else []


def get_set_by_echo(echo_name: str, prefer: str | None = None) -> str | None:
    """声骸名 → 套装名(评估时按声骸名选套装配置)。未录入返回 None(调用方回退通用)。
    多套装声骸: prefer 在候选内则取其(尊重调用方语境), 否则取声明顺序首个。"""
    sets = get_sets_by_echo(echo_name)
    if not sets:
        return None
    if prefer and prefer in sets:
        return prefer
    return sets[0]


def get_all_set_names() -> list[str]:
    """获取所有套装名列表。"""
    templates = load_templates()
    return list(templates.keys())


def get_set_weights(set_name: str | None) -> dict[str, float] | None:
    """
    获取指定套装的 {词条名: 权重} 字典。
    返回 None 表示使用通用配置。
    """
    if not set_name or set_name == "通用":
        return None
    templates = load_templates()
    info = templates.get(set_name)
    return info["weights"] if info else None


def get_set_core_first(set_name: str | None) -> list[str] | None:
    """
    获取指定套装的 Lv5 首条核心词条集合(_core_first)。
    缺省(未配置) = 全部有效词条; 通用模式返回 None。
    """
    if not set_name or set_name == "通用":
        return None
    templates = load_templates()
    info = templates.get(set_name)
    if not info:
        return None
    core = info.get("core_first")
    if core:
        return list(core)
    return list(info["weights"].keys())
