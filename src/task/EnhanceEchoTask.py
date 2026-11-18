# EnhanceEchoTask.py
import re
import threading
import time
import os

import cv2

from ww_engine import FindFeature, Logger, clear_folder, get_bounding_box
from src import echo_parse, echo_scoring
from src import echo_grid
from src.echo_parse import parse_number  # noqa: F401  (旧调用面: from src.task.EnhanceEchoTask import parse_number)
from src.echo_stats import (snap_to_tier, get_mean, is_stat_match,
                            tier_index, DEFAULT_WEIGHTS)  # noqa
from src.echo_main_prop import check_main_values
from src.echo_set_templates import (STAT_ORDER, get_all_set_names, get_set_weights, match_set_effect, match_set_text,
                                    get_set_core_first, get_set_low_first,
                                    get_sets_by_echo, normalize_echo_name, load_gamedata)
from src.echo_icon_match import (match_icon, MIN_MARGIN, MIN_SCORE,
                                 badge_hue, filter_by_set_hue, hue_group)
from src.task.BaseEchoTask import BaseEchoTask

logger = Logger.get_logger(__name__)

number_pattern = re.compile(r"^[\d.%％ ]+$")
property_pattern = re.compile(r"[\u4e00-\u9fff]{2,}")

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

# 注: 旧的"好词条"分位阈值常量 `HI_PERCENTILE` 已废弃 —— "建议重铸"档不再数"好词条条数",
# 改为按 `reforge_plan` 的"锁 N 条刷 M 条期望分"判定(见 judge_echo)。分位本身仍用于报告展示词条的
# `[前 X%]`(`echo_stats.tier_percentile`): 官方档位概率不等, 分位是唯一跨词条可比的度量
# (旧口径"档位值/期望 ≥ 1.0"在暴击上覆盖前 53.33%、暴击伤害仅前 30.00%, 口径并不一致)。
# 频整器成本见 `EnhanceEchoTask.REFORGE_PRICE`(官方: 锁 L 条 = L−1 个, 锁 1~2 条按 1 个计)。


def _legacy_threshold(set_name: str, tier: int) -> float:
    """基准门槛 B = 该套装有效键权重升序最低 (tier-1) 条 ×10 之和。
    通用模式走 _GENERAL_WEIGHTS 代表集 → tier=5 时为 (0.25+0.4+0.5+0.6)×10 = 17.5。
    注意: 它作为"基准门槛"用, 但**单独作达标线已废弃** —— "键多但权重低"的套装(隐世回光/轻云出月)
    会被压到 5~6 分(见 _tier_threshold 注释)。"""
    if tier <= 2:
        return 0.0
    src = _GENERAL_WEIGHTS if (not set_name or set_name == '通用')         else tuple((get_set_weights(set_name) or {}).values())
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
        先对两侧按 y 排序: OCR 返回顺序不保证有序, 不排序则"前 2 行=主属性"等行序语义会错。"""
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
                cv2.imwrite(path, frame)
                return path
        except Exception as e:                     # noqa: BLE001 - 存图失败不该掩盖原始错误
            self.log_debug(f'保存失败画面失败: {e}')
        return ''

    def resolve_set_name(self, echo_name: str, badge=None, effect_set=None) -> tuple[str, str]:
        """评估用: 声骸名 + 套装硬信号 → (套装名, 来源)。

        信号优先级(2026-11-14 迭代后的现状):
        ① **详情面板图标**(旧 UI, 3.x 已无): 高置信直接用, 可纠正名字候选;
        ② **合鸣效果文本**(`effect_set`): 详情面板滚到底能读到 2/5 件套效果描述(没有套装名),
           用效果文本反查套装 —— 文本信号最稳, 且调用方已按名字候选约束过;
        ③ **卡片徽章环色**(`badge=(hue|None, ok)`): 名字多个候选时用环色过滤(85% 可唯一定位);
        ④ 名字候选(config 套装在候选内则优先) → ⑤ config(评估=通用)。
        来源 'icon'/'effect'/'hue'/'name'/'default' 记入报告, 便于离线核对。
        """
        cfg_set = self.config.get('当前套装', '通用')
        cands = get_sets_by_echo(echo_name)
        if effect_set and (not cands or effect_set in cands):
            self.log_debug(f'[套装效果文本] {echo_name} → {effect_set} (名字候选 {cands})')
            return effect_set, 'effect'
        icon_set, score, margin = match_icon(self.frame)
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
        tmp_dir = tempfile.mkdtemp(prefix="okecho_eval_")
        ss_dir = os.path.join(tmp_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        # 网格角标 OCR 区 / 右侧详情面板区。所有坐标均用归一化比例(除以帧宽高), 分辨率无关;
        #   1920x1200 帧换算参考: 名字 y≈0.10, COST y≈0.21, 主属性 y≈0.37/0.42, 词条 y≈0.45..0.61(第5条),
        #   "声骸技能"行 y≈0.62 由 read_detail 按行过滤; "前 2 行=主属性"是相对行序判断, 不依赖帧高
        grid_box = (0.10, 0.15, 0.72, 0.92)
        detail_box = (0.66, 0.10, 0.995, 0.635)

        seen_sigs = set()          # 已处理声骸的去重签名(名字+全行档位值, 防滚动重叠漏拦)
        seen_stat_sigs = set()     # 只按属性行(不含名字)的去重签名: OCR 名字抖动(无常凶驾/无常冈驾)时防重复记录
        last_sig = None            # 上一次成功处理的详情全量签名(判点选未切换)
        no_new_screen = 0          # 连续滚动后无新格的次数 → 到底
        empty_scan = 0             # 网格区连续扫描为空的次数 → 真到底(0级角标 +0 也能被识别, 空=列表底)
        stop_all = False           # 到底 / 0 级尾部 → 正常收尾并输出报告
        zero_run = 0               # 连续 0 词条格数(排序正确时 0 级在尾部, 可提前结束)
        ZERO_TAIL_STOP = 12        # 连续两行(6 列 ×2) 0 词条 → 视为 0 级尾部
        # ── 滚动调参(2026-11-14 真机实测后定的量) ────────────────────────────
        SCROLL_TARGET_ROWS = 3.0    # 每次滚 3 行(可见 5 行 → 留 ~2 行重叠, 滚过头也还有 1 行缓冲)
        SCROLL_SETTLE_STEP = 0.15   # 位移采样间隔(动画期间轮询)
        SCROLL_SETTLE_TIMEOUT = 3.0  # 等画面静止的最长时间(真机 ease-in 动画约 1s 收尾)
        SCROLL_STILL_RATIO = 0.02   # 相邻两帧变化像素占比 < 此值 = 画面静止(动画结束)
        SHIFT_DIFF_OK = 18.0        # 对齐残差 ≤ 此值才认为位移可信
        SCROLL_CHANGE_MIN = 0.12    # 画面变化占比 < 此值 = 什么都没发生(只有悬停/选中框)
        SCROLL_FIRST_ROWS = 2.5     # 首滚上限(px/格还没实测过, 保守一点, 漏行比多滚贵)
        SCROLL_SAFETY = 0.95        # 距离打 95 折发送: 欠滚可由补滚补齐, 过滚会整行漏
        SET_PANEL_STEP = 6          # 找套装时每次只滚 6 格(小步: 大步会一步跨过目标文本)
        SET_PANEL_FIRST_STEP = 12   # 但第一步放大: 主词条区肯定没有套装名, 先跳过那一段
        SET_PANEL_MAX_STEPS = 9     # 12 + 8×6 = 60 格上限

        grid_pitch = {'row': None, 'col': None}   # 上一屏的列/行间距(像素), 本屏角标漏检时用于推断
        layout_model = None      # 网格布局模型(比例): 首屏标定后跨屏复用, 后续屏幕只需行检测
        # 滚轮距离模型: px/格 随窗口缩放(8.0 是 1920 宽帧的实测值)
        scroll_model = echo_grid.ScrollModel(
            frame_width=float(getattr(self.executor.method, 'width', 0) or 1920.0))
        scroll_fail = 0          # 连续滚动受阻次数(>=2 中止, 绝不空转)
        screens_done = 0         # 已扫完的屏数(首屏"0 重复"是正常的, 守卫要跳过它)
        back_steps = 0           # 本屏"滚过头"后的回滚次数(每屏最多 2 次, 防来回拉锯)

        # ── debug 数据集: 每格存 全屏原图/ROI框叠图 + detail/grid/count 区域裁剪, 每次 OCR 结果
        #    记入 ocr_text.txt —— 离线核对坐标与 OCR 输入输出, 无需重开云游戏。
        #    输出目录 logs/eval_debug/<时间戳>/, 独立于报告临时目录, 不随报告删除(约1GB/200声骸)。
        dbg_dir = None
        dbg_no = 0
        if SAVE_DEBUG_DATASET:   # 见模块级开关注释(默认关, 避免 GB 级磁盘占用)
            dbg_dir = os.path.join('logs', 'eval_debug', time.strftime('%Y%m%d_%H%M%S'))
            os.makedirs(dbg_dir, exist_ok=True)

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
            cv2.imwrite(os.path.join(dbg_dir, f'{tag}_full.png'), frame)
            boxed = frame.copy()
            for box, color in ((detail_box, (0, 0, 255)), (grid_box, (0, 255, 0))):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                cv2.rectangle(boxed, (x1, y1), (x2, y2), color, max(2, fw // 600))
            cv2.imwrite(os.path.join(dbg_dir, f'{tag}_boxes.png'), boxed)
            for name, box in (('detail', detail_box), ('grid', grid_box)):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                cv2.imwrite(os.path.join(dbg_dir, f'{tag}_{name}.png'), frame[y1:y2, x1:x2])

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
            """寻套装文本用的 OCR 区：**整块详情面板**（含最下面的合鸣效果区）。

            为什么不用 `detail_box`（下界 0.635）：那是给"读词条"用的，只覆盖面板上半截；
            用户实测合鸣效果/套装名落在面板下半截（截图里 y≈0.45~0.55 帧高，长描述还会更低），
            OCR 框不放开就会出现"滚了但读不到"。
            """
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            return (0.66 * fw, 0.08 * fh, 0.995 * fw, 0.95 * fh)

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

        @staticmethod
        def _has_heading(texts, word):
            """OCR 里有没有这个标题（合鸣效果 / 声骸技能）。容 鸣↔呜 这类单字误读。"""
            for b in texts or []:
                line = ''.join(ch for ch in str(getattr(b, 'name', '') or '')
                               if '\u4e00' <= ch <= '\u9fff')
                if word in line or (len(word) >= 2 and word[0] + word[2:] in line):
                    return True
                if word == '合鸣效果' and ('合鸣' in line or '合呜' in line):
                    return True
            return False

        def read_set_by_effect(cands):
            """滚详情面板找套装：**套装名文字优先**（合鸣效果区每条都会写套装名），
            其次按合鸣效果原文反查；以 **OCR 标题锚点** 判"到位没到位"，不用固定格数/像素静止。

            用户实测（2026-11-18 三张截图）：面板往下依次是 声骸技能描述 → 合鸣效果，
            合鸣效果区第一行就是 `雪落无声之愿` 这样的套装名（2/5 件套各一行），长描述在下面。
            所以"看到 合鸣效果 标题 + 匹配到名字"就是成功；两者都没有就继续滚（上限 6×10 格）。
            """
            best = (None, 0.0, 0.0)
            total = 0
            box = _effect_box_px()
            prev = self.frame
            still = 0
            seen_heading = None

            def _name_own_line(texts, name):
                """套装名是否**独占一行**。

                官方套装分两类：2+5 件套（套装名在合鸣效果区出现**两次**）/ 单条目（1 或 3 件，
                只出现一次）。不管几次，它都是**单独一行**（后面跟个图标）。所以"独占一行"既能
                确认已经滚到合鸣效果区（哪怕标题已经滚出视野），又能挡掉技能描述里偶然出现的套装名。
                """
                for b in texts or []:
                    line = ''.join(ch for ch in str(getattr(b, 'name', '') or '')
                                   if '\u4e00' <= ch <= '\u9fff')
                    if line == name:
                        return True
                return False

            try:
                for step in range(SET_PANEL_MAX_STEPS):
                    advance = SET_PANEL_FIRST_STEP if step == 0 else SET_PANEL_STEP
                    if not _panel_scroll(-advance):
                        break
                    total += advance
                    self.sleep(0.16)
                    cur = self.frame
                    texts = self.ocr(*box)
                    dbg_ocr(f'effect{step}', texts)
                    if _has_heading(texts, '合鸣效果'):
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
                        best = (named, 1.0, 0.0)
                        break
                    named = None
                    cand, s1, s2 = match_set_effect(texts, cands)
                    if cand:
                        self.log_info(f'[套装] 按合鸣效果文本命中: {cand} '
                                      f'(覆盖 {s1:.2f} / 次优 {s2:.2f}, 滚 {total} 格)')
                        best = (cand, s1, s2)
                        break
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
                    _panel_scroll(total)               # 滚回顶部
                    self.sleep(0.25)
                    for _ in range(2):
                        if self._panel_has_name():
                            break
                        self.log_debug('面板未回顶, 再向上滚一次')
                        _panel_scroll(total)
                        self.sleep(0.30)
            return best

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

        def _measure_shift(before, pitch, rect):
            """等滚动动画**停稳**再量位移 → (rows, diff, change_ratio, seconds)。

            判据同 `_wait_still`：看**相邻两帧**是否还在变，而不是看位移读数是否"稳定"
            （ease-in 动画的慢启动会让位移读数长时间停在很小的值上）。
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
            # 目标行数随**可见行数**收缩：1440x900 实测只看到 4 行(6 列 × 4 行)，
            # 若仍按"5 行可见"滚 3 行，就只剩 1 行重叠，一次偏差就跳行。
            visible = int(grid_pitch.get('nrows') or 5)
            rows = min(rows, max(1.5, visible - 1.8))
            rect = _grid_rect_px()
            before = _wait_still(rect)      # 先等上一屏的收尾动画停下来, 否则基准帧是糊的
            total = 0.0
            used = None
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
                moved, diff, change, secs = _measure_shift(before, pitch, rect)
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
                moved, diff, change, secs = _measure_shift(before, pitch, rect)
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

        def read_detail():
            """OCR 右侧详情面板。返回 (echo_name, paired_all, detail_sig, cost):
              echo_name  声骸名(面板顶部唯一中文行, y < 0.28*fh; 用于签名唯一性)
              paired_all 全部属性行 [(name, value_str), ...]  (主属性+词条, 按 y 序)
              detail_sig 名字 + 全量属性行签名(点选切换/唯一性检测)
              cost       面板 COST 角标(1/3/4; 认不出为 None)
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
            cost = parse_cost(texts)
            if cost is None:
                # 全屏 OCR 把数字框整个漏掉时(实测 27/135) → 只截角标区放大重读一次
                cost = self.read_cost_badge()
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
            if not properties:
                return echo_name, [], '', cost
            paired_all = self._pair_props(properties, values)
            detail_sig = f'{echo_name}|' + '|'.join(f'{n}={v}' for n, v in paired_all)
            return echo_name, paired_all, detail_sig, cost

        try:
            # 键数硬拒: 套装有效词条 <5 不允许评估(通用跳过)
            ok, msg = self._check_set_keys(self.config.get('当前套装', '通用'))
            if not ok:
                raise Exception(msg)
            if dbg_dir:
                self.log_info(f'调试数据集目录: {os.path.abspath(dbg_dir)}', notify=True)
            self.log_info('评估遍历: 不识别声骸数量, 直到「连续两行 0 词条 / 网格为空」结束')
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
            # 先读一次当前详情面板作为基线: 第一次点击若没生效(点在空白/边框),
            # 面板还是上一次选中的声骸 → 会被误记成本屏第一只(实测报告 #1 变成了之前手选的那只)
            try:
                _, _, last_sig, _ = read_detail()
            except Exception as e:
                self.log_debug(f'读初始详情失败(忽略): {e}')

            while not stop_all:
                if self.stop_requested():
                    stopped = True
                    self.log_info('已请求停止, 结束评估(未生成报告)')
                    break
                cells = scan_grid()
                if not cells:
                    # 网格区 OCR 不到角标: 0级角标 +0 也能被识别, 连续为空 ≈ 列表真到底;
                    # 首屏即空(且一个都未记录)才 raise, 提示可能不在背包界面
                    empty_scan += 1
                    fail_shot = self._save_fail_frame() if empty_scan == 1 else ''
                    if empty_scan >= 2:
                        if evaluated == 0 and not results:
                            raise Exception(
                                '未在背包界面检测到声骸网格(角标/结构线)。'
                                + (f'\n当时抓到的画面已存: {fail_shot}'
                                   '\n若那张图里不是背包列表（例如是控制台/桌面），说明游戏被别的窗口挡住了 ——'
                                   '这版截图会抓到遮挡窗口，请把游戏放最前面（或最小化 cmd）再试。'
                                   if fail_shot else ''))
                        self.log_info('到达背包底部(网格区无角标), 评估结束', notify=True)
                        break
                    scroll_grid()
                    self.sleep(0.6)
                    continue
                empty_scan = 0

                processed_any = False
                eval_before = evaluated
                dups = 0             # 本屏"重复/点空"格数 —— 与新增一起看可知重叠对不对
                zero_cells = 0       # 本屏 0 词条格数
                for nx, ny in cells:
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
                    click_points = ((nx, ny), (nx, max(0.02, ny + delta)))
                    for attempt, (cx, cy) in enumerate(click_points):
                        self.click(cx, cy, after_sleep=0.8)
                        dbg_shot(f'click_{cx:.2f}_{cy:.2f}')
                        echo_name, paired_all, sig, cost = read_detail()
                        if paired_all and sig != last_sig:
                            break
                        if attempt == 0:
                            self.log_debug(f'点选未切换 → 换行线另一侧重试: ({nx:.3f},{ny:.3f})')
                    # 属性行签名(不含名字): 名字 OCR 抖动(无常凶驾/无常冈驾/无常区鹭)时防重复记录
                    stat_key = '|'.join(f'{n}={round(parse_number(v), 1)}' for n, v in paired_all)
                    key = self.dedup_key(echo_name, paired_all) if paired_all else ''
                    if (not paired_all
                            or (last_sig is not None and sig == last_sig)
                            or (key and key in seen_sigs)
                            or (stat_key and stat_key in seen_stat_sigs)):
                        # 空格/点选未切换(行尾补全的空白格)/已处理过的声骸(滚动重叠/名字抖动)
                        # → 跳过本格继续。
                        # **不要"连续 8 格重复就提前滚屏"**（旧逻辑）：滚动只走 2~3 行时本屏前 2 行
                        # 都是重复，提前滚 4 行会把本屏还没扫的那些行**整段跳过**（漏行）。
                        # 卡住时不空转由 scroll_grid 返回 False + 连续 2 次中止兜底，不靠这里提前跳。
                        dups += 1
                        continue

                    processed_any = True
                    if stat_key:
                        seen_stat_sigs.add(stat_key)

                    # 词条筛选: 详情属性区已按 y 排序(_pair_props), 前 2 行固定为主属性(攻击/生命/防御等)——
                    # 按相对行序排除, 分辨率无关; 即使主属性固定值恰好命中词条档位
                    # (如 主属性生命=510 ∈ {510}, 防御=50 ∈ {50}) 也不会误收;
                    # 剩余行再叠加"数值≈档位集合"(离散匹配)才算词条, 最多 5 条
                    stats = []
                    for raw_n, v_str in paired_all[2:]:
                        norm = self._normalize_stat(raw_n, v_str)
                        val = parse_number(v_str)
                        if norm and is_stat_match(norm, val):
                            stats.append((norm, val))
                    stats = stats[:5]

                    tier = len(stats)
                    if stats:
                        zero_run = 0
                        # 套装 = 详情面板图标(硬信号)优先, 低置信回退"声骸名 → 候选套装"
                        # (名字多义 + OCR 错字在名字层无解, 见 resolve_set_name / CHANGELOG 阶段十二)
                        badge = badge_hue_at(nx, ny)
                        # 名字多义，或**名字根本没认出来**（OCR 错字 → 候选为空）时读「合鸣效果」；
                        # 只有"唯一候选"才省这一次滚动。实测 格洛玛图→格洛犸图 就属于后者，
                        # 跳过面板会直接落"通用"，而面板上明明写着套装名。
                        cand_list = get_sets_by_echo(echo_name) if echo_name else []
                        effect_set = None
                        if len(cand_list) != 1:
                            effect_set, _s1, _s2 = read_set_by_effect(cand_list)
                        set_name, set_src = self.resolve_set_name(echo_name, badge, effect_set)
                        # 评分 / 判定 / 前瞻 / 重铸方案 + 词条明细 → evaluate_one(与离线重放共用同一份实现)
                        # L2: 前 2 行主属性与 COST 角标一并交给它(报告据此标"官方管理方案"是否认可该主属性)
                        rec = self.evaluate_one(echo_name, stats, set_name, set_src,
                                                main_props=paired_all[:2], cost=cost)
                        # 徽章环色写进记录: 报告/JSON 自带证据, 事后可**离线核对套装判定**
                        rec['badge_hue'] = badge[0] if badge and badge[1] else None
                        verdict, verdict_cn, score = rec["verdict"], rec["verdict_cn"], rec["score"]
                    else:
                        # 0级声骸(0词条): 无评估价值——**跳过不记录、不终止**。
                        # 0级集中在列表底部, 置 processed_any 让它继续滚动推进(不触发"无新格"提前结束),
                        # 列表真到底由"网格连续为空(empty_scan)"判定; key 入 seen_sigs 防重叠重复扫。
                        processed_any = True
                        seen_sigs.add(key)
                        zero_run += 1
                        zero_cells += 1
                        self.log_debug(f'[评估跳过] {echo_name} | 0级(无词条)')
                        if zero_run >= ZERO_TAIL_STOP:
                            # 按等级排序时 0 级在列表尾部 → 连续两行 0 词条即视为到底, 不再往下点
                            self.log_info(f'连续 {zero_run} 格 0 词条, 视为 0 级尾部, 评估结束', notify=True)
                            stop_all = True
                        continue

                    last_sig = sig
                    seen_sigs.add(key)

                    ss_name = f"eval_{evaluated + 1:03d}_{verdict}_{score:.1f}.png"
                    ss_path = os.path.join(ss_dir, ss_name)
                    # 截图 = 右侧详情完整展示: 名字(y~122)/COST/主属性/词条(含第5, y~728)/声骸技能行
                    # 此前固定截网格左上角(0.09,0.09,0.37,0.55) → 与当前声骸无关, 已改为右侧面板
                    echo_img = self.box_of_screen(0.665, 0.07, 0.995, 0.65).crop_frame(self.frame)
                    cv2.imwrite(ss_path, echo_img)

                    # 记录字段来自 evaluate_one, 这里补报告用的序号与截图名
                    results.append({"index": evaluated + 1, "screenshot": ss_name, **rec})
                    self.log_info(f"[评估#{evaluated + 1}] {echo_name} | {tier}/5词条 | 得分={score:.2f} "
                                  f"| {verdict_cn} | 套装={set_name}({set_src})")
                    evaluated += 1
                    self.info_set('评估数量', evaluated)

                if stop_all or stopped:
                    break
                # 本屏小结: "新增 + 重复" 直接反映滚动重叠对不对(滚 3 行应剩 ~2 行重复)
                self.log_info(f'本屏完成: {len(cells)} 格, 新增 {evaluated - eval_before} 条, '
                              f'重复/点空 {dups} 格, 0词条 {zero_cells} 格')
                # ── 无重叠守卫(内容级，不依赖像素测量) ─────────────────────────
                # 非首屏却**一格重复都没有** = 这次滚过头了(≥5 行)，中间整行被跳过。
                # 像素测不准也能发现漏行：重复数是"真滚了几行"的直接证据。
                if screens_done >= 1 and dups == 0 and evaluated > 0 and back_steps < 2:
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
                            self.log_info('连续滚动无新内容, 评估结束', notify=True)
                            break
                else:
                    scroll_fail += 1
                    if scroll_fail >= 2:
                        self.log_warning(f'连续 {scroll_fail} 次滚动受阻, 评估中止'
                                         f'(已记录 {evaluated} 条, 生成部分报告)', notify=True)
                        stop_all = True
                        break
                self.sleep(1.2)

            if stopped:
                self.log_info(f'评估已停止, 本次已记录 {evaluated} 个声骸(不生成报告/不打开报告)', notify=True)
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return
            # 汇总 JSON(顶层 set = 本次评估的 config 套装; 逐条的 set/set_src 见 resolve_set_name)
            output_set = self.config.get('当前套装', '通用')
            output = {
                "set": output_set,
                "total": evaluated,
                "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "results": results,
            }
            json_path = os.path.join(tmp_dir, "eval_result.json")
            with open(json_path, "w", encoding="utf-8") as f:
                _json.dump(output, f, ensure_ascii=False, indent=2)

            self.log_info(f'评估完成, 共{evaluated}个声骸', notify=True)
            if on_done:
                self.handler.post(lambda: on_done(json_path, ss_dir))
        except Exception:
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
                    self.log_info('已是满级声骸, 跳过')
                    self.esc()
                    self.wait_ocr(0.82, 0.86, 0.97, 0.96, match='培养', settle_time=0.1)
                    continue
                elif len(properties) > 0:
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

            while True:
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

    def evaluate_one(self, echo_name, stats, set_name, set_src, main_props=None, cost=None):
        """一只声骸 → 报告记录字段(不含 index/screenshot): 评分 + 判定 + 前瞻 + 重铸方案 + 词条明细。

        **评估遍历与离线重放(tools/offline_eval_report)共用这一份** —— 以前两边各写一遍
        (score / judge / prospect / reforge / stats 明细), 改判定时容易只改一边、离线报告与线上不一致。
        调用方负责: 取数(OCR 或转录)、套装映射(resolve_set_name / pick_set)、截图、index。

        `main_props` / `cost` 是**可选**的 L2 输入(面板前 2 行主属性 + COST 角标): 不传则记录里
        不出现 `cost`/`main_props`/`plan_check` 三个键 —— 旧报告与旧调用方行为完全不变。
        """
        tier = len(stats)
        # compute_weighted_score 内部会 parse_number(value_str), 需传字符串; 显式传套装名让其用映射套装权重
        score, details = self.compute_weighted_score([(n, str(v)) for n, v in stats], set_name=set_name)
        # 判定与渐进强化共用同一份逻辑 (见 judge_echo); 第三项 = 「建议重铸」的最优方案(内部已算)
        (verdict, verdict_cn), threshold, reforge = self.judge_echo(set_name, tier, score, stats)
        # 未满级的"建议强化": 记下"继续开到满级能过保留线"的概率(前瞻), 供报告展示与核对
        prospect = (round(self.enchant_prospect(set_name, tier, stats) or 0, 3)
                    if verdict == 'pending' and tier < 5 else None)
        rec = {
            # name 用容错匹配到的**规范名**(如 `冠顶械集` → `冠顶械隼`), 拿不准时沿用 OCR 原文;
            # name_raw 保留 OCR 原文供追溯(报告里作 title)
            "name": normalize_echo_name(echo_name) or echo_name, "name_raw": echo_name,
            "tier": tier, "score": round(score, 2),
            "threshold": threshold, "verdict": verdict, "verdict_cn": verdict_cn,
            "set": set_name, "set_src": set_src,
            "prospect": prospect, "reforge": reforge,
            "stats": [{"name": n, "value": float(v), "detail": d,
                       "ratio": round((snap_to_tier(n, v) or 0) / (get_mean(n) or 1), 3)}
                      for (n, v), d in zip(stats, details)],
        }
        # L2: 主属性 / COST / 官方管理方案判定 —— 全部可选, 不给就一个键都不加(旧报告不受影响)
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

    def compute_weighted_score(self, paired_stats, set_name=None):
        """评分(薄封装, 实现见 `src.echo_scoring.compute_weighted_score`)。

        条分 = 档位值 ÷ 期望值 × 10 × 权重, 无效 0 分; 期望 = `echo_stats.get_mean` 的官方概率期望档位值。
        权重来源: 套装 JSON (`get_set_weights`); 通用模式用 `DEFAULT_WEIGHTS` 表。
        set_name: 显式指定套装名(评估按声骸名映射时用); None 时回退 config['当前套装'] ——
        这一句是任务运行时状态, 所以留在 adapter 侧, 纯计算在 domain 模块。
        """
        if set_name is None:
            set_name = self.config.get('当前套装', '通用')
        return echo_scoring.compute_weighted_score(paired_stats, set_name)

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
