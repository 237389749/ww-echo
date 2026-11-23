# EnhanceEchoTask.py
import re
import threading
import time
import os
from collections import Counter

import cv2

from ww_engine import FindFeature, Logger, clear_folder, get_bounding_box
from src import echo_parse, echo_scoring
from src import echo_grid
from src import echo_panel_shot
from src.echo_parse import parse_number  # noqa: F401  (旧调用面: from src.task.EnhanceEchoTask import parse_number)
from src.echo_stats import (snap_to_tier, get_mean, is_stat_match,
                            tier_index, DEFAULT_WEIGHTS, generic_weights_for_main)  # noqa
from src.echo_main_prop import check_main_values
from src.echo_set_templates import (STAT_ORDER, get_all_set_names, get_set_weights, match_set_text,
                                    get_set_core_first, get_set_low_first, has_heading, name_own_line,
                                    get_sets_by_echo, echo_set_counts, normalize_echo_name, load_gamedata)
from src.echo_icon_match import (match_icon, icon_box_at_level, MIN_MARGIN, MIN_SCORE,
                                 badge_hue, filter_by_set_hue, hue_group)
from src.task.BaseEchoTask import BaseEchoTask

logger = Logger.get_logger(__name__)

number_pattern = re.compile(r"^[\d.%％ ]+$")
property_pattern = re.compile(r"[\u4e00-\u9fff]{2,}")

# 详情面板**固定表头**里的等级(`+25` / `+5` / `+0`)。与名字/COST 一样不随滚动移动 —— 实测
# 174 个面板读取里 126 个读出 `+NN`, 置信 ≥0.90, y 只在 144~149 之间波动(取 y 最小者 = 名字右侧那个)。
# 词条数值框(`10.0%` / `150`)不会带 `+`, 所以锚定 `^\+\d{1,2}$` 不会误收。
LEVEL_RE = re.compile(r'^\s*\+\s*(\d{1,2})\s*$')


def _tier_from_level(level, n_stats: int) -> int:
    """等级 + 词条条数 → tier(0~5)。**只升不降**。

    为什么需要: 等级原本只按词条条数反推(`tier = len(stats)`)。而词条数只是**下界**
    (n 条 ⇒ 等级 ≥ 5n): 一条词条 OCR 漏读, +25 就会被当成 +20 → 走"未满级"分支,
    满级件被判成「建议强化/不建议强化」(2026-11-19 report1 #1 就是这么来的:
    5 条只读到 4 条 → 17.29 分判"不建议强化", 而上一轮同一只 5 条 27.29 分是"达标")。
    等级读到了就以它为准、但不低于已读到的条数(读到的词条不能凭空丢);
    等级认不出(None) → 退回词条数(旧行为, 不改变纯离线重放的结果)。
    """
    tier = int(n_stats)
    if level is not None:
        tier = max(tier, min(5, max(0, int(level)) // 5))
    return tier


# 声骸网格区(归一化)。点击点一律**夹在这个框内**(见 clamp_to_grid)。
GRID_BOX = (0.10, 0.15, 0.72, 0.92)
# 点击点离网格边缘至少留这个比例: 边缘格/重试点落到框外时会点到背包两侧/底部的
# "整理·筛选·培养"按钮, 游戏会跳去别的功能界面(2026-11-19 用户现场)。
CLICK_INSET = 0.012


def clamp_to_grid(x, y, box=GRID_BOX, inset=CLICK_INSET):
    """把归一化点击点夹进网格区(留 `inset` 边), 返回 (x, y)。"""
    x0, y0, x1, y1 = box
    return (min(max(x, x0 + inset), x1 - inset),
            min(max(y, y0 + inset), y1 - inset))


# 详情面板的 COST 角标: 实测 219 张面板里 117 张 OCR 把数字并进同一个框(`COST 4`/`COST4`),
# 其余 102 张只读到标签 `COST` —— 后者取**同一行右侧**的数字框(102/102 都能找到)。
_COST_RE = re.compile(r'COST\s*([134])')

# COST 角标区(归一化) + 重读放大倍数: 数字是小字, 全屏 1× OCR 有时**整个数字框都检不出来**
# (20261008 那批 135 只里 27 只 parse_cost 返 None; 用保存的面板截图复跑 OCR 复现: `eval_062`
#  只出 'COST', 没有数字框)。只截这一小块放大 3× 再读 → 27/27 全部读回, 且与"第 2 行固有属性反推"
# 的 COST 完全一致(见 echo_inventory.infer_cost / tests)。
_COST_ROI = (0.685, 0.19, 0.792, 0.25)
_COST_UPSCALE = 3


def parse_cost(boxes) -> int | None:
    """详情面板 OCR 框 → COST(1/3/4); 认不出返回 None。"""
    items = list(boxes)
    for b in items:
        m = _COST_RE.search(str(b.name))
        if m:
            return int(m.group(1))
    for b in items:
        if str(b.name).strip() != 'COST':
            continue
        right = sorted((x for x in items
                        if x is not b and abs(x.y - b.y) <= 12 and x.x >= b.x + b.width - 12),
                       key=lambda x: x.x)
        for x in right:
            m = re.fullmatch(r'([134])\D{0,2}', str(x.name).strip())
            if m:
                return int(m.group(1))
    return None


# 通用模式(套装未映射)算基准线 B 用的**固定代表档位**。
# 为什么不再从 DEFAULT_WEIGHTS 去重自动推导: B 是"保留地板"的**用户口径阈值**, 评分权重是可调策略;
#   2026-11-13 把通用共效 0.6→0.5 后, 去重档位从 6 个变成 5 个, 最低 4 条会多算进 0.7 档 →
#   B(5) 会从 17.5 自动抬到 18.5, 等于顺手收紧了保留线, 这不是权重调整的本意。
# 因此这里冻结为历史 6 档; 改评分权重时请明确决定 B 是否跟着变, 并同步本行 + 文档/测试。
# 当前值 = (1.0, 0.7, 0.6, 0.5, 0.4, 0.25) → 最低 tier-1 条之和×10 = (0.25+0.4+0.5+0.6)×10 = 17.5。
_GENERAL_WEIGHTS = (1.0, 0.7, 0.6, 0.5, 0.4, 0.25)

# 评估遍历的 debug 数据集开关(**默认关**): 每格存 全屏 PNG + ROI 叠图 + 三个区域裁剪, 200 只约数百 MB~1GB。
# 需要离线核对坐标/OCR/图标回归时改 True —— 它是 tools/eval_icon_match.py 与 tools/offline_eval_report.py 的数据源。
SAVE_DEBUG_DATASET = False

# 面板滚动数据集开关(**默认开**, 2026-11-19 用户口径): 只对"需要滚面板找套装"的声骸 ——
# 每步存一张面板裁剪 PNG + 该步 OCR 行(`panel_ocr.jsonl`), 存完把各步拼成一张**长图**
# (`<idx>_<名字>_long.png`), 再存一张回顶后的证明图(`_top.png`)。
# 好处: 一次真机跑就能离线反复重放(tools/analysis/replay_panel_scroll.py), 不必重开游戏;
# 占用约 100~400 KB/只(只存多义件), 对跑一轮 10 分钟的成本可忽略。
SAVE_PANEL_DATASET = True

# 注: 旧的"好词条"分位阈值常量 `HI_PERCENTILE` 已废弃 —— "建议重铸"档不再数"好词条条数",
# 改为按 `reforge_plan` 的"锁 N 条刷 M 条期望分"判定(见 judge_echo)。分位本身仍用于报告展示词条的
# `[前 X%]`(`echo_stats.tier_percentile`): 官方档位概率不等, 分位是唯一跨词条可比的度量
# (旧口径"档位值/期望 ≥ 1.0"在暴击上覆盖前 53.33%、暴击伤害仅前 30.00%, 口径并不一致)。
# 频整器成本见 `EnhanceEchoTask.REFORGE_PRICE`(官方: 锁 L 条 = L−1 个, 锁 1~2 条按 1 个计)。


_UNKNOWN_SET_WARNED: set[str] = set()


def _legacy_threshold(set_name: str, tier: int) -> float:
    """基准门槛 B = 该套装有效键权重升序最低 (tier-1) 条 ×10 之和。
    通用模式走 _GENERAL_WEIGHTS 代表集 → tier=5 时为 (0.25+0.4+0.5+0.6)×10 = 17.5。
    注意: 它作为"基准门槛"用, 但**单独作达标线已废弃** —— "键多但权重低"的套装(隐世回光/轻云出月)
    会被压到 5~6 分(见 _tier_threshold 注释)。

    未知套装名(模板里没有)会算出 B=0 → 该套装全判达标。`_check_set_keys` 只挡得住"配置套装"那条路,
    逐只解析出来的套装名没有二次校验, 所以这里至少**喊一次**(C5, 不抛: 评估中途抛会丢掉整轮结果)。
    """
    if tier <= 2:
        return 0.0
    if not set_name or set_name == '通用':
        src = _GENERAL_WEIGHTS
    else:
        weights = get_set_weights(set_name)
        if weights is None:
            if set_name not in _UNKNOWN_SET_WARNED:
                _UNKNOWN_SET_WARNED.add(set_name)
                logger.warning(f'套装「{set_name}」不在模板里 → 基准线 B 按 0 处理(该套装判定会偏松)')
            weights = {}
        src = tuple(weights.values())
    return round(sum(sorted(10 * w for w in src if w > 0)[:tier - 1]), 1)


def _tier_threshold(set_name: str, tier: int, stats=None) -> float:
    """达标线(锚线) A = 10 × (本只"出现的有效词条"权重之和), L = tier-1; **返回纯 A, 不取 max(A, B)**。

    返回**纯 A** = 10 × (本只"出现的有效词条"(该套装权重>0 且真的出现)权重之和) —— 相当于要求
      "这些词条每条都达到自己的平均档位"的水平(平均档 = 有价值)。**不在此处取 max(A, B)**:
      A 与基准线 B 的关系交给 judge_echo 判 —— 只有 A ≥ B 时 A 才是有效达标线, A < B 说明
      "出现的有效词条太少, 求和项不足以支撑达标", 该只最高只能到"保留"。
    数学: k(=出现有效词条数) ≥ L 时 A ≥ B 恒成立(k 元子集之和 ≥ 最小 k 元之和 ≥ 最小 L 元之和);
      k < L 时 A 可能 < B(实测 34% 样本 k < L, 其中 25 只真的更低)。出现有效词条 0 条 → 返回 0。
    注: **不引入通用线**作 A 的下限 —— 套装配置若被定制, 说明其取向是刻意的(如轻云出月
      用 4 个 0.1 的"占位键"来压低基准线, 因为真正的核心词条少), 不应被通用标准覆盖。
    Lv5/10(tier<=2) 走"有效词条存在"结构判定 → 返回 0(不用分数)。
    **旧规则单独使用已废弃**: 它独自会把"键多但权重低"的套装锚线压到极低(实测 轻云出月 9 键/4 个
    专伤 0.1 → Lv25 仅 4.0; 隐世回光删掉 4 个占位键后现为 5 键 → 19.0, 已不属此类),
    变成"词条种类越多越易达标"。"""
    if tier <= 2:
        return 0.0
    weight_map = DEFAULT_WEIGHTS if (not set_name or set_name == '通用') else (get_set_weights(set_name) or {})
    base = _legacy_threshold(set_name, tier)      # 旧规则线(套装按自身权重; 只有"通用"模式才等于通用线)
    appeared = [weight_map.get(n, 0.0) for n, _ in (stats or []) if weight_map.get(n, 0.0) > 0]
    if not appeared:
        return 0.0                                # A=0(必然 < B) → 该只最高只能到"保留"
    return round(10 * sum(appeared), 1)           # 达标线 A = 10 × (出现有效词条的权重之和)


class EnhanceEchoTask(BaseEchoTask, FindFeature):

    # ── 共享工具 ──

    @staticmethod
    def _check_set_keys(set_name: str) -> tuple:
        """键数硬拒: 套装有效词条数 <5 → (False, 提示)。通用模式跳过。"""
        if not set_name or set_name == '通用':
            return True, ''
        w = get_set_weights(set_name) or {}
        k = sum(1 for v in w.values() if v > 0)
        if k < 5:
            return False, (f'套装《{set_name}》有效词条仅 {k} 个(<5): '
                           f'强化后必有 5 词条, 最少需要 5 个有效词条, 请在套装配置中补足')
        return True, ''

    @staticmethod
    def _normalize_stat(raw_name: str, value_str: str) -> str:
        """OCR 原始名 → 规范化词条名(薄封装, 实现与容错规则见 `src.echo_parse.normalize_stat`)。

        逐字白名单清洗 → 精确子串链 → 最长公共子串回退; 不确定一律不猜, 返回清洗后的原文
        (由 `is_stat_match` 的离散档位匹配自然丢弃)。
        """
        return echo_parse.normalize_stat(raw_name, value_str)

    @staticmethod
    def check_main_prop(set_name, cost, main_props) -> dict | None:
        """官方「声骸管理方案」(`PhantomManagePlanV2`, 见 tools/gen_echo_data.py) 的主属性判定。

        游戏内置方案按 (套装, COST) 给出主属性的**保留组/丢弃组**(PropId)，这里拿面板第一行主属性去比：
        返回 `{"prop": 名, "prop_id": id, "state": "ok"|"off"|"other"|"unknown", "plan": {...}}`。
        `other` = 官方两组都没列(合法但未表态)。无生成物/该套装无方案/读不到主属性 → None
        (调用方不加该字段, 旧报告与离线重放不受影响)。
        """
        if not main_props or cost not in (1, 3, 4):
            return None
        gd = load_gamedata()
        plan = (((gd or {}).get("sets") or {}).get(set_name) or {}).get("plan", {}).get(str(cost))
        if not plan:
            return None
        names = gd.get("main_prop_names") or {}
        raw = str(main_props[0][0])
        # 最长优先: `暴击伤害` 先于 `暴击`; OCR 前缀污染(`X攻击`)不影响子串命中
        key = max((k for k in names if k in raw), key=len, default=None)
        if key is None:
            return {"prop": raw, "prop_id": None, "state": "unknown", "plan": plan}
        pid = names[key]
        if pid in plan.get("lock", []):
            state = "ok"
        elif pid in plan.get("discard", []):
            state = "off"
        else:
            state = "other"
        return {"prop": key, "prop_id": pid, "state": state, "plan": plan}

    @staticmethod
    def _pair_props(properties, values):
        """按 y 坐标(相对行序, 分辨率无关)配对待属性名和数值, 返回 [(name, value_str), ...].
        先对两侧按 y 排序: OCR 返回顺序不保证有序, 不排序则"前 2 行=主属性"等行序语义会错。

        **一直用"最近邻 + 未用集合"**(贪心), **不要**改成"数量相等时按行序 zip":
        rep7 的 #136/#137 就是反例 —— 面板是 +20/4 词条, 技能描述行被挤进了 detail 区(多一个**名**),
        同时 OCR 把 `COST 3` 拆成两个框、裸 `3` 被当成**值**(多一个值), 名/值数量**凑巧相等**,
        zip 于是把整列错开一格(冷凝 25.2 → 记成 3.0, 主属性/词条全错; 见 CHANGELOG 补记 81)。
        贪心在这种情况下是对的: 每个名都拿离自己最近的值, 多出来的噪声值落到尾部噪声行。
        """
        paired = []
        unmatched = sorted(values, key=lambda v: v.y)
        for prop in sorted(properties, key=lambda p: p.y):
            v_text = "0"
            if unmatched:
                closest = min(unmatched, key=lambda v: abs(prop.y - v.y))
                v_text = closest.name
                unmatched.remove(closest)
            paired.append((prop.name, v_text))
        return paired

    def read_cost_badge(self) -> int | None:
        """COST 角标**单区放大重读**(全屏 1× 漏检时的兜底): 只截 `_COST_ROI` 放大 `_COST_UPSCALE` 倍再 OCR。

        为什么需要: 数字是小字, 全屏 OCR 有时**整个数字框都检不出来**(实测 20261008 那批 27/135 只剩
        `COST` 标签; 用保存的面板截图复跑可复现)。只读这一小块放大后 27/27 都能读回。
        代价只在 1× 没读到时才发生(通常 <0.3s)。
        """
        frame = self.frame
        if frame is None:
            return None
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = _COST_ROI
        roi = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        if roi.size == 0:
            return None
        roi = cv2.resize(roi, None, fx=_COST_UPSCALE, fy=_COST_UPSCALE, interpolation=cv2.INTER_CUBIC)
        try:
            boxes = self.ocr(0, 0, 1, 1, frame=roi)
        except Exception as e:                     # noqa: BLE001 - OCR 失败不该让整轮评估崩掉
            logger.warning(f'COST 角标重读失败(忽略): {e}')
            return None
        for b in boxes or []:                      # 放大后常是 `COST 1` / `COST1`
            m = _COST_RE.search(str(getattr(b, 'name', '')))
            if m:
                return int(m.group(1))
        return parse_cost(boxes or [])             # 标签与数字仍是两个框 → 走同行规则

    @staticmethod
    def _main_props_like(paired_all) -> bool:
        """前 2 行里的第 1 行是不是**真主属性** —— 用来区分"+0 级面板根本没有主属性行"。

        +0 的面板只有 名字 / +0 / COST / `持有数量：N` / 声骸技能…；把 `持有数量` 当主属性，
        技能描述里的 `加成提升10.00%` 就会被当成一条词条，报告里出现"0 级却有 1 词条"的假记录
        （2026-11-19 report1 的 #145/#146）。判据 = 第 1 行归一化后能落在官方主属性取值网格上
        （与报告「数值可疑」用的是同一份数据）。**判不了就放行**：宁可多记一条，不要漏真声骸。
        """
        if not paired_all or len(paired_all) < 2:
            return False
        try:
            from src.echo_inventory import normalize_main_prop
            from src.echo_main_prop import value_grid
            n, v = paired_all[0]
            return bool(value_grid(normalize_main_prop(n, v, None, None), None))
        except Exception:                          # noqa: BLE001 - 判不了不要中断评估
            return True

    @staticmethod
    def level_box(texts):
        """从详情面板的 OCR 框里取等级 `+NN` 的那个框(y 最小、conf ≥ 0.6); 认不出 None。

        **为什么需要框而不只是数字**: 面板上的**套装图标**跟在等级文字右侧, 图标位置随文字宽度变
        (`+5` 比 `+25` 窄, 图标左移约 10px) → 图标裁剪必须锚定这个框(见 `icon_box_at_level`)。
        """
        best = None
        for b in texts or []:
            m = LEVEL_RE.match(str(getattr(b, 'name', '') or ''))
            if not m:
                continue
            try:
                conf = float(getattr(b, 'confidence', 1.0))
            except (TypeError, ValueError):
                conf = 1.0
            if conf < 0.6:
                continue
            try:
                y = float(getattr(b, 'y', 0) or 0)
            except (TypeError, ValueError):
                y = 0.0
            if best is None or y < best[0]:
                best = (y, b)
        return best[1] if best else None

    @staticmethod
    def parse_level(texts) -> int | None:
        """从详情面板的 OCR 框里取等级(`+25`/`+10`/`+5`/`+0`) → int; 认不出 None。

        等级是**固定表头**, 与名字/COST 一起恒在面板顶部 → 不受滚动影响, 是比"数词条"硬得多的信号。
        实测(2026-11-19 的 174 个面板读取): 126 个读出 `+NN`, 全部 conf ≥ 0.90, y 恒定在 144~149。
        取 **y 最小**的那个(名字右侧); OCR 有时会多吐一个孤立的 `+`(conf≈0.74), 它不匹配数字所以被忽略。
        """
        b = EnhanceEchoTask.level_box(texts)
        m = LEVEL_RE.match(str(getattr(b, 'name', '') or '')) if b is not None else None
        return int(m.group(1)) if m else None


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "批量强化声骸(游戏语言必须为简体/繁体中文)"
        self.description = "点击B进入背包, 在过滤器中选择需要强化的声骸, 并按照等级从0排序后开始."
        # 任务图标留空: 本项目自建 UI 不渲染任务的 icon/group_icon(引擎侧只给默认值), 留 None 后
        # task adapter 不再 import qfluentwidgets(耦合 P1, 见 docs/COUPLING.md §4)。
        self.icon = None
        self.group_name = "批量强化声骸"
        self.group_icon = None
        self.fail_reason = ""
        self.supported_languages = ["zh_CN", "zh_TW"]
        # 评估跑在 UI 自己的线程里(不是 executor 线程), task.disable() 打断不了它;
        # 用 threading.Event 让「停止」按钮能真正终止遍历(每格/每屏之间检查)。
        self._stop_event = threading.Event()
        self.default_config.update({
            '必须有双爆': True,
            '双爆出现之前必须全有效词条': True,
            '双爆总计>=': 13.8,
            '首条双爆>=': 6.9,
            '有效词条>=': 3,
            '第一条必须为有效词条': True,
            '有效词条': ['暴击', '暴击伤害', '攻击百分比', '攻击', '共鸣效率'],
            '成功后暂停': True,
            '强化策略': '渐进式',
            '当前套装': '通用',
            '启用评分模式': False,
            '最低得分>=': 32.0,
        })
        # 词条表唯一来源 = echo_set_templates.STAT_ORDER(与"套装配置"表格同序)
        self.config_type["有效词条"] = {'type': "multi_selection",
                                        'options': list(STAT_ORDER)}
        self.config_type['强化策略'] = {'type': "drop_down",
                                        'options': ['传统', '渐进式']}
        self.config_type['当前套装'] = {'type': "drop_down",
                                        'options': ['通用'] + get_all_set_names()}
        self.config_description = {
            '必须有双爆': '如果开启，声骸最终必须同时拥有暴击和暴击伤害。如果剩余孔位不足以凑齐双爆，则丢弃',
            '双爆出现之前必须全有效词条': '开启后，在暴击或暴击伤害词条出现之前，前面的所有词条必须都在有效词条列表中',
            '双爆总计>=': '当声骸同时存在暴击和爆伤时，需要满足 暴击 + (爆伤/2) >= 此数值',
            '首条双爆>=': '仅检查第一条出现的暴击或暴击伤害是否满足条件, 爆伤/2',
            '有效词条>=': '满级时需要的有效词条数量\n剩余孔位无法凑齐则提前丢弃',
            '第一条必须为有效词条': '如果开启，第一个副词条必须在有效词条列表中且符合数值要求，否则直接丢弃',
            '有效词条': '定义哪些属性被视为有效',
            '成功后暂停': '强化出符合条件的声骸时自动暂停任务并弹出通知，方便手动确认',
            '强化策略': '传统: 满级后一次判断\n渐进式: Lv5/10 首条在首核内即过(低权重套装可配 `_low_first` 要求前 N 档) → Lv15+ 走两线判定(达标线 A = 10×本只出现有效词条权重和; 基准线 B = 通用 6.5/11.5/17.5), 不及格即停',
            '当前套装': '在"套装配置"tab中管理词条和权重',
            '启用评分模式': '条分=档位值÷期望值×10×权重(期望=官方公示概率期望; 平均档=10分, 满档≈13.1~14.0): 暴击1.0/爆伤0.7/攻%等0.5/共效0.5/专伤0.4/固定三系0.25\n无效词条=0分',
            '最低得分>=': '传统模式满级5词条总分>=此值保留',
        }

    def _panel_has_name(self) -> bool:
        """详情面板顶部是否还有"名字行"（判面板有没有被滚走）。

        面板顶部的名字是 y < 0.28×帧高 的唯一中文行（见 read_detail）；被滚走后那里就空了。
        读合鸣效果后用它确认**面板已回顶**，否则下一只的 read_detail 会读不到名字。
        """
        try:
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            texts = self.ocr(0.66, 0.10, 0.995, 0.28)
            return any(len(re.findall(r'[\u4e00-\u9fff]', str(getattr(b, 'name', '') or ''))) >= 2
                       and 0 <= float(getattr(b, 'y', 0)) < fh * 0.28
                       for b in texts)
        except Exception:
            return True

    def _save_fail_frame(self) -> str:
        """把"当前抓到的画面"存到 logs/eval_fail_frame.png，供"检测不到网格"时自查。

        2026-11-18 实测的坑：工具没以管理员运行 → `bring_to_front` 被 UIPI 拒 → cmd 窗口一直
        盖在游戏上 → 这版截图（PrintWindow + BitBlt）抓到的是**遮挡窗口**（截图里是控制台）。
        光看"未检测到网格"猜不出来，存一张图最直观。
        """
        try:
            os.makedirs('logs', exist_ok=True)
            path = os.path.abspath(os.path.join('logs', 'eval_fail_frame.png'))
            frame = self.frame
            if frame is not None and getattr(frame, 'size', 0):
                # **不能裸 `cv2.imwrite`**: 它对非 ASCII 路径返回 False 且**不抛**(Windows 中文用户名
                # → %TEMP% / logs/ 就在中文目录下), 那样下面返回的路径就是假证据 —— 排查时打开的是
                # 一个不存在的文件。统一走 imwrite_unicode(见 src/echo_panel_shot 的说明)。
                if echo_panel_shot.imwrite_unicode(path, frame):
                    return path
                self.log_debug(f'保存失败画面失败: 写文件返回 False(路径含非 ASCII?): {path}')
        except Exception as e:                     # noqa: BLE001 - 存图失败不该掩盖原始错误
            self.log_debug(f'保存失败画面失败: {e}')
        return ''

    @staticmethod
    def _blank_panel_is_zero_level(level, paired_all) -> bool:
        """"读到面板但一条词条都没配上"时, 判它是**真 0 级**还是**这一格没读干净**。

        列表是按等级排序的(用户口径), 0 级件只会出现在尾部 → 中途的"0 词条"基本都是没读干净
        (面板还没刷新完 / 点到格子间隙 / OCR 只读到半个面板)。旧代码把两者一律当 0 级, 于是
        "连续 12 格 0 词条 = 到底"的判据会在列表中间误触发(2026-11-19 21:26 只扫到 43 条)。

        判据(任一成立 = 不是 0 级, 该计"失败"):
          ① 等级读到了且 ≥ +5 —— 有词条孔位却说没词条, 只能是没读出来;
          ② 前 2 行像真主属性 —— +0 面板**没有主属性行**, 有主属性就说明它至少 +5。
        两样都判不了(None + 不像主属性)才按 0 级放过(宁可跳过一个 0 级, 不要漏真件)。
        """
        if level is not None and int(level) >= 5:
            return False
        return not EnhanceEchoTask._main_props_like(paired_all)

    def reset_bag_view(self, presses: int = 2, wait: float = 0.9) -> None:
        """按 B 把背包**关掉再打开**, 让声骸列表回到默认状态(顶部 + 默认排序)。

        为什么(2026-11-19 用户口径): 背包的列表滚动位置是**跨轮保留**的 —— 上一轮停在列表下部,
        这一轮就从中间开始扫(实测 21:06 那次首格就在中部), 上面的件永远扫不到。
        别去"猜滚了多少格"做补偿: 关掉再打开 = 回顶, 与上一次停在哪无关。
        `presses=2`: 第一下关掉(或从别的界面退回), 第二下重新打开。
        开局若本来就在大世界(背包没开), 两下 B 会以"关闭"收尾 —— 由首屏空网格的兜底再补一下。
        """
        for _ in range(max(1, presses)):
            self.send_key('b', after_sleep=wait)
        self.log_info(f'复位背包: 按 {presses} 次 B 重新打开(声骸列表应回到顶部)')

    def resolve_set_name(self, echo_name: str, badge=None, effect_set=None,
                         effect_src: str = '', use_icon: bool = False,
                         icon_box=None) -> tuple[str, str]:
        """评估用: 声骸名 + 套装硬信号 → (套装名, 来源)。

        信号优先级(2026-11-20 现状):
        ① **详情面板「合鸣效果」区套装名明文**(`effect_set` + `effect_src='text'`): 最稳, 调用方逐只读;
           参数名沿用 effect_set(effect 原文兜底已停用, 只有旧报告/离线重放还会传 `effect`);
        ② **详情面板套装图标**(`use_icon=True` + `icon_box`): 等级文字右侧的小圆图标, 灰度 ZNCC
           与 37 套模板比对; **必须用 `icon_box_at_level` 的动态框**(固定框只对 +25 成立);
        ③ **卡片徽章环色**(`badge=(hue|None, ok)`): 名字多个候选时用环色过滤(85% 可唯一定位);
        ④ **名字候选**(config 套装在候选内则优先) → ⑤ config(评估=通用)。
        来源 'text'/'icon'/'hue'/'name'/'default' 记入报告, 便于离线核对。
        """
        cfg_set = self.config.get('当前套装', '通用')
        cands = get_sets_by_echo(echo_name)
        # 面板上**明写的套装名**(text)是地面真相：名字候选是"按 OCR 名字推的"，名字读错时它本身就是错的
        # —— 2026-11-19 实测 #95 `梦魔·咕咕河豚`(魇→魔) 候选推成 [凝夜白霜, 浮星祛暗]，面板明明写着
        # 息界同调之律(放开到 37 套才认到)，却被"必须在候选内"挡掉，最后退回候选首个凝夜白霜 → 套装判错。
        # 所以 text 一律采信；只有**效果原文覆盖率反查**(effect)这种模糊信号才要求落在候选内。
        if effect_set and ((effect_src or 'effect').startswith('text') or not cands or effect_set in cands):
            src = effect_src or 'effect'
            self.log_debug(f'[套装{src}] {echo_name} → {effect_set} (名字候选 {cands})')
            return effect_set, src
        icon_set, score, margin = (None, 0.0, 0.0)
        if use_icon:
            icon_set, score, margin = match_icon(self.frame, icon_box)
        if icon_set:
            corrected = f' — 名字候选 {cands} 由图标纠正' if cands and icon_set not in cands else ''
            self.log_debug(f'[套装图标] {echo_name} → {icon_set}'
                           f' (s1={score:.3f} margin={margin:.3f}){corrected}')
            return icon_set, 'icon'
        if len(cands) > 1 and badge is not None:
            narrowed = filter_by_set_hue(cands, badge[0], badge[1])
            if len(narrowed) == 1:
                self.log_debug(f'[套装环色] {echo_name} → {narrowed[0]}'
                               f' (候选 {cands} 按环色 {hue_group(badge[0])} 过滤)')
                return narrowed[0], 'hue'
            cands = narrowed            # 收窄后仍多义 → 继续走名字兜底(顺序按收窄结果)
        if cands:
            set_name = cfg_set if cfg_set in cands else cands[0]
            self.log_debug(f'[套装映射] {echo_name} → {set_name} (名字候选: {cands};'
                           f' 图标未达置信线 s1={score:.3f}/{MIN_SCORE} margin={margin:.3f}/{MIN_MARGIN})')
            return set_name, 'name'
        self.log_debug(f'[套装映射] {echo_name} → {cfg_set} (名字未收录, 用默认)')
        return cfg_set, 'default'

    def quick_set_from_header(self, echo_name: str, badge, cands, icon_box):
        """快速模式: **不滚面板**能定的套装 —— 详情面板图标(固定表头) → 徽章环色收窄。

        为什么能省时间: 图标在固定表头、等级 `+NN` 右侧, 与面板滚动位置无关。report6 的 139 张
        真机面板回归: top-1 **99.3%**(138/139)、置信闸内 **100%**(123/123), 而滚面板读合鸣效果明文
        实测 1.41s/步、平均 2.8 步/只(整轮 20.2 分钟里占 **9.3 分钟**)。见
        `tools/analysis/icon_accuracy_report.py` / `panel_scroll_time.py`。

        返回 `(套装名, 来源)`; **None = 两个信号都不够**, 调用方去滚面板读明文(低置信件才付这笔时间)。
        精确模式(`config['套装精确模式']`)不走这里 —— 那条路总是读明文。
        """
        icon_set, score, margin = match_icon(self.frame, icon_box)
        if icon_set:
            note = f' — 名字候选 {cands} 由图标纠正' if cands and icon_set not in cands else ''
            self.log_info(f'[套装图标] {echo_name} → {icon_set} '
                          f'(s1={score:.3f} margin={margin:.3f}, 不滚面板){note}')
            return icon_set, 'icon'
        cands = list(cands or [])
        if len(cands) > 1 and badge is not None:
            narrowed = filter_by_set_hue(cands, badge[0], badge[1])
            if len(narrowed) == 1:
                self.log_info(f'[套装环色] {echo_name} → {narrowed[0]}'
                              f' (候选 {cands} 按环色 {hue_group(badge[0])} 过滤, 不滚面板)')
                return narrowed[0], 'hue'
        self.log_debug(f'[套装快速] {echo_name} 图标未达置信线'
                       f'(s1={score:.3f}/{MIN_SCORE} margin={margin:.3f}/{MIN_MARGIN}) → 滚面板读明文')
        return None

    def request_stop(self):
        """UI「停止」调用: 置停止事件, evaluate_only 在每格/每屏之间检查后退出。"""
        self._stop_event.set()

    def stop_requested(self):
        return self._stop_event.is_set()

    def reset_stop(self):
        """开始新一轮评估前清掉上一次的停止标记(在启动线程前调用, 避免和「刚开始就停止」竞争)。"""
        self._stop_event.clear()

    def evaluate_only(self, on_done=None):
        """
        评估模式 v2: 遍历背包声骸(每行6格) — 点格子→读右侧详情→评分记录→指纹去重→滚屏→到底结束。
        0 词条(全新0级/列表尾) 即认为到底, 结束。
        完成后调用 on_done(json_path, screenshot_dir)。
        """
        import json as _json, tempfile, shutil

        stopped = False            # 用户点「停止」→ 不生成报告, 直接收尾
        results: list[dict] = []
        evaluated = 0
        # 评估链自己的计数器(U-03): 运行页状态卡以前读的是**强化**的 成功/失败/得分, 评估跑 12 分钟
        # 也一直显示「成功: 0 / 失败: 0 / 得分: -」。评估的语义不同(只读遍历), 单独给三个键:
        #   评估数量 = 已记录只数(每记录一只写一次, 见下方 info_set)
        #   评估失败 = 点了却读不到属性的格数(_register_fail 里累加; 与"重复"区分开)
        #   评估结束原因 = 为什么停(0级尾部/到底/受阻/用户停止), 写进状态卡便于事后核对
        self.info_set('评估数量', 0)
        self.info_set('评估失败', 0)
        self.info_set('评估结束原因', '')
        tmp_dir = tempfile.mkdtemp(prefix="okecho_eval_")
        ss_dir = os.path.join(tmp_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        # 网格角标 OCR 区 / 右侧详情面板区。所有坐标均用归一化比例(除以帧宽高), 分辨率无关;
        #   1920x1200 帧换算参考: 名字 y≈0.10, COST y≈0.21, 主属性 y≈0.37/0.42, 词条 y≈0.45..0.61(第5条),
        #   "声骸技能"行 y≈0.62 由 read_detail 按行过滤; "前 2 行=主属性"是相对行序判断, 不依赖帧高
        grid_box = GRID_BOX
        detail_box = (0.66, 0.10, 0.995, 0.635)
        # 找套装要读**整块**详情面板(含最下面的合鸣效果区) —— `detail_box` 只到 0.635，
        # 套装名在面板下半截，会漏。**归一化比例**(self.ocr 的入参口径; 别传像素, 见 _effect_box_px)
        EFFECT_BOX = (0.66, 0.08, 0.995, 0.95)

        # 点击点必须落在**网格区内**(留 `CLICK_INSET` 边): 布局模型给出的边缘格、以及"换行线另一侧"
        # 的重试点都可能落到网格外 —— 背包两侧/底部是"整理·筛选·培养"这类按钮, 点到就跳去别的功能界面
        # (2026-11-19 用户现场: 中途进入游戏其他功能界面)。
        def clamp_click(x, y):
            return clamp_to_grid(x, y, grid_box)

        seen_sigs = set()          # 已处理声骸的去重签名(名字+全行档位值, 防滚动重叠漏拦)
        seen_stat_sigs = set()     # 只按属性行(不含名字)的去重签名: OCR 名字抖动(无常凶驾/无常冈驾)时防重复记录
        last_sig = None            # 上一次成功处理的详情全量签名(判点选未切换)
        no_new_screen = 0          # 连续滚动后无新格的次数 → 到底
        empty_scan = 0             # 网格区连续扫描为空的次数 → 真到底(0级角标 +0 也能被识别, 空=列表底)
        stop_all = False           # 到底 / 0 级尾部 → 正常收尾并输出报告
        zero_screens = 0           # 连续"整屏全是 0 词条"的屏数(到 ZERO_TAIL_SCREENS 收工)
        # 连续 3 整屏 0 词条(≈90 格)才认"进了 0 级段"。单屏/两屏都不够 —— 0 级件是按套装夹在列表
        # 中间的(2026-11-19 21:26 那次第 4 屏只有 13 个 0 级格, 旧版"连续 12 格"当场把 43 条当成了到底)。
        ZERO_TAIL_SCREENS = 3
        # ── 滚动调参(2026-11-14 真机实测后定的量) ────────────────────────────
        SCROLL_TARGET_ROWS = 3.0    # 每次滚 3 行(可见 5 行 → 留 ~2 行重叠, 滚过头也还有 1 行缓冲)
        SCROLL_SETTLE_STEP = 0.15   # 位移采样间隔(动画期间轮询)
        SCROLL_SETTLE_TIMEOUT = 3.0  # 等画面静止的最长时间(真机 ease-in 动画约 1s 收尾)
        SCROLL_STILL_RATIO = 0.02   # 相邻两帧变化像素占比 < 此值 = 画面静止(动画结束)
        SHIFT_DIFF_OK = 18.0        # 对齐残差 ≤ 此值才认为位移可信
        # 开局滚轮标定(2026-11-19): 先用 6 格小步滚一次, 用**行线位移**量真实 px/格。
        # 为什么必须标定: 图像相关在这台机器上残差常年 27~34(永远"不可信") → px/格 一直停在默认 8,
        # 而实测 ≈15 → 每次请求 2 行实际滚 3~4 行, 整行被跳过(43/146 的根源)。
        SCROLL_PROBE_NOTCHES = 6    # 标定用的小步(位移 <1 个行距 → 没有周期歧义)
        SCROLL_LINE_COST_OK = 6.0   # 行线匹配的中位误差 ≤ 此值(像素)才认这次测量
        SCROLL_PAGE_FRACTION = 0.6  # 每次滚**一页的 60%**(4 行页 → 2.4 行; 5 行页 → 3 行)
        SCROLL_CHANGE_MIN = 0.12    # 画面变化占比 < 此值 = 什么都没发生(只有悬停/选中框)
        SCROLL_FIRST_ROWS = 2.5     # 首滚上限(px/格还没实测过, 保守一点, 漏行比多滚贵)
        SCROLL_SAFETY = 0.95        # 距离打 95 折发送: 欠滚可由补滚补齐, 过滚会整行漏
        SET_PANEL_STEP = 4          # 找套装时每次只滚 4 格(小步: 大步会一步跨过目标文本)
        SET_PANEL_FIRST_STEP = 8    # 但第一步放大: 主词条区肯定没有套装名, 先跳过那一段
        SET_PANEL_MAX_STEPS = 24    # **只是安全上限**(8+23×4=100 格); 真正的"到底"判定是画面不再变化
        PANEL_UP_STEP = 8           # 回顶首步; 之后翻倍(8→16→32→64), 只为少滚几次
        PANEL_UP_MAX_STEP = 64      # 单次最大格数
        PANEL_UP_MAX_ITERS = 8      # 安全上限(8+16+32+64+… 早超过任何面板的实际长度)
        PANEL_MOVE_RATIO = 0.02     # **端点判据**: 滚一下再看画面变化占比是否过线(= 有没有动)

        grid_pitch = {'row': None, 'col': None}   # 上一屏的列/行间距(像素), 本屏角标漏检时用于推断
        layout_model = None      # 网格布局模型(比例): 首屏标定后跨屏复用, 后续屏幕只需行检测
        # 滚轮距离模型: px/格 随窗口缩放(8.0 是 1920 宽帧的实测值)
        scroll_model = echo_grid.ScrollModel(
            frame_width=float(getattr(self.executor.method, 'width', 0) or 1920.0))
        scroll_fail = 0          # 连续滚动受阻次数(>=2 中止, 绝不空转)
        screens_done = 0         # 已扫完的屏数(首屏"0 重复"是正常的, 守卫要跳过它)
        back_steps = 0           # 本屏"滚过头"后的回滚次数(每屏最多 2 次, 防来回拉锯)
        panel_dirty = False      # 找套装后没回顶(滚动条是共用的) → 读下一格前先回顶
        # **不要按声骸名缓存套装**: 同名不同件可以属于不同套装(格洛犸图 → 长路启航之星/雪落无声之愿),
        # 按名字复用会把第一只读到的套装套给所有同名件(2026-11-20 report4 #21/#23/#24 实测)。
        # 多候选的名字一律逐只读面板(见下方 stats 分支)。
        click_fail = 0           # 连续"点了却读不到属性"的格数(到 click_fail_stop 就中止)
        click_fail_stop = 6      # 连续这么多格"点了却读不到属性"就中止(一整行; 用户口径: 计入失败)
        click_fail_total = 0     # 全场"点了没读到属性"的格数(报告里可查)
        bag_retry_done = False   # 开局 B×2 后仍空网格 → 补按一次 B(开始时可能人在大世界)
        resynced = False         # 连续点空时"复位背包重扫"用过没有(只做一次, 防来回拉锯)
        stop_reason = ''         # 结束原因(写进"评估完成"那行, 免得只看到一个条数不知道为啥停)
        shot_fail_warned = False # 截图落盘失败只警告一次(非 ASCII 路径下每只都会失败, 刷 160 条没意义)

        # ── debug 数据集: 每格存 全屏原图/ROI框叠图 + detail/grid/count 区域裁剪, 每次 OCR 结果
        #    记入 ocr_text.txt —— 离线核对坐标与 OCR 输入输出, 无需重开云游戏。
        #    输出目录 logs/eval_debug/<时间戳>/, 独立于报告临时目录, 不随报告删除(约1GB/200声骸)。
        dbg_dir = None
        dbg_no = 0
        if SAVE_DEBUG_DATASET:   # 见模块级开关注释(默认关, 避免 GB 级磁盘占用)
            dbg_dir = os.path.join('logs', 'eval_debug', time.strftime('%Y%m%d_%H%M%S'))
            os.makedirs(dbg_dir, exist_ok=True)

        # ── 面板滚动数据集(默认开): 只对"要滚面板找套装"的声骸, 每步存裁剪 + OCR 行, 并拼长图。
        #    一次真机跑 → 离线重放(tools/analysis/replay_panel_scroll.py), 不用重开游戏。
        #    **目录懒创建**: 一轮里没有任何件需要滚面板时不留空目录(2026-11-19 几个空目录就是这么来的)。
        panel_dbg_dir = (os.path.join('logs', 'panel_debug', time.strftime('%Y%m%d_%H%M%S'))
                         if SAVE_PANEL_DATASET else None)
        panel_dir_ready = False

        def _ensure_panel_dir():
            nonlocal panel_dir_ready
            if not panel_dbg_dir or panel_dir_ready:
                return panel_dir_ready
            try:
                os.makedirs(panel_dbg_dir, exist_ok=True)
                panel_dir_ready = True
                self.log_info(f'面板数据集目录: {os.path.abspath(panel_dbg_dir)}'
                              f' (可离线重放: python tools/analysis/replay_panel_scroll.py)')
            except Exception as e:                      # noqa: BLE001
                self.log_debug(f'面板数据集目录创建失败: {e}')
            return panel_dir_ready

        def panel_dbg_step(tag, step, notches, texts, crop):
            """存一步: 面板裁剪 PNG + 该步 OCR 行(文本/坐标/置信度)。写失败不影响评估。"""
            if not _ensure_panel_dir():
                return
            try:
                echo_panel_shot.imwrite_unicode(
                    os.path.join(panel_dbg_dir, f'{tag}_s{step:02d}.png'), crop)
                rec = {
                    "kind": "step", "tag": tag, "step": step, "notches": notches,
                    "texts": [{"name": str(getattr(b, 'name', '') or ''),
                               "x": int(getattr(b, 'x', 0)), "y": int(getattr(b, 'y', 0)),
                               "w": int(getattr(b, 'width', 0)), "h": int(getattr(b, 'height', 0)),
                               "conf": round(float(getattr(b, 'confidence', 0) or 0), 3)}
                              for b in (texts or [])],
                }
                with open(os.path.join(panel_dbg_dir, 'panel_ocr.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(_json.dumps(rec, ensure_ascii=False) + '\n')
            except Exception as e:                      # noqa: BLE001 - 落盘失败不该中断评估
                self.log_debug(f'面板数据集写入失败: {e}')

        def panel_dbg_summary(tag, echo_idx, echo_name, cands, frames, notches, best, restore_ok):
            """存这一只的结论 + 长图 + 回顶证明图(用户要的"每个声骸滑到底后回到最上"的证据)。"""
            nonlocal panel_dbg_restore_fail
            if not _ensure_panel_dir():
                return
            try:
                long_path, used, long_h = echo_panel_shot.stitch_and_save(
                    os.path.join(panel_dbg_dir, f'{tag}_long.png'), frames)
                box = _effect_box_px()
                frame = self.frame
                if frame is not None and getattr(frame, 'size', 0):
                    echo_panel_shot.imwrite_unicode(
                        os.path.join(panel_dbg_dir, f'{tag}_top.png'),
                        frame[int(box[1]):int(box[3]), int(box[0]):int(box[2])])
                rec = {
                    "kind": "summary", "tag": tag, "echo": echo_idx, "name": echo_name,
                    "cands": list(cands or []), "steps": len(frames), "notches": notches,
                    "found": best[0], "src": best[3], "restore_ok": bool(restore_ok),
                    "long": os.path.basename(long_path) if long_path else '',
                    "long_frames": used, "long_h": long_h,
                }
                if not restore_ok:
                    panel_dbg_restore_fail += 1
                with open(os.path.join(panel_dbg_dir, 'panel_ocr.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(_json.dumps(rec, ensure_ascii=False) + '\n')
            except Exception as e:                      # noqa: BLE001
                self.log_debug(f'面板长图写入失败: {e}')

        panel_dbg_restore_fail = 0     # 回顶失败次数(报告里可查; 数据集里每只都有 restore_ok)

        def dbg_ocr(label, texts):
            """记录一次 OCR 的输入区域标签 + 全部文本行(文本/坐标/置信度)到 ocr_text.txt"""
            if not dbg_dir or not texts:
                return
            with open(os.path.join(dbg_dir, 'ocr_text.txt'), 'a', encoding='utf-8') as f:
                for b in texts:
                    f.write(f'[{label}] {getattr(b, "name", "")!r} x={b.x} y={b.y} '
                            f'w={b.width} h={b.height} conf={getattr(b, "confidence", 0):.2f}\n')

        def dbg_shot(label):
            """存当前帧: 全屏PNG + 三个 ROI 框(红=detail,绿=grid,蓝=count)叠加PNG + 各区域裁剪PNG"""
            nonlocal dbg_no
            if not dbg_dir:
                return
            fw = int(getattr(self.executor.method, 'width', 0) or 1920)
            fh = int(getattr(self.executor.method, 'height', 0) or 1200)
            dbg_no += 1
            tag = f'{dbg_no:04d}_{label}'
            frame = self.frame
            if frame is None or frame.size == 0:
                return
            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)   # 灰度帧转彩色, 否则 rectangle 画不出
            # 落盘统一走 imwrite_unicode(裸 cv2.imwrite 对非 ASCII 路径静默失败, 见 _save_fail_frame)
            echo_panel_shot.imwrite_unicode(os.path.join(dbg_dir, f'{tag}_full.png'), frame)
            boxed = frame.copy()
            for box, color in ((detail_box, (0, 0, 255)), (grid_box, (0, 255, 0))):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                cv2.rectangle(boxed, (x1, y1), (x2, y2), color, max(2, fw // 600))
            echo_panel_shot.imwrite_unicode(os.path.join(dbg_dir, f'{tag}_boxes.png'), boxed)
            for name, box in (('detail', detail_box), ('grid', grid_box)):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                echo_panel_shot.imwrite_unicode(os.path.join(dbg_dir, f'{tag}_{name}.png'),
                                                frame[y1:y2, x1:x2])

        def ocr_conf(box):
            try:
                return float(getattr(box, 'confidence', 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        def ocr_quality(texts):
            """低置信重读的取舍: 先比"达到 0.85 的框数", 再比这些框的置信度和。"""
            good = [ocr_conf(b) for b in (texts or []) if ocr_conf(b) >= self.OCR_RETRY_CONF]
            return len(good), sum(good)

        def _log_grid_geometry(cols, rows, row_pitch):
            """本屏网格几何只在**变化时**记一条 INFO —— 排查"点歪/漏格"时这是第一手证据。"""
            sig = f'{cols}x{rows}@{row_pitch:.0f}'
            if grid_pitch.get('sig') == sig:
                return
            grid_pitch['sig'] = sig
            self.log_info(f'本屏网格: {cols} 列 × {rows} 行 (行距 {row_pitch:.0f}px)')

        def badge_hue_at(nx, ny):
            """格子左下角的套装徽章 → `(hue|None, ok)`（新 UI 下唯一的套装信号）。

            位置由**布局比例**算: 徽章中心 ≈ (点击点 x - 0.235 列距, 行线 y - 0.116 行距) ——
            实测 1254 帧列距 115/行距 138 → 偏移 (-27, -16) px, 与行线独立于滚动相位。
            """
            if layout_model is None:
                return None, False
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            col_px = layout_model.col_pitch_ratio * fw
            row_px = layout_model.row_pitch_ratio * fw
            dy_ratio = grid_pitch.get('dy')
            if dy_ratio is None:
                dy_ratio = 0.08
            cx = nx * fw - 0.235 * col_px
            cy = ny * fh - (dy_ratio + 0.116) * row_px
            return badge_hue(self.frame, cx, cy, 0.101 * row_px)

        def _effect_box_px():
            """寻套装文本用的区域**像素**矩形（给 `frame_change_ratio` 用）。

            ⚠ **单位坑(2026-11-19 真机抓到)**: `self.ocr(*box)` 要的是**归一化比例**，而这里返回的是
            **像素**；把像素直接喂给 ocr 会让 `relative_box` 再乘一次帧宽高 → 裁出 (0,0) 的空图 →
            OCR 永远返回空 → "合鸣效果区套装名"这条链在真机上**一个字都没读到过**(一路滚到底还回不去)。
            所以 OCR 一律用 `EFFECT_BOX`(归一化)，像素串只给图像比较类函数。
            """
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            return (EFFECT_BOX[0] * fw, EFFECT_BOX[1] * fh, EFFECT_BOX[2] * fw, EFFECT_BOX[3] * fh)

        def _panel_scroll(notches):
            """把光标放到面板中部并滚 notches 格（负=向下）。返回 True=已发送。"""
            dm = self.executor.device_manager
            hwnd_window = getattr(dm, 'hwnd_window', None)
            if hwnd_window is None or not hwnd_window.hwnd:
                return False
            try:
                import ctypes
                import win32gui
                from pynput.mouse import Controller
                hwnd_window.bring_to_front()
                self.sleep(0.10)
                fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
                fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
                target = getattr(hwnd_window, 'top_hwnd', None) or hwnd_window.hwnd
                ax, ay = win32gui.ClientToScreen(target, (int(fw * 0.83), int(fh * 0.55)))
                ctypes.windll.user32.SetCursorPos(int(ax), int(ay))
                self.sleep(0.06)
                Controller().scroll(0, int(notches))
                return True
            except Exception as e:
                self.log_debug(f'滚详情面板失败: {e}')
                return False

        def _panel_settled(prev, box, timeout=1.0):
            """等**面板滚动动画停稳**，返回稳定后的帧。

            真机上滚动是 ease-in 动画（网格那边实测 0.8s 才停），滚完立刻比帧会一直判"还在动"
            —— 2026-11-19 17:00 那次 5 次"回顶失败"就是这么来的（其实早到顶了，只是还在动画里）。
            判据同 `_wait_still`: 相邻两帧差异 < `PANEL_MOVE_RATIO` 连续两次。
            """
            last = prev
            still = 0
            t0 = time.time()
            while time.time() - t0 < timeout:
                self.sleep(0.10)
                cur = self.frame
                if echo_grid.frame_change_ratio(last, cur, box) < PANEL_MOVE_RATIO:
                    still += 1
                    if still >= 2:
                        return cur
                else:
                    still = 0
                last = cur
            return last

        def restore_panel_top():
            """把详情面板滚回顶部 —— 判据 = **画面不再变化**(与"滚了几步/多少格"无关)。

            2026-11-19 真机修正(之前是假判据)：面板的**名字 / +25 / COST 是固定表头** —— 四个滚动位置上
            顶部 0~30% 逐像素不动，"名字可见 ⇒ 已回顶"**永远成立**（数据集里 `_top.png` 与最后一步
            逐字节相同就是铁证）。现在只看画面：滚一下 → 等动画停稳 → 比帧；**滚了但画面没变 = 到顶**。
            步长翻倍(8→16→32→64)只为少滚几次，判定与步长/格数无关；长面板(实测滚过 80 格)也够。
            """
            box = _effect_box_px()
            before = self.frame
            advance = PANEL_UP_STEP
            still = 0
            for _ in range(PANEL_UP_MAX_ITERS):
                if not _panel_scroll(advance):
                    return False
                after = _panel_settled(before, box)
                moved = echo_grid.frame_change_ratio(before, after, box) >= PANEL_MOVE_RATIO
                before = after
                if not moved:
                    still += 1
                    if still >= 2:      # 连续两次滚不动 = 已经到顶
                        return True
                    continue
                still = 0
                advance = min(advance * 2, PANEL_UP_MAX_STEP)
            return False


        def read_set_by_effect(cands, echo_name=''):
            """滚详情面板找套装：**套装名文字优先**（合鸣效果区每条都会写套装名），
            其次按合鸣效果原文反查；以 **OCR 标题锚点** 判"到位没到位"，不用固定格数/像素静止。

            用户实测（2026-11-18 三张截图）：面板往下依次是 声骸技能描述 → 合鸣效果，
            合鸣效果区第一行就是 `雪落无声之愿` 这样的套装名（2/5 件套各一行），长描述在下面。
            所以"看到 合鸣效果 标题 + 匹配到名字"就是成功；两者都没有就继续滚（上限 6×10 格）。
            """
            best = (None, 0.0, 0.0, '')   # (套装名, 相似度1, 次优2, 来源) —— 来源 'text'/'effect' 要一路传到报告
            total = 0
            box = _effect_box_px()
            prev = self.frame
            still = 0
            seen_heading = None
            restore_ok = True
            frames = []                   # 每一步的面板裁剪(存数据集 + 拼长图)
            tag = ''
            if panel_dbg_dir:
                echo_idx = evaluated + 1
                safe = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '_', echo_name or 'x')[:24]
                tag = f'{echo_idx:03d}_{safe}'

            def _name_own_line(texts, name):
                """套装名是否独占一行（实现见 `echo_set_templates.name_own_line`，离线重放共用）。"""
                return name_own_line(texts, name)

            try:
                for step in range(SET_PANEL_MAX_STEPS):
                    advance = SET_PANEL_FIRST_STEP if step == 0 else SET_PANEL_STEP
                    if not _panel_scroll(-advance):
                        break
                    total += advance
                    cur = _panel_settled(prev, box)     # 等滚动动画停稳再 OCR/比帧(0.16s 会取到糊帧)
                    texts = self.ocr(*EFFECT_BOX)
                    dbg_ocr(f'effect{step}', texts)
                    if panel_dbg_dir:
                        # 面板裁剪(与 OCR 的 EFFECT_BOX 同一块) —— 离线重放/长图都用它
                        frames.append(cur[int(box[1]):int(box[3]), int(box[0]):int(box[2])].copy())
                        panel_dbg_step(tag, step, total, texts, frames[-1])
                    if has_heading(texts, '合鸣效果'):
                        seen_heading = step
                    named, how = match_set_text(texts, cands)
                    if not named and cands:
                        # 候选是"按名字推的"，名字 OCR 错字会把真套装排除在外；
                        # 面板上写的是**明文套装名**，所以放开到 37 套再认一次是安全的。
                        named_all, how_all = match_set_text(texts)
                        if named_all:
                            named, how = named_all, how_all + '/all'
                    if named and (seen_heading is not None or _name_own_line(texts, named)):
                        self.log_info(f'[套装] 合鸣效果区读到套装名: {named}({how}, 滚 {total} 格)')
                        # how = 'text'(精确) / 'text-lcs'(容错) / 带 '/all'(放开到 37 套) → 统一记 text
                        best = (named, 1.0, 0.0, 'text')
                        break
                    named = None
                    # **效果原文兜底已停用**(2026-11-20 用户口径: 宁缺毋滥) —— 它原本是"套装名明文"
                    # 链路没打通时的唯一信号; 现在明文(含 text-lcs / 放开到 37 套)已足够, 而效果原文
                    # 是长文本覆盖率匹配, 会把技能描述里的"热熔伤害"当成套装效果(report5: 6 次 effect
                    # 里 4 次是绿熔蜥的误判)。保留注释备查; 需要看效果匹配结果用 check_set_panel.py。
                    # cand, s1, s2 = match_set_effect(texts, cands)
                    # if cand and seen_heading is not None:
                    #     self.log_info(f'[套装] 按合鸣效果文本命中: {cand} '
                    #                   f'(覆盖 {s1:.2f} / 次优 {s2:.2f}, 滚 {total} 格)')
                    #     best = (cand, s1, s2, 'effect')
                    #     break
                    if echo_grid.frame_change_ratio(prev, cur, box) < SCROLL_STILL_RATIO:
                        still += 1
                        if still >= 2:                 # 到底了仍没读到 → 交给环色/名字兜底
                            self.log_debug(f'面板到底(滚 {total} 格)仍未读到套装信息')
                            break
                    else:
                        still = 0
                    if seen_heading is not None and step - seen_heading >= 2:
                        # 已经看到「合鸣效果」标题又滚了两步仍匹配不到 → 别空转
                        self.log_debug(f'看到合鸣效果标题但仍未命中(滚 {total} 格), 停止')
                        break
                    prev = cur
            finally:
                if total:
                    # 滚过就必须回顶：词条区在面板中间(30~80%)，面板停在下面 → 下一只读不到词条
                    nonlocal panel_dirty
                    panel_dirty = True
                    if restore_panel_top():
                        panel_dirty = False
                    else:
                        restore_ok = False
                        self.log_warning(f'详情面板没回顶(上滚 {PANEL_UP_MAX_ITERS} 次画面还在动) '
                                         f'— 下一只会先回顶再读')
                if panel_dbg_dir:
                    panel_dbg_summary(tag, evaluated + 1, echo_name, cands, frames, total,
                                      best, restore_ok)
            if not best[0]:
                # 让"套装到底认没认出来"在日志里可见(用户 2026-11-19 提的: 看不出来)
                self.log_info(f'[套装] 面板没读到套装信息(滚 {total} 格) → 回退环色/名字')
            return best

        def _register_fail(nx, ny, why='', rc=''):
            """计一格"点了却没读到词条"; 返回 True = 本屏到此为止(已复位背包 / 该中止)。

            两处调用: ①根本没读到属性 ②面板换了但一条词条没配上(等级/主属性说它该有)。
            连续 `click_fail_stop` 格 → 先复位背包重扫一次(疑似被点进别的功能界面), 再失败才中止。
            """
            nonlocal click_fail, click_fail_total, miss, stop_all, screen_invalid
            nonlocal resynced, stop_reason
            click_fail += 1
            click_fail_total += 1
            miss += 1
            self.info_incr('评估失败')      # U-03: 状态卡「失败: N」—— 只统计"点了没读到", 不含重复
            if why:
                # 读不干净的**面板**存一张(不是整屏): 下次复发能直接看到当时面板长什么样
                try:
                    os.makedirs('logs', exist_ok=True)
                    crop = self.box_of_screen(0.66, 0.10, 0.995, 0.635).crop_frame(self.frame)
                    echo_panel_shot.imwrite_unicode(os.path.join('logs', 'eval_fail_panel.png'), crop)
                except Exception:                  # noqa: BLE001 - 存图失败不影响评估
                    pass
            self.log_info(f'[失败] 格{(" " + rc) if rc else ""}({nx:.3f},{ny:.3f}) 点击后没读到属性{why} '
                          f'(本屏第 {miss} 格, 连续 {click_fail} 次)')
            if click_fail < click_fail_stop:
                return False
            if not resynced:
                # 一整行都点不出属性 = 屏幕已经不在声骸列表(中途被点进了别的功能界面, 或背包被关掉)
                # → 复位背包重扫一次, 而不是直接中止丢掉后面的件。
                resynced = True
                shot = self._save_fail_frame()
                self.log_warning(
                    f'连续 {click_fail} 格点击后都读不到属性 → 疑似被点进了别的功能界面, '
                    f'复位背包后重扫一次(已记录 {evaluated} 条)'
                    + (f'; 当时画面已存: {shot}' if shot else ''), notify=True)
                self.reset_bag_view(presses=2)
                click_fail = 0
                screen_invalid = True
                return True
            stop_reason = f'连续 {click_fail} 格点击失败'
            self.log_warning(f'连续 {click_fail} 格点击后都读不到属性, 评估中止'
                             f'(已记录 {evaluated} 条, 生成部分报告)', notify=True)
            stop_all = True
            return True

        def scan_grid():
            """OCR 网格区角标 → 聚行 → 按 6 列基准补全缺列(防 OCR 漏格), 返回完整网格点
            (nx, ny) 归一化列表, 按行从上到下、行内从左到右。全部按实际帧尺寸换算, 分辨率自适应。"""
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            row_tol = max(20.0, fh * 0.03)   # 行聚类容差(~1200帧→36px)
            col_gap = max(50.0, fw * 0.046)  # 列间距阈值(~1920帧→88px)
            # 扫描 ROI: 比点击区略宽(容下首/末列角标), 右侧不越过详情面板(挡掉面板自己的 +25)
            sx0, sx1 = max(0.0, 0.075 * fw), 0.655 * fw
            sy0, sy1 = 0.10 * fh, 0.90 * fh
            # 小窗口(如 1254x889)下 +25 只有 10~14px 高: 单次裁剪 OCR 只检出 5~14/30,
            # 还会把 +25 拆成 + 与 25 → 单次结果聚行聚列必然残缺(实测漏第一行/第一列、点到隔壁)。
            # ① 布局模型 + 行检测（最快、最稳）：列布局来自首屏标定的比例，行每屏重新取
            #    （滚动后相位会变）；行距突变/模型缺失时回到完整结构检测。
            nonlocal layout_model
            frame = self.frame
            rows, row_pitch = echo_grid.detect_row_lines(frame, (sx0, sy0, sx1, sy1))
            if layout_model is not None and rows and layout_model.matches(row_pitch, fw):
                cells_model = layout_model.cells(fw, rows)
                grid_pitch['row'] = row_pitch
                grid_pitch['dy'] = layout_model.click_dy_ratio
                grid_pitch['nrows'] = len(rows)
                _log_grid_geometry(layout_model.cols, len(rows), row_pitch)
                return [(mx / fw, my / fh) for mx, my in cells_model]
            # ② 完整结构标定：等级条顶边 → 行，金色亮段 → 列；成功则更新模型
            struct = echo_grid.detect_grid_structure(frame, (sx0, sy0, sx1, sy1))
            if struct:
                struct_cells = echo_grid.cells_from_structure(struct)
                if len(struct_cells) >= 20:
                    layout_model = echo_grid.GridModel.from_structure(struct, fw)
                    grid_pitch['row'] = struct['row_pitch']
                    grid_pitch['dy'] = struct.get('click_dy', 0.08)
                    grid_pitch['nrows'] = len(struct['rows'])
                    _log_grid_geometry(len(struct['cols']), len(struct['rows']),
                                            struct['row_pitch'])
                    return [(mx / fw, my / fh) for mx, my in struct_cells]
            # ③ 回退：两路 OCR 并集 + 拆框合并 + 等间距推断
            texts = list(self.ocr(*grid_box))
            dbg_ocr('grid', texts)
            try:
                texts += list(self.ocr(0, 0, 1, 1))
            except Exception as e:
                self.log_debug(f'全帧 OCR 失败(只用裁剪结果): {e}')
            marks = echo_grid.merge_badge_marks(texts, roi=(sx0, sy0, sx1, sy1))
            if not marks:
                return []
            cells = echo_grid.cells_from_marks(
                marks, (sx0, sy0, sx1, sy1),
                row_tol=row_tol, col_gap=col_gap,
                row_pitch_hint=grid_pitch['row'], col_pitch_hint=grid_pitch['col'])
            xs = sorted({int(round(x)) for x, _ in cells})
            ys = sorted({int(round(y)) for _, y in cells})
            grid_pitch['col'] = echo_grid.axis_pitch(xs) or grid_pitch['col']
            grid_pitch['row'] = echo_grid.axis_pitch(ys) or grid_pitch['row']
            self.log_debug(f'网格扫描: 角标 {len(marks)} 个 → {len(xs)} 列 × {len(ys)} 行')
            return [(mx / fw, my / fh) for mx, my in cells]

        def _grid_rect_px():
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            return (max(0.0, 0.075 * fw), 0.10 * fh, 0.655 * fw, 0.90 * fh)

        def _real_wheel(notches):
            """真实鼠标滚轮（SendInput）：先把窗口拉前、光标放到网格中心，保证命中。

            为什么需要它：PostMessage 的 WM_MOUSEWHEEL 不移动真实光标，UE 的 Slate 用真实光标做命中测试，
            本地窗口模式下会被忽略（2026-11-14 真机：首屏 30 条后列表不动）。
            """
            try:
                import ctypes
                import win32gui
                from pynput.mouse import Controller
                dm = self.executor.device_manager
                hwnd_window = getattr(dm, 'hwnd_window', None)
                if hwnd_window is None or not hwnd_window.hwnd:
                    return False
                hwnd_window.bring_to_front()
                self.sleep(0.15)
                target = getattr(hwnd_window, 'top_hwnd', None) or hwnd_window.hwnd
                ax, ay = win32gui.ClientToScreen(target, (int(self.width * 0.52), int(self.height * 0.5)))
                ctypes.windll.user32.SetCursorPos(int(ax), int(ay))
                self.sleep(0.08)
                Controller().scroll(0, -int(notches))
                return True
            except Exception as e:
                self.log_warning(f'真实鼠标滚轮失败: {e}')
                return False

        def _drag_scroll(pitch, rows=4):
            """拖拽兜底：网格下部按住向上拖 rows 行（真实鼠标，SendInput）。

            距离**故意限到 2.5 行**：拖拽带惯性，真机实测一次能滑 5~6 行（可见 5 行），
            而 5 行以上在 711px 视口里没有足够重叠 → 位移测不出来，漏行也发现不了。
            拖不够由 `scroll_grid` 的补滚闭环补齐。
            """
            rows = min(float(rows), 2.5)
            try:
                import win32gui
                from pynput.mouse import Button, Controller
                dm = self.executor.device_manager
                hwnd_window = getattr(dm, 'hwnd_window', None)
                if hwnd_window is None or not hwnd_window.hwnd:
                    return False
                hwnd_window.bring_to_front()
                self.sleep(0.15)
                target = getattr(hwnd_window, 'top_hwnd', None) or hwnd_window.hwnd
                sx, sy = win32gui.ClientToScreen(target, (int(self.width * 0.55), int(self.height * 0.72)))
                mouse = Controller()
                mouse.position = (sx, sy)
                self.sleep(0.08)
                mouse.press(Button.left)
                for step in range(1, 11):
                    mouse.position = (sx, sy - int(pitch * rows * step / 10.0))
                    self.sleep(0.03)
                mouse.release(Button.left)
                return True
            except Exception as e:
                self.log_warning(f'拖拽滚动失败: {e}')
                return False

        def _wait_still(rect, timeout=SCROLL_SETTLE_TIMEOUT):
            """等画面**停止变化**再返回这一帧（滚动动画的收尾）。

            **为什么不能只看位移读数**（2026-11-14 真机 16:21 那轮）：
            滚轮是 ease-in 动画 —— 前 0.5s 只走 0.2 行，之后才加速。旧判据"连续两次读数一致"
            在慢启动阶段就满足了 → 报"停稳 0.52s / +0.2 行"，实际最后走了 4~5 行。
            读数错 → 不校正 → 越滚越多 → 整行被跳过（那轮 113 只 / 应为 153）。
            这里改成看**相邻两帧的差异**：还在动就继续等，动了多久/动了多少都不影响判据。
            """
            prev = self.frame
            t0 = time.time()
            stable = 0
            while time.time() - t0 < timeout:
                self.sleep(SCROLL_SETTLE_STEP)
                cur = self.frame
                delta = echo_grid.frame_change_ratio(prev, cur, rect)
                prev = cur
                if delta < SCROLL_STILL_RATIO:
                    stable += 1
                    if stable >= 2:       # 连续两次"几乎不变"才算真停稳(防单次巧合)
                        return cur
                else:
                    stable = 0
                if self.stop_requested():
                    break
            self.log_debug(f'等静止超时({timeout:.1f}s): 画面一直在变(可能背景有动效), 用当前帧')
            return self.frame

        def _measure_shift(before, pitch, rect, expect_rows=None):
            """等滚动动画**停稳**再量位移 → (rows, diff, change_ratio, seconds)。

            判据同 `_wait_still`：看**相邻两帧**是否还在变，而不是看位移读数是否"稳定"
            （ease-in 动画的慢启动会让位移读数长时间停在很小的值上）。

            **量法优先用行线**(`row_shift_by_lines`)：图像相关在真机上残差 27~34(对不齐)，
            一旦只能靠它，px/格 就永远学不到、闭环也永远不纠。行线给 `expect_rows`(按发了几格估的)
            ±0.8 行窗口 → 既避开行线周期歧义，又比相关稳。行线不可信才退回相关。
            """
            t0 = time.time()
            prev = before
            rows, diff, change = 0.0, 1e9, 0.0
            stable = 0
            while True:
                self.sleep(SCROLL_SETTLE_STEP)
                frame = self.frame
                rows, diff = echo_grid.estimate_row_shift(before, frame, rect, pitch)
                change = echo_grid.frame_change_ratio(before, frame, rect)
                delta = echo_grid.frame_change_ratio(prev, frame, rect)
                prev = frame
                if delta < SCROLL_STILL_RATIO:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                if time.time() - t0 >= SCROLL_SETTLE_TIMEOUT or self.stop_requested():
                    self.log_debug(f'滚动静止超时({SCROLL_SETTLE_TIMEOUT:.1f}s), 用最后一次读数')
                    break
            if change >= SCROLL_CHANGE_MIN:
                lrows, lcost = echo_grid.row_shift_by_lines(
                    before, frame, rect, pitch, max_rows=max(1.2, (expect_rows or 1.0) + 1.0),
                    expect_rows=expect_rows)
                if lcost <= SCROLL_LINE_COST_OK and lrows > 0.02:
                    return lrows, lcost, change, time.time() - t0
            return rows, diff, change, time.time() - t0

        def scroll_up(rows=1.0):
            """向上回滚 rows 行 —— 只为"这次滚过头"时把跳过的行捞回来，不做精确测量。"""
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            pitch = max(20.0, (layout_model.row_pitch_ratio * fw) if layout_model else 0.11 * fw)
            notches = scroll_model.notches_for(rows, pitch)
            rect = _grid_rect_px()
            before = _wait_still(rect)
            if not _real_wheel(-notches):      # 负格数 = 向上
                return False
            _measure_shift(before, pitch, rect)   # 只为等动画停稳
            self.log_info(f'回滚: {notches} 格(向上, 捞回被跳过的行)')
            return True

        def scroll_grid(rows=SCROLL_TARGET_ROWS):
            """滚一屏（目标 rows 行）。返回 True=画面确实动了（哪怕没滚够）。

            2026-11-14 重写（真机三次"越滚越少/滚不动"，最终只收到 54/229）：
              ① 每种输入方式**单独测量**，动了就停 —— 旧版把「真实滚轮 → PostMessage → 拖拽」
                 一股脑全发出去，三次叠加能滚 6 行（可见 5 行）→ 中间整行被跳过；
              ② 测到**动画停稳**再读数（单次 0.6s 采样低估 8 倍）；
              ③ 距离**闭环**：不够补残余（最多 2 次），够了就停，绝不叠加；
              ④ "动了但量不出位移"单独识别，不再当"受阻"再叠一次输入。
            """
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            pitch = (layout_model.row_pitch_ratio * fw) if layout_model else 0.11 * fw
            pitch = max(20.0, pitch)
            # 一页 = **本屏检测到的行数 × 行距**(4/5 行随分辨率变, 6 列是常量)。
            # 滚动量按**页的比例**算, 不写死"3 行": 1440x900 只显示 4 行, 滚 3 行只剩 1 行重叠,
            # 一次偏差就跳行。留在页内的比例也决定了"滚完还剩几行重叠"。
            visible = int(grid_pitch.get('nrows') or 5)
            page_px = max(1.0, float(visible)) * pitch
            rows = max(1.0, min(float(rows), visible - 1.0, float(visible) * SCROLL_PAGE_FRACTION))
            self.log_debug(f'滚动规划: 本屏 {visible} 行 × {pitch:.0f}px = 一页 {page_px:.0f}px, '
                           f'目标 {rows:.1f} 行({rows / max(1, visible):.0%} 页)')
            rect = _grid_rect_px()
            before = _wait_still(rect)      # 先等上一屏的收尾动画停下来, 否则基准帧是糊的
            total = 0.0
            used = None
            # ── 开局标定: 6 格小步 → 行线位移 → 真实 px/格 ────────────────────────
            # 只在还没量过时做; 失败就保留默认值(宁可欠滚: 欠滚有去重兜底, 过滚整行漏)。
            if scroll_model.observations == 0 and SCROLL_PROBE_NOTCHES > 0:
                if _real_wheel(SCROLL_PROBE_NOTCHES):
                    after = _wait_still(rect)
                    moved, cost = echo_grid.row_shift_by_lines(before, after, rect, pitch,
                                                               max_rows=1.2)
                    change = echo_grid.frame_change_ratio(before, after, rect)
                    if cost <= SCROLL_LINE_COST_OK and moved > 0.03 and change >= SCROLL_CHANGE_MIN:
                        scroll_model.observe(SCROLL_PROBE_NOTCHES, moved * pitch, weight=1.0)
                        total, used, before = moved, '真实滚轮', after
                        self.log_info(f'滚动标定: {SCROLL_PROBE_NOTCHES} 格 → {moved:.2f} 行 '
                                      f'(≈{scroll_model.px_per_notch:.1f}px/格, 行线残差 {cost:.1f})')
                    else:
                        self.log_debug(f'滚动标定失败(位移 {moved:.2f} 行, 残差 {cost:.1f}), 先用默认值')
            # 首滚保守：px/格 还没实测过(默认值有 ±50% 误差)，先滚 ≤2.5 行再把残余补到目标。
            # 宁可多一屏，也不要第一次就滚过 5 行 —— 越过 5 行就没有重叠，漏行连发现都发现不了。
            first_scroll = scroll_model.observations == 0
            goal = min(rows, SCROLL_FIRST_ROWS) if first_scroll else rows
            for name in ('真实滚轮', 'PostMessage', '拖拽'):
                notches = scroll_model.notches_for(goal - total, pitch)
                if total <= 0.0:
                    # 首发送略欠一点（宁可下一次补，绝不一次过滚）：过滚会整行漏，欠滚有去重兜底
                    notches = max(scroll_model.min_notches, int(round(notches * SCROLL_SAFETY)))
                if name == '真实滚轮':
                    sent = _real_wheel(notches)
                elif name == 'PostMessage':
                    sent = True
                    try:
                        self.scroll_relative(0.52, 0.5, -notches)
                    except Exception as e:
                        self.log_debug(f'PostMessage 滚轮失败: {e}')
                        sent = False
                else:
                    sent = _drag_scroll(pitch, max(1, int(round(rows - total))))
                if not sent:
                    continue
                expect = notches * scroll_model.px_per_notch / max(1.0, pitch)
                moved, diff, change, secs = _measure_shift(before, pitch, rect, expect_rows=expect)
                if change < SCROLL_CHANGE_MIN:
                    self.log_debug(f'{name}: 画面无变化({change:.0%}), 换下一种方式')
                    continue
                used = name
                total = abs(moved)
                self.log_info(f'滚动({name}): {notches} 格 → {moved:+.1f} 行 '
                              f'(≈{scroll_model.px_per_notch:.1f}px/格, 残差 {diff:.0f}, '
                              f'停稳 {secs:.2f}s, 画面变化 {change:.0%})')
                if diff > SHIFT_DIFF_OK:
                    # 量不出位移(超出可测范围/动画抖动): 保守按"已滚动"处理, 绝不叠加输入
                    self.log_warning(f'动了但量不出位移(残差 {diff:.0f} > {SHIFT_DIFF_OK:.0f}), '
                                     f'按已滚动处理, 不再叠加输入')
                    return True
                # 测量已验证可信(静止判据 + 残差门槛) → **全信这一次实测**。
                # 旧的 0.5/0.7 平滑要 3~4 屏才收敛，收敛前每一屏都可能过滚(真机就是这么漏掉 40 只的)。
                scroll_model.observe(notches, moved * pitch, weight=1.0)
                break
            if used is None:
                self.log_warning('滚动受阻: 三种输入都没让画面发生变化')
                return False
            # ③ 闭环补残余：动画/限幅/加速度都可能让实际位移小于目标
            for _ in range(2):
                remaining = rows - total
                if remaining <= 0.6:
                    break
                before = _wait_still(rect)
                notches = scroll_model.notches_for(remaining, pitch)
                if used == '拖拽':
                    if not _drag_scroll(pitch, max(1, int(round(remaining)))):
                        break
                elif used == 'PostMessage':
                    try:
                        self.scroll_relative(0.52, 0.5, -notches)
                    except Exception as e:
                        self.log_debug(f'补滚 PostMessage 失败: {e}')
                        break
                elif not _real_wheel(notches):
                    break
                expect = notches * scroll_model.px_per_notch / max(1.0, pitch)
                moved, diff, change, secs = _measure_shift(before, pitch, rect, expect_rows=expect)
                if change < SCROLL_CHANGE_MIN or diff > SHIFT_DIFF_OK or abs(moved) < 0.35:
                    self.log_warning(f'补滚无效: {notches} 格 → {moved:+.1f} 行 '
                                     f'(残差 {diff:.0f}), 停在 {total:.1f} 行')
                    break
                scroll_model.observe(notches, moved * pitch)
                total += abs(moved)
                self.log_info(f'补滚({used}): {notches} 格 → {moved:+.1f} 行 '
                              f'(累计 {total:.1f}/{rows:.0f} 行, 停稳 {secs:.2f}s)')
            if total > 5.5:
                self.log_warning(f'一次滚了 {total:.1f} 行(可见 5 行), 可能漏行')
            elif total < rows - 1.5:
                self.log_warning(f'本次只滚了 {total:.1f} 行(目标 {rows:.0f} 行), 重叠会被去重吸收')
            return True

        def _parse_stats(paired_all):
            """属性行 → 真词条(前 2 行主属性排除 + 档位离散匹配, 最多 5 条)。

            提取成闭包是为了"面板没读干净 → 重读一次再解析"能复用同一份规则。
            """
            out = []
            if self._main_props_like(paired_all):
                for raw_n, v_str in paired_all[2:]:
                    norm = self._normalize_stat(raw_n, v_str)
                    val = parse_number(v_str)
                    if norm and is_stat_match(norm, val):
                        out.append((norm, val))
            return out[:5]

        def _has_stat_rows(paired_all):
            """详情读数里有没有**真词条**(2 行主属性之后、能对上官方档位的那几条)。

            为什么需要: 面板滚下去时名字/+25/COST 仍在(固定表头)，但词条区被滚走 —— 只用
            `paired_all` 非空判断"读到了"会漏掉这种情况(2026-11-19 真机)。
            """
            for raw_n, v_str in (paired_all or [])[2:]:
                norm = self._normalize_stat(raw_n, v_str)
                if norm and is_stat_match(norm, parse_number(v_str)):
                    return True
            return False

        def read_detail():
            """OCR 右侧详情面板。返回 (echo_name, paired_all, detail_sig, cost, level, level_box):
              echo_name  声骸名(面板顶部唯一中文行, y < 0.28*fh; 用于签名唯一性)
              paired_all 全部属性行 [(name, value_str), ...]  (主属性+词条, 按 y 序)
              detail_sig 名字 + 全量属性行签名(点选切换/唯一性检测)
              cost       面板 COST 角标(1/3/4; 认不出为 None)
              level      面板固定表头里的等级(0/5/…/25; 认不出为 None) —— 判"是否满级"的硬信号,
                         见 `_tier_from_level`(不能只数词条: 漏读一条就会把 +25 当成 +20)
            词条筛选由调用方按词条档位 is_stat_match 过滤(主属性数值超档自动丢弃)。

            布局注意: detail_box 下界 0.635(归一化) 是为覆盖第 5 词条(y≈0.607 + 文字高≈0.025);
            此前的 0.615(=738px@1920x1200) 把满级第 5 词条截在框外 → 报告永远最多 4 词条。
            """
            texts = self.ocr(*detail_box)
            dbg_ocr('detail', texts)
            # 低置信重读(参考策略工坊的"失败行重试"): 任一行 < 0.85 就再读一次整个详情面板,
            # 两次都不改画面, 取"高置信框更多/置信和更高"的那次; 只有 0.5~1 次额外 OCR, 不翻倍。
            if texts and any(ocr_conf(b) < self.OCR_RETRY_CONF for b in texts):
                texts_retry = self.ocr(*detail_box)
                dbg_ocr('detail_retry', texts_retry)
                if ocr_quality(texts_retry) > ocr_quality(texts):
                    texts = texts_retry
                    self.log_debug('详情面板低置信重读: 采用第二次结果')
            # COST 角标**只当佐证**：1× OCR 读到就带上(不额外放大重读 —— 那个 3× 裁剪重识别
            # 换成别的分辨率/字体就失效, 和套装图标是同一类问题)。真正的主口径是下面 evaluate_one
            # 里"第 2 行 = COST 固有属性"的结构反推(分辨率无关)。两者都在时用反推, 不一致只记日志。
            cost = parse_cost(texts)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            properties = [p for p in self.find_boxes(texts, match=property_pattern)
                          if p.name.strip() not in ('声骸技能', 'COST', 'Z', 'C')]
            properties.sort(key=lambda p: p.y)   # 先按 y 排序: "顶部中文行=名字/前 2 行=主属性" 都是相对行序
            echo_name = ''
            if properties and properties[0].y < fh * 0.28:
                # 面板顶部第一个中文行(归一化 y<0.28, 分辨率无关) = 声骸名, 提出来不进 properties(避免与数值错配)
                echo_name = properties[0].name
                properties = properties[1:]
            for p in properties:
                m = property_pattern.search(p.name)
                if m:
                    p.name = m.group()
            values = self.find_boxes(texts, match=number_pattern)
            # **表头噪声先剔掉**: COST 角标与等级都在第一行属性名的**上方**。OCR 有时把 `COST 3`
            # 拆成两个框，那个裸 `3` 也会被 `number_pattern` 当成"数值" —— 它一进 values 就可能与
            # 属性名错配一格(rep7 #136/#137: 冷凝 25.2 被记成 3.0, 整列右移)。
            if properties:
                value_floor = properties[0].y - 8
                values = [v for v in values if v.y >= value_floor]
            level = self.parse_level(texts)
            level_box = self.level_box(texts)      # 图标锚点(套装图标跟在等级文字右侧)
            if not properties:
                return echo_name, [], '', cost, level, level_box
            paired_all = self._pair_props(properties, values)
            detail_sig = f'{echo_name}|' + '|'.join(f'{n}={v}' for n, v in paired_all)
            return echo_name, paired_all, detail_sig, cost, level, level_box

        try:
            # 键数硬拒: 套装有效词条 <5 不允许评估(通用跳过)
            ok, msg = self._check_set_keys(self.config.get('当前套装', '通用'))
            if not ok:
                raise Exception(msg)
            if dbg_dir:
                self.log_info(f'调试数据集目录: {os.path.abspath(dbg_dir)}', notify=True)
            self.log_info('评估遍历: 不识别声骸数量, 直到「连续两行 0 词条 / 网格为空」结束')
            # 套装判定口径写进日志(用户 2026-11-20): 一值单键(名字只属一套)才按名字锁定,
            # 一值多键(同名可属多套)必须逐只读面板 —— 官方索引 229 个显示名里 158 个是多键。
            try:
                counts = echo_set_counts()
                multi = sum(1 for c in counts.values() if c > 1)
                self.log_info(f'套装判定: {len(counts)} 个声骸名 — 单键 {len(counts) - multi} 个(按名锁定) / '
                              f'多键 {multi} 个(逐只读面板)')
            except Exception as e:                  # noqa: BLE001 - 统计失败不该拦评估
                self.log_debug(f'套装统计读取失败(忽略): {e}')
            # 前置自检: 能不能把游戏拉到前台（= 输入权限是否够）。缺了它，故障会伪装成"检测不到网格"：
            # 没管理员 → bring_to_front 被 UIPI 拒 → 别的窗口盖着游戏 → 截图抓到遮挡窗口（实测 2026-11-18）。
            try:
                hwnd_window = getattr(self.executor.device_manager, 'hwnd_window', None)
                if hwnd_window is not None and hwnd_window.hwnd and not hwnd_window.bring_to_front():
                    raise Exception(
                        '无法把游戏窗口拉到前台（拒绝访问）：工具权限低于游戏。\n'
                        '请右键「以管理员身份运行」mainui.py 后重试（游戏是 High 权限时，Medium 的点/滚/前台都会被拒）。')
                self.sleep(0.3)
            except Exception as e:
                if '无法把游戏窗口拉到前台' in str(e):
                    raise
                self.log_debug(f'前置自检跳过(取 hwnd 失败): {e}')
            # 开局复位(用户口径 2026-11-19): **按两次 B** 关掉再打开背包 —— 声骸列表回到默认(顶部/默认排序)。
            # 不做的话会从上一轮停下的滚动位置继续(实测 21:06 那次首格落在列表中部, 上面的件永远扫不到)。
            self.reset_bag_view(presses=2)
            self.sleep(0.8)
            # 复位后游戏**默认选中第一只**(用户口径 2026-11-20) —— 这份基线就是 r1c1 的内容。
            # 所以它不能当"点选未切换"的参照: 点 r1c1 本来就不会换面板, 拿基线去比必然把首格
            # 判成"点击失败"(2026-11-20 report3 的 r1c1 就是这么丢的: 159 = 160-1, 面板内容
            # 与任何已记录条都对不上)。基线只留作日志证据, `last_sig` 置空 → 首格无论点击
            # 是否真的生效, 面板里的就是这一格。
            try:
                base_name, _, _, _, base_level, _ = read_detail()
                self.log_debug(f'开局基线(复位后默认选中的第一只): {base_name or "(无名)"} '
                               f'+{base_level if base_level is not None else "?"}')
            except Exception as e:
                self.log_debug(f'读初始详情失败(忽略): {e}')
            last_sig = ''

            while not stop_all:
                if self.stop_requested():
                    stopped = True
                    self.log_info('已请求停止, 结束评估(未生成报告)')
                    break
                cells = scan_grid()
                if not cells:
                    empty_scan += 1
                    if evaluated == 0 and not results and not bag_retry_done:
                        # 开局那两下 B 也可能是"打开→关闭"(开始时人就在大世界) → 补按一次再扫
                        bag_retry_done = True
                        self.reset_bag_view(presses=1)
                        empty_scan = 0
                        continue
                    # 网格区 OCR 不到角标: 0级角标 +0 也能被识别, 连续为空 ≈ 列表真到底;
                    # 首屏即空(且一个都未记录)才 raise, 提示可能不在背包界面
                    fail_shot = self._save_fail_frame() if empty_scan == 1 else ''
                    if empty_scan >= 2:
                        if evaluated == 0 and not results:
                            raise Exception(
                                '未在背包界面检测到声骸网格(角标/结构线)。'
                                + (f'\n当时抓到的画面已存: {fail_shot}'
                                   '\n若那张图里不是背包列表（例如是控制台/桌面），说明游戏被别的窗口挡住了 ——'
                                   '这版截图会抓到遮挡窗口，请把游戏放最前面（或最小化 cmd）再试。'
                                   if fail_shot else ''))
                        stop_reason = '到达背包底部(网格区连续为空)'
                        self.log_info('到达背包底部(网格区无角标), 评估结束', notify=True)
                        break
                    scroll_grid()
                    self.sleep(0.6)
                    continue
                empty_scan = 0

                processed_any = False
                screen_t0 = time.time()
                eval_before = evaluated
                dups = 0             # 本屏"真重复"格数(内容与已记录的一致) —— 与新增一起看可知重叠对不对
                miss = 0             # 本屏"点了但读不到属性"的格数 —— 这是**失败**，不是重复
                zero_cells = 0       # 本屏 0 词条格数
                screen_invalid = False   # 本屏被判"跑偏了"(点空一整行) → 复位背包后重扫, 不结算本屏
                ncols = max(1, len(cells) // max(1, int(grid_pitch.get('nrows') or 5)))
                for cell_i, (nx, ny) in enumerate(cells):
                    rc = f'r{cell_i // ncols + 1}c{cell_i % ncols + 1}'
                    if self.stop_requested():
                        stopped = True
                        self.log_info('已请求停止, 结束评估(未生成报告)')
                        break
                    # 点格子 → 右侧详情。第一次没切换就**换到行线的另一侧**再点一次：
                    # 行线是"等级条"的横边，卡片可能在线上方（批量管理视图）也可能压在线的下沿
                    # （普通列表）。主点按亮度判过一侧，重试点就取**相反那一侧**，两次合起来覆盖
                    # 两种解释；仍不切换则跳过（不再无限点同一格）。
                    fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
                    pitch_px = float(grid_pitch['row'] or 0.0)
                    dy_ratio = grid_pitch.get('dy')
                    if dy_ratio is None:
                        dy_ratio = 0.08
                    alt_ratio = 0.08 if dy_ratio < 0 else -0.30
                    delta = (alt_ratio - dy_ratio) * pitch_px / fh if pitch_px > 1 else -0.035
                    click_points = (clamp_click(nx, ny), clamp_click(nx, ny + delta))
                    echo_name, paired_all, sig, cost, level, level_box = '', [], '', None, None, None
                    for attempt, (cx, cy) in enumerate(click_points):
                        self.click(cx, cy, after_sleep=0.8)
                        dbg_shot(f'click_{cx:.2f}_{cy:.2f}')
                        echo_name, paired_all, sig, cost, level, level_box = read_detail()
                        if paired_all and sig != last_sig:
                            break
                        # 面板可能还停在上一次"找套装"的滚动位置(滚动条共用) → 先回顶再读一次。
                        # 判据用"读不到词条"(面板滚下去时固定表头仍在，只有词条区被滚走)。
                        if panel_dirty and (not paired_all or not _has_stat_rows(paired_all)):
                            if restore_panel_top():
                                panel_dirty = False
                            echo_name, paired_all, sig, cost, level, level_box = read_detail()
                            if paired_all and sig != last_sig:
                                break
                        if attempt == 0:
                            self.log_debug(f'点选未切换 → 换行线另一侧重试: ({nx:.3f},{ny:.3f})')
                    # **每格都留一条可核对的面板读数**(用户 2026-11-20: 日志不够详细) ——
                    # 名字/等级/属性行数/主属性像不像, 出问题时不用开调试数据集也能定位
                    mp_like = bool(paired_all) and self._main_props_like(paired_all)
                    rows_desc = ' / '.join(f'{n}={v}' for n, v in (paired_all or [])[:4]) or '(空)'
                    panel_desc = (f'面板: {echo_name or "(无名)"} '
                                  f'+{level if level is not None else "?"} '
                                  f'属性行{len(paired_all)}(主属性{"像" if mp_like else "不像"})')
                    self.log_debug(f'[格 {rc}] ({nx:.3f},{ny:.3f}) {panel_desc} :: {rows_desc}')
                    # 属性行签名(不含名字): 名字 OCR 抖动(无常凶驾/无常冈驾/无常区鹭)时防重复记录
                    stat_key = '|'.join(f'{n}={round(parse_number(v), 1)}' for n, v in paired_all)
                    key = self.dedup_key(echo_name, paired_all) if paired_all else ''
                    known_repeat = (key and key in seen_sigs) or (stat_key and stat_key in seen_stat_sigs)
                    still_same = last_sig is not None and sig == last_sig
                    if not paired_all or (still_same and not known_repeat):
                        # 按布局点了、但**没读到属性**(面板滚走/点空/没切换) —— 计入失败。
                        # 用户口径(2026-11-19): 这种不能悄悄当"重复"混过去，要能看见、且不能无限继续。
                        if _register_fail(nx, ny, f' | {panel_desc} | {rows_desc}', rc=rc):
                            break
                        continue
                    click_fail = 0
                    if known_repeat:
                        # 滚动重叠导致的重扫(内容与已记录的一致) —— 这才是"重复"，用于判重叠对不对
                        dups += 1
                        self.log_info(f'[格 {rc}] ({nx:.3f},{ny:.3f}) 重复(内容与已记录的一致) | '
                                      f'{panel_desc}')
                        continue

                    processed_any = True
                    if stat_key:
                        seen_stat_sigs.add(stat_key)

                    # 词条筛选: 详情属性区已按 y 排序(_pair_props), 前 2 行固定为主属性(攻击/生命/防御等)——
                    # 按相对行序排除, 分辨率无关; 即使主属性固定值恰好命中词条档位
                    # (如 主属性生命=510 ∈ {510}, 防御=50 ∈ {50}) 也不会误收;
                    # 剩余行再叠加"数值≈档位集合"(离散匹配)才算词条, 最多 5 条
                    #
                    # **+0 级面板没有主属性行**(只有 名字/+0/COST/持有数量：N/声骸技能…)，此时"前 2 行"
                    # 会把 `持有数量：1` 当主属性、把技能描述里的 `加成提升10.00%` 当成一条词条
                    # → 报告里出现"1 词条 / 0 级"的假记录(2026-11-19 report1 的 #145/#146 就是)。
                    # 所以先验一次"第 1 行像不像真主属性"，不像就按 0 级跳过(与"0 词条不入报告"同一口径)。
                    stats = _parse_stats(paired_all)
                    # **可疑面板**: 等级/主属性说它该有词条, 却一条没配上 —— 多半是这一格没读干净
                    # (面板重新选中后滚动位置没回顶 / 还没刷新完)。先回顶 + 等 0.3s 重读一次;
                    # 真机 2026-11-20 首屏 5/24 格就是这种情况(以前被静默当成"0 级", 现在报失败)。
                    if not stats and ((level is not None and level >= 5)
                                      or (paired_all and self._main_props_like(paired_all))):
                        # **只有我们真的滚过面板(没回顶)才回顶** —— 否则每次都往上滚一下,
                        # 用户看到的就是"评估一开始右侧面板反而往上滑"(2026-11-20 反馈)。
                        if panel_dirty and restore_panel_top():
                            panel_dirty = False
                        self.sleep(0.3)
                        name2, paired2, sig2, cost2, level2, level_box2 = read_detail()
                        stats2 = _parse_stats(paired2)
                        if stats2:
                            echo_name, paired_all, sig = name2, paired2, sig2
                            cost, level = cost2 or cost, level2 if level2 is not None else level
                            level_box = level_box2 or level_box
                            stats = stats2
                            self.log_info(f'[格 {rc}] 面板重读成功({len(stats)} 条词条): {echo_name}')
                        else:
                            self.log_info(f'[格 {rc}] 面板重读仍无词条: {name2 or "(无名)"} '
                                          f'属性行{len(paired2)} 主属性'
                                          f'{"像" if self._main_props_like(paired2) else "不像"}')

                    if stats:
                        badge = badge_hue_at(nx, ny)
                        cand_list = get_sets_by_echo(echo_name) if echo_name else []
                        # 套装图标锚点: 图标跟在等级文字右侧, 位置随 `+5`/`+25` 的宽度变 →
                        # 用等级框算(icon_box_at_level), 不用固定区(固定区只对 +25 成立)。
                        icon_box = None
                        if level_box is not None:
                            try:
                                fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
                                icon_box = icon_box_at_level(level_box.x, level_box.y,
                                                             level_box.width, level_box.height, fw)
                            except Exception as e:      # noqa: BLE001 - 图标只是备选
                                self.log_debug(f'图标锚点计算失败(忽略): {e}')
                        if len(cand_list) == 1:
                            # **只属于一套** → 名字就是答案，不滚面板、不做 OCR(用户口径)
                            set_name, set_src = self.resolve_set_name(echo_name, badge)
                        else:
                            # 名字多义/没认出来 → 两条路(2026-11-20 用户拍板):
                            # ① **精确模式**(`config['套装精确模式']`): 总是滚到「合鸣效果」区读套装名明文
                            #    (2026-11-19 口径, 最稳, 但下滑占整轮 46% 的时间);
                            # ② **默认快速**: 先试固定表头 —— 套装图标(动态框) → 徽章环色收窄。
                            #    report6 139 张面板回归: top-1 99.3%、闸内 100%; 两个信号都不够
                            #    (约 11%)才回退去滚面板, 低置信件才付这笔时间。
                            # **逐只判定**, 不按名字/环色缓存套装: 同名不同件可以属于不同套装
                            # (格洛犸图 → 长路启航之星 / 雪落无声之愿), report4 的 #21/#23/#24
                            # 就是被第一只(长路)的名字缓存套错的。
                            precise = bool(self.config.get('套装精确模式'))
                            if precise:
                                effect_set, _s1, _s2, effect_src = read_set_by_effect(cand_list, echo_name)
                                set_name, set_src = self.resolve_set_name(echo_name, badge,
                                                                          effect_set, effect_src,
                                                                          use_icon=True, icon_box=icon_box)
                            else:
                                quick = self.quick_set_from_header(echo_name, badge, cand_list, icon_box)
                                if quick:
                                    set_name, set_src = quick
                                else:
                                    # 回退: 滚面板读明文(图标刚试过, 这里不再重复匹配)
                                    effect_set, _s1, _s2, effect_src = read_set_by_effect(cand_list, echo_name)
                                    set_name, set_src = self.resolve_set_name(echo_name, badge,
                                                                              effect_set, effect_src,
                                                                              use_icon=False,
                                                                              icon_box=None)
                        # 评分 / 判定 / 前瞻 / 重铸方案 + 词条明细 → evaluate_one(与离线重放共用同一份实现)
                        # L2: 前 2 行主属性与 COST 角标一并交给它(报告据此标"官方管理方案"是否认可该主属性)
                        # level: 面板固定表头的 `+NN` —— 判"满级/未满级"的硬信号(见 _tier_from_level)
                        rec = self.evaluate_one(echo_name, stats, set_name, set_src,
                                                main_props=paired_all[:2], cost=cost, level=level)
                        tier = rec["tier"]
                        if rec.get("stats_missing"):
                            # 等级说满级、词条却少读了 → 分数只是下界。不拦记录(宁可多记),
                            # 但必须让人看见: 2026-11-19 就是这条被静默当成 +20 才判出"不建议强化"。
                            self.log_warning(
                                f'[!] {echo_name}: 等级 +{level} 应有 {tier} 条词条, 只读到 {len(stats)} 条'
                                f'(漏读 {rec["stats_missing"]}) → 分数偏低, 判定按满级算')
                        # 徽章环色写进记录: 报告/JSON 自带证据, 事后可**离线核对套装判定**
                        rec['badge_hue'] = badge[0] if badge and badge[1] else None
                        verdict, verdict_cn, score = rec["verdict"], rec["verdict_cn"], rec["score"]
                    else:
                        # 读到面板、但一条词条都没配上: **先分清是"真 0 级"还是"这一格没读干净"**。
                        # 列表按等级排序(用户口径) → 0 级件只会在尾部, 中途的"0 词条"基本都是没读干净
                        # (面板没刷新完 / 点到格子间隙 / OCR 只读到半个面板)。旧代码一律当 0 级,
                        # 于是"连续 N 格 0 词条 = 到底"的判据在列表中间误触发(2026-11-19 21:26 只扫到 43 条)。
                        if not self._blank_panel_is_zero_level(level, paired_all):
                            # 等级 ≥+5 或前 2 行像真主属性 → 它本该有词条, 这是**失败**
                            why = (f'(等级 +{level}, 主属性'
                                   f'{"像" if self._main_props_like(paired_all) else "不像"}, '
                                   f'却没配出词条) | {rows_desc}')
                            if _register_fail(nx, ny, why, rc=rc):
                                break
                            continue
                        # 真 0 级: 列表按等级排序 → **这就是尾部**, 直接收工(用户口径 2026-11-20:
                        # "按等级识别到 0 级 / 只有两个固定词条就可以停")。硬信号:
                        #   ① 等级读到 +0; ② 等级没读到但面板只剩两条固定行(没有词条区)。
                        # 读失败(等级 ≥+5 或主属性像)上面已走失败分支, 不会到这里。
                        # 旧的"整屏全 0 连续 3 屏"保留为兜底(0 级信号认不出时仍能收工)。
                        processed_any = True
                        seen_sigs.add(key)
                        zero_cells += 1
                        if level == 0 or (level is None and len(paired_all) <= 2):
                            stop_reason = f'到达0级尾部(格 {rc} 读到 +0)'
                            self.log_info(f'[格 {rc}] ({nx:.3f},{ny:.3f}) 0级(无词条) → '
                                          f'列表已到 0 级段, 评估结束', notify=True)
                            stop_all = True
                            break
                        self.log_info(f'[格 {rc}] ({nx:.3f},{ny:.3f}) 0级(无词条) 跳过 | {panel_desc}')
                        continue

                    last_sig = sig
                    seen_sigs.add(key)

                    ss_name = f"eval_{evaluated + 1:03d}_{verdict}_{score:.1f}.png"
                    ss_path = os.path.join(ss_dir, ss_name)
                    # 截图 = 右侧详情完整展示: 名字(y~122)/COST/主属性/词条(含第5, y~728)/声骸技能行
                    # 此前固定截网格左上角(0.09,0.09,0.37,0.55) → 与当前声骸无关, 已改为右侧面板
                    echo_img = self.box_of_screen(0.665, 0.07, 0.995, 0.65).crop_frame(self.frame)
                    # 报告引用这张图 → 落盘失败必须能看见, 不能像裸 cv2.imwrite 那样静默返回 False
                    if not echo_panel_shot.imwrite_unicode(ss_path, echo_img) and not shot_fail_warned:
                        shot_fail_warned = True
                        self.log_warning(f'截图落盘失败(大概率是路径含非 ASCII 字符): {ss_path} — '
                                         f'报告里的截图会是碎图; 把工作区/临时目录换到纯英文路径可解')

                    # 记录字段来自 evaluate_one, 这里补报告用的序号与截图名
                    results.append({"index": evaluated + 1, "screenshot": ss_name, **rec})
                    self.log_info(f'[格 {rc}] ({nx:.3f},{ny:.3f}) {panel_desc} → 记录#{evaluated + 1}')
                    self.log_info(f"[评估#{evaluated + 1}] {echo_name} | {tier}/5词条 | 得分={score:.2f} "
                                  f"| {verdict_cn} | 套装={set_name}({set_src})")
                    evaluated += 1
                    self.info_set('评估数量', evaluated)

                if stop_all or stopped:
                    break
                if screen_invalid:
                    # 已经复位过背包: 不滚屏、不判重叠, 直接重扫本屏(此时在列表顶部, 重复由去重吸收)
                    layout_model = None      # 重开背包后重新标定, 不吃旧模型
                    panel_dirty = False
                    continue
                # 本屏小结: "新增 + 重复" 直接反映滚动重叠对不对(滚 3 行应剩 ~2 行重复);
                # 失败 = 点了但读不到属性(面板滚走/点空) —— 与"重复"分开计数，否则分不清是重叠还是坏了
                self.log_info(f'本屏完成: {len(cells)} 格({ncols}×{len(cells) // max(1, ncols)}), '
                              f'新增 {evaluated - eval_before} 条, 重复 {dups} 格, '
                              f'失败 {miss} 格, 0词条 {zero_cells} 格, 耗时 {time.time() - screen_t0:.1f}s')
                # ── 0 级尾部: **整屏都是 0 词条**才记一屏, 连续 3 屏才收工 ──────────────
                # 不能按"连续 12 格"判: 0 级件是按套装/获得顺序**夹在列表中间**的(实测 2026-11-19 21:26:
                # 第 4 屏只有 13 个 0 级格, 12 格规则当场把 43 条当成"到底"; 而 17:00 那次旧版要到整屏
                # 跑完才生效, 所以扫满 146 才停)。整屏全 0 才说明进了 0 级段, 一屏不够(可能只是某个套装的
                # 一批 0 级件), 三屏 ≈90 格连续 0 级才收工。真到底仍由"网格连续为空"兜底。
                if zero_cells == len(cells):
                    zero_screens += 1
                    self.log_info(f'[0级] 本屏 {zero_cells} 格全是 0 词条 (连续 {zero_screens} 屏)')
                else:
                    zero_screens = 0
                if zero_screens >= ZERO_TAIL_SCREENS:
                    stop_reason = f'0级尾部(连续 {zero_screens} 屏 0 词条)'
                    self.log_info(f'连续 {zero_screens} 屏全是 0 词条, 视为 0 级尾部, 评估结束', notify=True)
                    stop_all = True
                    break
                # ── 无重叠守卫(内容级，不依赖像素测量) ─────────────────────────
                # 非首屏却**一格重复都没有** = 这次滚过头了(≥5 行)，中间整行被跳过。
                # 像素测不准也能发现漏行：重复数是"真滚了几行"的直接证据。
                # 有"点了读不到"的格子时不判重叠 —— 那屏的结果本来就不可信，先别拿它当证据。
                if screens_done >= 1 and dups == 0 and miss == 0 and evaluated > 0 and back_steps < 2:
                    back_steps += 1
                    self.log_warning(f'本屏无重叠(滚过头, 中间整行被跳过) → 回滚 1 行重扫'
                                     f' (第 {back_steps} 次)')
                    scroll_up(1.0)
                    continue
                screens_done += 1
                back_steps = 0

                moved_ok = scroll_grid()
                if moved_ok:
                    scroll_fail = 0
                    if processed_any:
                        no_new_screen = 0
                    else:
                        no_new_screen += 1
                        if no_new_screen >= 3:
                            stop_reason = '连续滚动无新内容'
                            self.log_info('连续滚动无新内容, 评估结束', notify=True)
                            break
                else:
                    scroll_fail += 1
                    if scroll_fail >= 2:
                        stop_reason = f'滚动受阻 {scroll_fail} 次'
                        self.log_warning(f'连续 {scroll_fail} 次滚动受阻, 评估中止'
                                         f'(已记录 {evaluated} 条, 生成部分报告)', notify=True)
                        stop_all = True
                        break
                self.sleep(1.2)

            if stopped:
                self.info_set('评估结束原因', '用户停止')
                self.log_info(f'评估已停止, 本次已记录 {evaluated} 个声骸(不生成报告/不打开报告)', notify=True)
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return
            # U-03: 结束原因进状态卡(与下面日志里那句同源, 免得只看到一个条数不知道为啥停)
            self.info_set('评估结束原因', stop_reason or '完成')
            # 汇总 JSON(顶层 set = 本次评估的 config 套装; 逐条的 set/set_src 见 resolve_set_name)
            output_set = self.config.get('当前套装', '通用')
            src_stat = Counter(r.get('set_src') or 'default' for r in results)
            output = {
                "set": output_set,
                "total": evaluated,
                "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "click_fail": click_fail_total,
                # U-07: 本次跑的是哪种套装判定模式(报告页脚/事后核对 set_src 分布用)
                "set_mode": "precise" if self.config.get('套装精确模式') else "icon_first",
                "panel_restore_fail": panel_dbg_restore_fail if panel_dbg_dir else None,
                "set_src": dict(src_stat),
                "results": results,
            }
            json_path = os.path.join(tmp_dir, "eval_result.json")
            with open(json_path, "w", encoding="utf-8") as f:
                _json.dump(output, f, ensure_ascii=False, indent=2)

            self.log_info(f'评估完成, 共{evaluated}个声骸 '
                          f'(套装来源: {" / ".join(f"{k}={v}" for k, v in src_stat.most_common())}'
                          f'; 点击失败 {click_fail_total} 格'
                          + (f'; 面板回顶失败 {panel_dbg_restore_fail} 次' if panel_dbg_restore_fail else '')
                          + (f'; 结束原因: {stop_reason}' if stop_reason else '')
                          + ')', notify=True)
            if on_done:
                self.handler.post(lambda: on_done(json_path, ss_dir))
            else:
                # 没有回调(离线/批处理场景): 没人会来收这个临时目录, 自己清掉(C16)
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except BaseException:                  # noqa: BLE001 - 连 SystemExit/KeyboardInterrupt 也要先清临时目录
            # 只写 `except Exception` 会漏掉 `SystemExit`: `TaskExecutor.frame` 在退出时就是
            # `sys.exit(0)`(见 A4), 那样这一轮评估的详情面板截图(可达数百 MB)会永久留在 %TEMP%。
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def find_echo_enhance(self):
        return self.ocr(0.82, 0.86, 0.97, 0.96, match='培养')

    def run(self):
        # 键数硬拒: 套装有效词条 <5 不允许强化(与评估共用配置校验)
        ok, msg = self._check_set_keys(self.config.get('当前套装', '通用'))
        if not ok:
            raise Exception(msg)
        self.info_set('成功声骸数量', 0)
        self.info_set('失败声骸数量', 0)
        clear_folder('screenshots')
        # **连续跳过上限**(C15): "已是满级 → esc → 下一个"这条分支如果 esc 没真的换到下一只,
        # 就会原地死循环(不报错、不推进)。20 只是余量, 超过必然是界面/过滤器出问题。
        max_level_skips = 0
        while True:
            enhance = self.find_echo_enhance()
            if not enhance:
                raise Exception('必须在背包声骸界面过滤后开始!')
            # 检查是否为0级声骸 vs 未满级声骸 vs 满级声骸
            current_is_0 = self.ocr(0.65, 0.35, 1, 0.57, match=re.compile('声骸技能'))
            if not current_is_0:
                # 非0级: 可能是未满级或满级
                # OCR读取当前词条数判断是否满级
                texts = self.ocr(0.09, 0.3, 0.40, 0.53)
                properties = [p for p in self.find_boxes(texts, match=property_pattern) if '辅音' not in p.name]
                if len(properties) >= 5:
                    # 已满级 → 跳过这个, 找下一个
                    max_level_skips += 1
                    if max_level_skips > 20:
                        raise Exception('连续 20 只都是满级声骸 —— 过滤器/排序没生效, 或 esc 没换到下一只')
                    self.log_info('已是满级声骸, 跳过')
                    self.esc()
                    self.wait_ocr(0.82, 0.86, 0.97, 0.96, match='培养', settle_time=0.1)
                    continue
                elif len(properties) > 0:
                    max_level_skips = 0        # 真的在处理一只 → 清掉"连续跳过"计数
                    self.log_info(f'未满级声骸(已有{len(properties)}词条), 继续强化')
                else:
                    total = self.info_get('成功声骸数量') + self.info_get('失败声骸数量')
                    self.log_info(f'无可强化声骸, 任务结束! 强化{total}个, 符合条件{self.info_get("成功声骸数量")}个',
                                  notify=True)
                    if self.info_get('成功声骸数量') >= 1:
                        try:
                            os.startfile(os.path.abspath("screenshots"))
                        except Exception as e:
                            self.log_error(f"无法打开截图文件夹: {e}")
                    return
            start = time.time()
            while time.time() - start < 5:
                if enhance:
                    self.click(enhance, after_sleep=0.5)
                enhance = self.find_echo_enhance()
                if not enhance:
                    break

            # 未满级声骸先读当前词条做渐进判断, 避免浪费材料
            is_partial = not bool(self.ocr(0.65, 0.35, 1, 0.57, match=re.compile('声骸技能')))
            if is_partial and self.config.get('强化策略') == '渐进式':
                texts = self.ocr(0.09, 0.3, 0.40, 0.53)
                properties = [p for p in self.find_boxes(texts, match=property_pattern) if '辅音' not in p.name]
                for p in properties:
                    match = property_pattern.search(p.name)
                    if match:
                        p.name = match.group()
                values = self.find_boxes(texts, match=number_pattern)
                self.log_debug(f'未满级前置检查: {properties}')
                if not self.check_echo_progressive(properties, values):
                    self.trash_and_esc()
                    break
                self.log_info(f'前置检查通过, 继续强化')

            # **有界循环**(C15): 正常每轮 +5 级, 最多 5 轮就该满级;
            # 给 12 轮是余量, 超过说明"点了强化但词条不涨"(材料不足/界面变了/OCR 一直漏读)。
            for _level_round in range(12):
                start_wait = time.time()
                have_add_mat = False
                while time.time() - start_wait < 5:
                    add_mat = self.find_add_mat()
                    if add_mat:
                        have_add_mat = True
                        self.click(add_mat, after_sleep=0.3)
                    else:
                        self.next_frame()
                        if have_add_mat:
                            break
                if not have_add_mat:
                    raise Exception('强化设置需要开启阶段放入!')

                if not self.wait_click_ocr(0.17, 0.88, 0.29, 0.96, match=['强化并调谐'],
                                           settle_time=0.1,
                                           after_sleep=1.5):
                    if self.ocr(0.17, 0.88, 0.29, 0.96, match=['强化']):
                        raise Exception('强化设置需要开启同步调谐!')
                    else:
                        raise Exception('找不到 强化并调谐!')
                while handle := self.wait_ocr(0.24, 0.18, 0.75, 0.98,
                                              match=[re.compile('不再提示'), '调谐成功', re.compile('点击任')],
                                              time_out=2):
                    if handle[0].name in ['本次登录不再提示', '本次登入不再提示']:
                        click = handle[0]
                        click.width = 1
                        click.x -= click.height * 1.1
                        self.click(click, after_sleep=0.5)
                        self.click(self.find_confirm(), after_sleep=0.5)
                    elif handle[0].name in ['点击任意位置返回', '调谐成功']:
                        self.click(handle, after_sleep=1)
                    else:
                        self.sleep(0.5)
                self.sleep(0.1)
                texts = self.ocr(0.09, 0.3, 0.40, 0.53)
                self.log_debug(f'ocr values: {texts}')
                properties = [p for p in self.find_boxes(texts, match=property_pattern) if '辅音' not in p.name]
                for p in properties:
                    match = property_pattern.search(p.name)
                    if match:
                        p.name = match.group()
                values = self.find_boxes(texts, match=number_pattern)
                self.info_set('属性', properties)
                self.info_set('值', values)

                if self.config.get('强化策略') == '渐进式':
                    if not self.check_echo_progressive(properties, values):
                        self.trash_and_esc()
                        break
                else:
                    if not self.check_echo_stats(properties, values):
                        self.trash_and_esc()
                        break

                if len(properties) >= 5:
                    self.lock_and_esc()
                    break
            else:
                # for-else: 12 轮都没 break = 一直在"点强化但没满级"(C15)
                raise Exception(f'强化 {12} 轮仍未满级 —— 看看"强化并调谐"是否点到了/材料是否够'
                                f'(当前词条 {len(properties)} 条)')

    def find_confirm(self):
        button_box = self.box_of_screen(0.60, 0.65, 0.82, 0.82)
        if confirm := self.find_one('echo_enhance_confirm', box=button_box, threshold=0.7):
            return [confirm]
        return self.ocr(box=button_box, match='确认')

    def check_echo_stats(self, properties, values):
        self.fail_reason = ""
        invalid_count = 0

        paired_stats = self._pair_props(properties, values)

        total_count = len(paired_stats)

        crit_rate_val = 0
        crit_dmg_val = 0
        has_crit_rate = False
        has_crit_dmg = False

        checked_first_crit = False
        has_encountered_crit = False

        valid_stats = self.config.get('有效词条') or []

        for p_raw, v_str in paired_stats:
            p = self._normalize_stat(p_raw, v_str)

            v = parse_number(v_str)

            is_valid_prop = True
            is_crit_stat = p in ['暴击', '暴击伤害']

            if self.config.get(
                    '双爆出现之前必须全有效词条') and '暴击' in valid_stats and '暴击伤害' in valid_stats and not has_encountered_crit:
                if not is_crit_stat:
                    if p not in valid_stats:
                        self.fail_reason = f'双爆前含无效_{p}'
                        self.log_info(f'双爆出现前存在无效词条 {p}, 丢弃')
                        return False
                else:
                    has_encountered_crit = True

            if is_valid_prop and p not in valid_stats:
                is_valid_prop = False
                self.log_debug(f'非有效词条, {p} 不符合条件')

            if p == '暴击':
                has_crit_rate = True
                crit_rate_val += v
                if '暴击' in valid_stats and not checked_first_crit:
                    checked_first_crit = True
                    if v < self.config.get('首条双爆>='):
                        self.fail_reason = f'首条暴击不足_{v}'
                        self.log_info(f'首条暴击 {v} < {self.config.get("首条双爆>=")}，丢弃')
                        return False

            elif p == '暴击伤害':
                has_crit_dmg = True
                crit_dmg_val += v
                if '暴击伤害' in valid_stats and not checked_first_crit:
                    checked_first_crit = True
                    if v / 2 < self.config.get('首条双爆>='):
                        self.fail_reason = f'首条爆伤不足_{v}'
                        self.log_info(f'首条爆伤 {v} < {self.config.get("首条双爆>=")}，丢弃')
                        return False

            if not is_valid_prop:
                invalid_count += 1

        self.info_set('不符合条件属性', invalid_count)

        if self.config.get('必须有双爆'):
            missing_crit = (0 if has_crit_rate else 1) + (0 if has_crit_dmg else 1)
            remaining_slots = 5 - total_count
            if remaining_slots < missing_crit:
                self.fail_reason = f'无法凑齐双爆_缺{missing_crit}'
                self.log_info(f'无法凑齐双爆 (缺{missing_crit}种, 剩{remaining_slots}孔), 丢弃')
                return False

        if has_crit_rate and has_crit_dmg:
            total_score = crit_rate_val + (crit_dmg_val / 2)
            if total_score < self.config.get('双爆总计>='):
                self.fail_reason = f'双爆总计不足_{total_score:.1f}'
                self.log_info(f'双爆总计 {total_score:.1f} < {self.config.get("双爆总计>=")}，丢弃')
                return False

        if total_count == 1 and self.config.get('第一条必须为有效词条') and invalid_count == 1:
            self.fail_reason = '首条无效'
            self.log_info('第一条必须为有效词条, 丢弃')
            return False

        valid_count = total_count - invalid_count
        remaining_slots = 5 - total_count
        if (valid_count + remaining_slots) < self.config.get('有效词条>='):
            self.fail_reason = f'有效词条不足_上限{valid_count + remaining_slots}'
            self.log_info(f'剩余孔位不足以达到设定的有效词条数量, 丢弃')
            return False

        # 评分模式：计算加权词条得分
        if self.config.get('启用评分模式'):
            score, detail_lines = self.compute_weighted_score(paired_stats)
            self.info_set('声骸得分', f'{score:.2f}')
            self.log_info(f'评分详情: {" | ".join(detail_lines)}')
            self.log_info(f'声骸总分: {score:.2f}')
            if score < self.config.get('最低得分>='):
                self.fail_reason = f'得分不足_{score:.2f}'
                self.log_info(f'总分 {score:.2f} < {self.config.get("最低得分>=")} 丢弃')
                return False

        return True

    def check_echo_progressive(self, properties, values):
        """渐进式强化判断 —— 判定统一走 `judge_echo`(与评估同源), 这里只负责取数与丢弃动作:
          Lv5/Lv10(1~2 条) → 结构判定: **首条**在首核内即过(不限分); 套装配置了 `_low_first`
                              时, 低权重首条还须位于前 N 档
          Lv15/Lv20(3~4 条) → 总分 ≥ **B(满级)**, 或 前瞻概率 ≥ ENCHANT_MIN_PROB(0.60) 且 总分 ≥ 达标线 A
          Lv25(5 条) → A ≥ B 且 总分 ≥ A 才算达标, 否则丢弃
        未满级一律与 B(满级) 比(不是当前级的 B(tier)); 通用模式 B(满级) = 17.5, 套装模式按该套装权重算。
        """
        self.fail_reason = ""

        # 1. 配对属性名和数值
        paired_stats = self._pair_props(properties, values)

        tier = len(paired_stats)

        # 2. 归一化属性名
        normalized = []
        for p_raw, v_str in paired_stats:
            p = self._normalize_stat(p_raw, v_str)
            v = parse_number(v_str)
            normalized.append((p, v))

        # 3. 套装(权重来源; 判定两线见 judge_echo)
        set_name = self.config.get('当前套装', '通用')

        # 4. 渐进式判断(与评估共用 judge_echo: Lv5/10 首条结构判定, Lv15+ 锚线)
        if tier <= 2:
            ok, reason = self._struct_first_ok(set_name, normalized)
            if not ok:
                self.fail_reason = reason or '首条不合格'
                self.log_info(f'[渐进T{tier}] 首条不合格({reason}) : {[n for n, _ in normalized]}, 丢弃')
                return False
            self.log_info(f'[渐进T{tier}] 首条通过(不限分) OK 继续')
            return True

        # tier 3-5: 先算总分再判定
        score, details = self.compute_weighted_score(
            [(n, str(v)) for n, v in normalized]
        )
        self.info_set('声骸得分', f'{score:.2f}')
        self.log_info(f'[渐进T{tier}] 得分: {" | ".join(details)}')
        self.log_info(f'[渐进T{tier}] 总分: {score:.2f}')

        (verdict, _), threshold, _ = self.judge_echo(set_name, tier, score, normalized)
        if verdict == 'fail':
            self.fail_reason = f'T{tier}得分不足_{score:.2f}<{threshold}'
            self.log_info(f'[渐进T{tier}] {score:.2f} < {threshold}, 停止强化')
            return False
        self.log_info(f'[渐进T{tier}] {score:.2f} >= {threshold} OK 继续')
        return True

    # 频整器(官方公示): 锁 L 条消耗 (L-1) 个, 但锁 1~2 条都按 1 个计(用户口径); 每个按 30 元估算。
    REFORGE_PRICE = 30            # 元/个(仅用于报告展示的估算)
    REFORGE_LOCK_MAX = 4          # 最多锁 4 条(要留 1 个刷新位)
    REFORGE_TRIALS = 3000         # 每个候选方案的模拟次数(P 的估计误差 ≈ ±0.9%)
    REFORGE_MIN_PROB = 0.60       # 判"值得重铸"的最低达标概率(用户口径: 胚子可无限刷,
                                  # 花 30 元只买三成把握不值 —— 宁可去刷新胚子)
    ENCHANT_TRIALS = 3000         # 未满级前瞻的模拟次数
    ENCHANT_MIN_PROB = 0.60       # "继续开到满级能否过保留线"的最低概率(与重铸同口径)
    OCR_RETRY_CONF = 0.85         # 详情面板任一 OCR 框低于此置信度时, 整面板重读一次再取较优结果

    def enchant_prospect(self, set_name, tier, stats):
        """未满级前瞻: 继续强化到满级后"总分 ≥ 保留线 B(满级)"的概率(0~1); 无法前瞻返回 None。

        为什么要前瞻: Lv15(剩 2 位) / Lv20(剩 1 位) 若**大概率**连保留线都够不到, 就没必要再花强化材料
        —— 与"建议重铸"同理(期望只是均值, 而胚子可无限刷), 所以判据也用**概率**而非期望分。
        模拟: 保留现有 tier 条不动, 从"可用池(13 − 已有类型)"**无放回**补 (5 − tier) 条, 每条按
        **官方档位概率**抽档位 → 统计 (当前分 + 新分) ≥ B(5) 的比例。
        已满级(无需前瞻) / 无候选池 → 返回 None, 由调用方按原逻辑处理。
        """
        import random

        from src.echo_stats import _TIERS, _load_tier_probs

        need = 5 - len(stats)
        if need <= 0:
            return None
        weights = DEFAULT_WEIGHTS if (not set_name or set_name == '通用') else (get_set_weights(set_name) or {})
        have, cur_score = set(), 0.0
        for n, v in stats:
            have.add(n)
            tv, mn, w = snap_to_tier(n, v), get_mean(n), weights.get(n, 0.0)
            if tv and mn and w > 0:
                cur_score += w * tv / mn * 10
        pool = [n for n in _TIERS if n not in have]
        if len(pool) < need:
            return None
        base5 = _legacy_threshold(set_name, 5)
        probs = _load_tier_probs()
        feat: dict[str, tuple] = {}
        for nm in pool:
            p = probs.get(nm) or {}
            tiers = [t for t in _TIERS[nm] if t in p]
            feat[nm] = (tiers, [p[t] for t in tiers], 10 * weights.get(nm, 0.0) / (get_mean(nm) or 1.0))
        rng = random.Random(20260915)                 # 固定种子 → 可复现
        ok = 0
        for _ in range(self.ENCHANT_TRIALS):
            total = cur_score
            for nm in rng.sample(pool, need):
                tiers, tier_probs, coef = feat[nm]
                if tiers:
                    total += rng.choices(tiers, weights=tier_probs)[0] * coef
            if total >= base5:
                ok += 1
        return ok / self.ENCHANT_TRIALS

    def reforge_plan(self, set_name, stats):
        """穷举"锁 L 条 + 刷 (5−L) 条" → **"刷成达标的概率 ≥ REFORGE_MIN_PROB"里成本最低的方案**; 无则 None。

        **为什么用概率而不是"期望分"**: 期望只是均值 —— "期望达标"实际只有约 50% 把握, 而分数分布
        右偏(档位有上限、类型无放回)使真实概率更低。花 30 元买 5 成把握不值, 所以直接模拟
        "这套方案刷完能不能真的达标"。

        三层过滤(先代数后模拟, 避免对全部 30 个方案做蒙特卡洛):
          ① 代数粗筛 `10 × Σw_after ≥ B` —— 重铸后的达标线站得住(A_after ≥ B), 否则这只永远达不到标
             (典型: "锁 1 条低权重词条 + 刷 4 条" — 那些条 w=0, 对达标无贡献却占锁定名额)
          ② 期望粗筛 `r̄ ≥ 1.0` —— 期望达标。P ≥ 50% 的方案必然通过它(均值必大于门槛), 故不会漏判;
             (5−L)×E_feat = 10×W_new 两边抵消, 所以 ② 等价于"期望分 ≥ A_after"
          ③ 蒙特卡洛精确: 锁 L 条 + 从"可用池(13−L 种)"**无放回**补 M 条, 每条按**官方档位概率**抽档位;
             统计 `A_after ≥ B 且 新总分 ≥ A_after` 的比例 = 达标概率 P

        成本 = max(1, L−1) × 30 元; 选法: 通过③(P ≥ 阈值)的方案里取**成本最低**(并列取 P 最高)。
        方案里同时保留期望量(e_feat / r̄ / 期望分 / 重铸后达标线)供报告对照。
        """
        import random
        from itertools import combinations

        from src.echo_stats import _TIERS, _load_tier_probs

        weights = DEFAULT_WEIGHTS if (not set_name or set_name == '通用') else (get_set_weights(set_name) or {})
        per, wr = [], []                             # 每条词条的当前条分 / 当前 rᵢ·wᵢ
        for n, v in stats:
            tv, mn, w = snap_to_tier(n, v), get_mean(n), weights.get(n, 0.0)
            if tv and mn and w > 0:
                r = tv / mn
                per.append(w * r * 10)
                wr.append(r * w)
            else:
                per.append(0.0)
                wr.append(0.0)
        if len(per) < 2:
            return None
        total_w = sum(w for w in weights.values() if w > 0)
        base = _legacy_threshold(set_name, len(per))
        # 预计算每个词条的抽取表(tiers, 概率, 得分系数=10w/期望, 权重) —— 避免在模拟内反复查表
        probs = _load_tier_probs()
        feat: dict[str, tuple] = {}
        for nm in _TIERS:
            p = probs.get(nm) or {}
            tiers = [t for t in _TIERS[nm] if t in p]
            mean = get_mean(nm) or 1.0
            w = weights.get(nm, 0.0)
            feat[nm] = (tiers, [p[t] for t in tiers], 10 * w / mean, w)
        all_names = list(_TIERS)
        rng = random.Random(20260915)                # 固定种子 → 同一只的结果可复现
        best = None
        for limit in range(1, min(self.REFORGE_LOCK_MAX, len(per) - 1) + 1):
            for idx in combinations(range(len(per)), limit):
                locked_names = [stats[i][0] for i in idx]
                locked_w = sum(weights.get(n, 0.0) for n in locked_names)
                locked_score = sum(per[i] for i in idx)
                need = len(per) - limit
                avail = total_w - locked_w
                e_feat = 10 * avail / (13 - limit)          # 一条随机新词的期望分
                w_new = need * avail / (13 - limit)         # 新刷部分的期望权重和(其档位期望恰为 1.0)
                sw_after = locked_w + w_new
                if 10 * sw_after < base:                    # ① 代数粗筛: 重铸后的达标线站不住
                    continue
                rbar = (sum(wr[i] for i in idx) + w_new) / sw_after if sw_after > 0 else 0.0
                if rbar < 1.0:                              # ② 期望粗筛: 期望都不到平均档
                    continue
                pool = [n for n in all_names if n not in locked_names]   # ③ 可用池(锁定类型不再出现)
                ok = 0
                for _ in range(self.REFORGE_TRIALS):
                    new_score, new_w = 0.0, 0.0
                    for nm in rng.sample(pool, need):
                        tiers, tprobs, coef, w = feat[nm]
                        if not tiers:
                            continue
                        new_score += rng.choices(tiers, weights=tprobs)[0] * coef
                        new_w += w
                    a_after = 10 * (locked_w + new_w)
                    if a_after >= base and locked_score + new_score >= a_after:
                        ok += 1
                p_pass = ok / self.REFORGE_TRIALS
                if p_pass < self.REFORGE_MIN_PROB:
                    continue
                units = max(1, limit - 1)          # 官方: 锁 1~2 条按 1 个计
                cost = units * self.REFORGE_PRICE
                plan = {
                    'lock': locked_names,
                    'refresh': need,
                    'units': units,
                    'cost': cost,
                    # 参考策略工坊的"期望消耗"口径: 这是"每次成本 / 本次达标概率"的几何近似,
                    # 只用于报告对照(判定仍是 P >= REFORGE_MIN_PROB 的硬门, 不改选法)。
                    'expected_units': round(units / p_pass, 2),
                    'expected_cost': round(cost / p_pass, 1),
                    'p_pass': round(p_pass, 3),
                    'trials': self.REFORGE_TRIALS,
                    'e_feat': round(e_feat, 2),
                    'rbar': round(rbar, 3),
                    'a_after': round(10 * sw_after, 1),
                    'expected': round(locked_score + need * e_feat, 2),
                }
                if best is None or (plan['cost'], -plan['p_pass']) < (best['cost'], -best['p_pass']):
                    best = plan
        return best

    @staticmethod
    def dedup_key(echo_name, paired_all):
        """去重签名 = 声骸名 + 全部属性行的档位值(薄封装, 实现见 `src.echo_parse.dedup_key`)。

        档位值是离散集合 → 同一声骸多次识别一致, 跨屏重叠时才拦得住(`seen_sigs`)。
        名字先去掉间隔号/空白/中点(`双极·` / `双极・` 是同一只)。
        评估遍历与 tools/offline_eval_report 共用这一份。
        """
        return echo_parse.dedup_key(echo_name, paired_all)

    def evaluate_one(self, echo_name, stats, set_name, set_src, main_props=None, cost=None,
                     level=None):
        """一只声骸 → 报告记录字段(不含 index/screenshot): 评分 + 判定 + 前瞻 + 重铸方案 + 词条明细。

        **评估遍历与离线重放(tools/offline_eval_report)共用这一份** —— 以前两边各写一遍
        (score / judge / prospect / reforge / stats 明细), 改判定时容易只改一边、离线报告与线上不一致。
        调用方负责: 取数(OCR 或转录)、套装映射(resolve_set_name / pick_set)、截图、index。

        `main_props` / `cost` / `level` 是**可选**的 L2 输入(面板前 2 行主属性 + COST 角标 + 等级 `+NN`):
        不传则记录里不出现 `cost`/`main_props`/`plan_check`/`level`/`stats_missing` 这些键 ——
        旧报告与旧调用方行为完全不变。
        `level` 只影响 **tier**(= 是否满级), 见 `_tier_from_level`; 等级 > 词条数时另记
        `stats_missing`(漏读几条), 因为那份分数只是下界。
        """
        tier = _tier_from_level(level, len(stats))
        missing = tier - len(stats)
        # compute_weighted_score 内部会 parse_number(value_str), 需传字符串; 显式传套装名让其用映射套装权重
        score, details = self.compute_weighted_score([(n, str(v)) for n, v in stats], set_name=set_name)
        # **通用评分(散件口径)**: 同一批词条按"散件权重"再算一遍 —— 主属性是 攻/生/防 时
        # **只启用该族**的百分比+固定(生命主属性的件, 攻击%/固定攻击的副词条没有意义);
        # 专伤不知道角色类型 → 统一 0.2(低于固定攻击、远低于攻击%)。**不参与判定**。
        if main_props:
            _gw = generic_weights_for_main(str(main_props[0][0]))
        else:
            _gw = DEFAULT_WEIGHTS       # 旧记录/离线无主属性 → 保持旧通用口径
        generic_score, _generic_details = self.compute_weighted_score(
            [(n, str(v)) for n, v in stats], weights=_gw)
        if missing > 0:
            # 读数不全(等级说还有词条没读到): 这份分数只是**下界**, 任何"丢/练"的判断都不可靠 ——
            #   ① 不能判"不合格": 漏读的那条可能正好让它达标(实测那只少了一条暴击 7.5 → 17.29 不合格,
            #      补上后 27.29 达标);
            #   ② 不能给重铸建议: reforge_plan 按"5 个孔"建模, 少一条会把它当成空孔, 方案是错的。
            # 所以统一给"保留(词条缺失)": 先留着别丢, 报告里带 ⚠ 让人复读这一只。
            # 也不跑 judge_echo —— 那里的两处概率门(重铸/前瞻)在缺条时都没有意义(重铸还要 0.2s 蒙特卡洛)。
            verdict, verdict_cn, threshold, reforge = 'hold', '保留(词条缺失)', 0.0, None
        else:
            # 判定与渐进强化共用同一份逻辑 (见 judge_echo); 第三项 = 「建议重铸」的最优方案(内部已算)
            (verdict, verdict_cn), threshold, reforge = self.judge_echo(set_name, tier, score, stats)
        # 未满级的"建议强化": 记下"继续开到满级能过保留线"的概率(前瞻), 供报告展示与核对
        prospect = (round(self.enchant_prospect(set_name, tier, stats) or 0, 3)
                    if verdict == 'pending' and tier < 5 else None)
        rec = {
            # name 用容错匹配到的**规范名**(如 `冠顶械集` → `冠顶械隼`), 拿不准时沿用 OCR 原文;
            # name_raw 保留 OCR 原文供追溯(报告里作 title)
            "name": normalize_echo_name(echo_name) or echo_name, "name_raw": echo_name,
            "tier": tier, "score": round(score, 2), "score_generic": round(generic_score, 2),
            "threshold": threshold, "verdict": verdict, "verdict_cn": verdict_cn,
            "set": set_name, "set_src": set_src,
            "prospect": prospect, "reforge": reforge,
            "stats": [{"name": n, "value": float(v), "detail": d,
                       "ratio": round((snap_to_tier(n, v) or 0) / (get_mean(n) or 1), 3)}
                      for (n, v), d in zip(stats, details)],
        }
        # 等级 / 漏读条数: 只在**有值**时加键(与 cost/main_props 同样的"加法"约定, 旧报告不受影响)
        if level is not None:
            rec["level"] = int(level)
        if tier > len(stats):
            rec["stats_missing"] = tier - len(stats)
        # L2: 主属性 / COST / 官方管理方案判定 —— 全部可选, 不给就一个键都不加(旧报告不受影响)
        # COST 主口径 = **第 2 行(COST 固有属性)结构反推**(分辨率无关); 角标 OCR 只当佐证,
        # 反推不出唯一值时才退回它, 两者冲突时以反推为准(角标"4 读成 A"这类误读更常见)。
        badge_cost = cost if cost in (1, 3, 4) else None
        if main_props:
            from src.echo_inventory import infer_cost, normalize_main_prop
            rows = list(main_props)[:2]
            # 等级 `+NN` 是比词条数更硬的信号: 有它就按那一点取网格(唯一), 没有才用词条数窗口。
            # 2026-11-20 report3 #145: 只给 tier=1 的窗口(+5..+25)时, +5 的 `攻击 54.0`(4C 固有)
            # 与 +11 的 `55.0`(3C 固有)只差 1.0, 正好落在 TOL_FLAT 内 → 反推"不唯一" → 整条缺 COST。
            inferred = infer_cost(
                [(normalize_main_prop(n, v, level, tier), parse_number(v)) for n, v in rows],
                level=level, tier=tier)
            if inferred not in (1, 3, 4) and level is not None:
                # 等级 OCR 读错(如 +15 认成 +16)时, 按等级取网格会全不中 → 退回词条数窗口(旧行为)
                inferred = infer_cost(
                    [(normalize_main_prop(n, v, None, tier), parse_number(v)) for n, v in rows],
                    tier=tier)
            if inferred in (1, 3, 4):
                cost = inferred
                rec["cost_src"] = "main"
                if badge_cost and badge_cost != inferred:
                    self.log_debug(f'[COST] 角标 {badge_cost} 与主属性反推 {inferred} 不一致, 采用反推'
                                   f' ({echo_name})')
            elif badge_cost:
                cost = badge_cost
                rec["cost_src"] = "badge"
        elif badge_cost:
            cost = badge_cost
            rec["cost_src"] = "badge"
        if cost in (1, 3, 4):
            rec["cost"] = cost
        if main_props:
            rec["main_props"] = [{"name": n, "value": parse_number(v)}
                                 for n, v in list(main_props)[:2]]
            pc = self.check_main_prop(set_name, cost, main_props)
            if pc:
                rec["plan_check"] = pc
            # 数值校验(官方 5★ 主属性网格 + 用词条数推出的等级窗口): 只记**不合法**的, 报告里标 ⚠
            bad = [m for m in check_main_values(main_props, tier) if m.get("ok") is False]
            if bad:
                rec["main_values_check"] = bad
        return rec

    @staticmethod
    def _struct_first_ok(set_name, stats) -> tuple[bool, str]:
        """Lv5/Lv10 结构判定 —— **只看首条词条**(stats[0]), 返回 (是否通过, 原因)。

        规则(2026-11 用户口径, 语义 1 + 可选低权重门槛):
          ① 首条必须是该套装的"有效词条"(权重 > 0; 通用模式同样);
          ② 若该套装配置了 `_low_first`(`{"below": 权重上限, "top": 前 N 档}`)
             且首条权重 ≤ below → 首条必须落在该词条档位表的**前 top 档**(降序);
             否则即使它同时是核心词条也不过(低权重低档位不值得继续投入);
          ③ 未触发 ② 时, 首条必须在 `_core_first` 内(缺省 = 全部有效词条)。

        为什么只认首条: UI 一直把它叫"首条核心词条"; 旧实现用 `any(...)` 让第二条兜底,
        使得"首条废、第二条好"的件在 Lv10 也能过。**低权重门槛按套装可选**:
        只有像轻云出月这样带 0.1 占位键的套装才配置, 其余套装行为不变。
        """
        if not stats:
            return False, '无词条'
        name, value = stats[0]
        weights = DEFAULT_WEIGHTS if (not set_name or set_name == '通用') else (get_set_weights(set_name) or {})
        w = weights.get(name, 0.0)
        low = get_set_low_first(set_name)
        if low and 0 < w <= low['below'] + 1e-9:
            rank = tier_index(name, value)
            if rank is not None and rank < low['top']:
                return True, ''
            return False, f'低权重首条档位不足_{name}={value}(需前{low["top"]}档)'
        if w <= 0:
            return False, f'首条无效_{name}'
        if set_name == '通用' or name in (get_set_core_first(set_name) or []):
            return True, ''
        return False, f'首条非核心_{name}'

    def judge_echo(self, set_name, tier, score, stats):
        """公共判定(评估与渐进强化共用): 返回 ((verdict, verdict_cn), threshold, reforge)。
        Lv5/Lv10 (1-2 词条): 结构判定——**只看首条**(stats[0]), 见 `_struct_first_ok`:
          首条在 `_core_first` 内(缺省=全部有效词条; 通用=weight>0)即过, 不限分;
          若该套装配置了 `_low_first` 且首条是低权重词条, 还要求它位于前 N 档。
          文案与 Lv15/Lv20 统一为「建议强化/不建议强化」。
        满级: (aim ≥ base 且 score ≥ aim) → pass达标; score ≥ base → hold保留;
              score < base 时再看"花频整器能不能把它**刷成达标**"(reforge_plan: 存在
              **蒙特卡洛达标概率 ≥ REFORGE_MIN_PROB(0.60)** 的锁定方案, 取成本最低者)
              → keep建议重铸; 否则 fail不合格
        未满级: score ≥ base(满级) → pending建议强化; 未过线但"继续开到满级能过保留线"的概率 ≥
          ENCHANT_MIN_PROB(0.60) **且** score ≥ aim → pending(建议强化); 否则 fail(不建议强化)
        aim = _tier_threshold(10 × 出现有效词条权重之和) —— **不取 max(aim, base)**:
          aim < base 说明"出现有效词条太少", 这只最高只能到"保留"; base = _legacy_threshold(旧规则线);
        强化流程不豁免(不达标仍丢弃), keep/hold 仅评估报告标注。
        第三项 **reforge** = 「建议重铸」时那个最优锁定方案(其余档位为 None)。判定内部本来就要算
          reforge_plan(穷举锁定组合 + 蒙特卡洛, 单次约 0.2 秒) —— 直接带出来给报告用, 不让调用方重算。
        """
        if tier <= 2:
            ok, _ = self._struct_first_ok(set_name, stats)
            return (('pending', '建议强化') if ok else ('fail', '不建议强化')), 0.0, None
        aim = _tier_threshold(set_name, tier, stats)      # 达标线 = 10 × 出现有效词条权重之和
        base = _legacy_threshold(set_name, tier)          # 基准门槛 = 套装有效键最低 tier-1 条之和 ×10
        if tier >= 5:                                     # 满级
            if aim >= base and score >= aim:              # 达标: 达标线本身也要在基准线之上
                return ('pass', '达标'), aim, None
            if score >= base:                             # 过了基准门槛(含 A<B 的情形) → 保留(值得留着)
                return ('hold', '保留'), aim, None
            # 基准线以下 → 只有"花频整器能刷成达标"才留。reforge_plan 只返回**蒙特卡洛达标概率 ≥
            # REFORGE_MIN_PROB(0.60)** 的最省成本方案, 所以这里直接判它是否存在 —— "只刷成一个保留档位不值得"。
            plan = self.reforge_plan(set_name, stats)
            if plan:
                return ('keep', '建议重铸'), aim, plan
            return ('fail', '不合格'), aim, None
        # 未满级: 分两级 —— **建议强化 / 不建议强化**(素材有限, 要在没前途的件上及时止损)
        #   判据 = ① 已够满级保留线(稳了) 或 ② 前瞻概率够 **且** 现有词条档位已达平均档
        #   ② 的 `score ≥ aim` 是"现有几条词条自己站得住": 只看前瞻会放过"权重低但档位好"的件
        #   (如 3.10 分却因 A=2.5 而"过 A"), 而只看 A 又会杀掉"已过线只是略低于平均档"的件 —— 故取"或已过线"。
        #   基准用 **B(满级)** 而非 B(tier): 后者只回答"这一级够不够看", 与"最终能不能留"不是一回事。
        base5 = _legacy_threshold(set_name, 5)
        if score >= base5:                                # ① 已够满级保留线 → 稳了
            return ('pending', '建议强化'), base5, None
        p = self.enchant_prospect(set_name, tier, stats)  # ② 前瞻: 继续开完能否达到满级保留线
        if p is not None and p >= self.ENCHANT_MIN_PROB and score >= aim:
            return ('pending', '建议强化'), base5, None
        return ('fail', '不建议强化'), base5, None

    def compute_weighted_score(self, paired_stats, set_name=None, weights=None):
        """评分(薄封装, 实现见 `src.echo_scoring.compute_weighted_score`)。

        条分 = 档位值 ÷ 期望值 × 10 × 权重, 无效 0 分; 期望 = `echo_stats.get_mean` 的官方概率期望档位值。
        权重来源: 套装 JSON (`get_set_weights`); 通用模式用 `DEFAULT_WEIGHTS` 表;
        `weights` 显式给一套权重(散件评分按主属性族算时用 `generic_weights_for_main`)。
        set_name: 显式指定套装名(评估按声骸名映射时用); None 时回退 config['当前套装'] ——
        这一句是任务运行时状态, 所以留在 adapter 侧, 纯计算在 domain 模块。
        """
        if set_name is None and weights is None:
            set_name = self.config.get('当前套装', '通用')
        return echo_scoring.compute_weighted_score(paired_stats, set_name, weights)

    def find_add_mat(self):
        return self.wait_ocr(0.09, 0.6, 0.38, 0.86, match=['阶段放入'], time_out=1)

    def esc(self):
        start = time.time()
        while not self.find_echo_enhance() and time.time() - start < 10:
            self.send_key('esc', interval=4, after_sleep=0.2)
        self.sleep(0.1)

    def trash_and_esc(self):
        self.info_incr('失败声骸数量')
        start = time.time()
        success = False
        while time.time() - start < 5:
            drop_status = self.find_best_match_in_box(self.get_box_by_name('echo_dropped').scale(1.05),
                                                      ['echo_dropped', 'echo_not_dropped'], threshold=0.7)
            if not drop_status:
                raise Exception('无法找到声骸弃置状态!')
            if drop_status.name == 'echo_not_dropped':
                self.send_key('z', after_sleep=1)
            else:
                self.log_info('成功弃置!')
                success = True
                break
        if not success:
            raise Exception('弃置失败!')
        safe_reason = re.sub(r'[<>:"/\\|?*]', '', self.fail_reason)
        self.screenshot_echo(f'failed/{self.info_get("失败声骸数量")}_{safe_reason}')
        self.esc()
        self.log_info('不符合条件 丢弃')
        self.wait_ocr(0.82, 0.86, 0.97, 0.96, match='培养', settle_time=0.1)

    def screenshot_echo(self, name):
        echo = self.box_of_screen(0.09, 0.09, 0.37, 0.55).crop_frame(self.frame)
        self.screenshot(name=name, frame=echo)

    def lock_and_esc(self):
        self.info_incr('成功声骸数量')
        start = time.time()
        success = False
        lock_status_box = get_bounding_box([
            self.get_box_by_name('echo_locked'),
            self.get_box_by_name('echo_not_locked'),
        ]).scale(1.05)
        while time.time() - start < 5:
            drop_status = self.find_best_match_in_box(lock_status_box,
                                                      ['echo_locked', 'echo_not_locked'], threshold=0.7)
            if not drop_status:
                raise Exception('无法找到声骸上锁状态!')
            if drop_status.name == 'echo_not_locked':
                self.send_key('c', after_sleep=1)
            else:
                self.log_info('成功上锁!')
                success = True
                break
        if not success:
            raise Exception('上锁失败!')
        self.screenshot_echo(f'success/{self.info_get("成功声骸数量")}')
        self.log_info('成功上锁!')
        if self.config.get('成功后暂停'):
            self.log_info('符合条件的声骸，已暂停任务', notify=True)
            self.pause()
        self.esc()
        self.wait_ocr(0.82, 0.86, 0.97, 0.96, match='培养', settle_time=0.1)
