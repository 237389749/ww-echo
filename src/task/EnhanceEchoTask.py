# EnhanceEchoTask.py
import re
import time
import os

import cv2
from qfluentwidgets import FluentIcon

from ok import FindFeature, Logger
from ok.feature.Box import get_bounding_box
from ok.util.file import clear_folder
from src.echo_stats import snap_to_tier, get_mean, is_stat_match, DEFAULT_WEIGHTS  # noqa
from src.echo_set_templates import (get_expected_stats, get_all_set_names, get_set_weights,
                                    get_set_core_first, get_set_by_echo, get_sets_by_echo)
from src.task.BaseEchoTask import BaseEchoTask

logger = Logger.get_logger(__name__)

number_pattern = re.compile(r"^[\d.%％ ]+$")
property_pattern = re.compile(r"[\u4e00-\u9fff]{2,}")

# OCR 词条名拆字污染的公共子串回退候选(优先级同 _normalize_stat 分支链)
_TIERS_ORDER = ['共鸣技能伤害加成', '共鸣解放伤害加成', '普攻伤害加成', '重击伤害加成', '暴击伤害',
                '共鸣效率', '攻击百分比', '生命百分比', '防御百分比', '攻击', '生命', '防御', '暴击']

# 逐字白名单: 全部标准词条名 + 常见主属性名的单字并集。
# OCR 把属性图标误识成汉字(艾攻击/众共鸣…)或拆字(共呜效率)时, 不在字典的字直接剥离。
_STAT_CHARS = set(''.join(_TIERS_ORDER) + '治疗效果加成')


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


def _tier_threshold(set_name: str, tier: int) -> float:
    """达标线 = 有效词条"平均档加权分"(10×权重)中最低 L 条之和, L = tier-1。
    Lv5/10(1-2 词条)返回 0 —— 判定走"有效词条条数"结构规则(见调用处), 不走分数。
    Lv15/20/25(L=2/3/4): 套装模式取套装键(weight>0)权重升序前 L 条 ×10 求和;
    通用模式取"角色适配集"6 种代表权重 [1.0,0.9,0.85,0.7,0.6,0.5]
    (暴击/爆伤/攻%类/共效/一种专伤/固定攻——专伤与固定三系各取一种, 因为通常只需要一条特定专伤)。
    键数 k < L 时取全部 k 条(评分上限按 k 收缩)。
    例: Lv15=5+6=11, Lv20=18, Lv25=26.5。"""
    if tier <= 2:
        return 0.0
    if set_name == '通用':
        weights = [1.0, 0.9, 0.85, 0.7, 0.6, 0.5]
    else:
        weights = [w for w in (get_set_weights(set_name) or {}).values() if w > 0]
    avg = sorted(10 * w for w in weights)
    need = min(tier - 1, len(avg))
    return round(sum(avg[:need]), 1)


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


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "批量强化声骸(游戏与okww语言必须为简体/繁体中文)"
        self.description = "点击B进入背包, 在过滤器中选择需要强化的声骸, 并按照等级从0排序后开始."
        self.icon = FluentIcon.ADD
        self.group_name = "批量强化声骸"
        self.group_icon = FluentIcon.ADD
        self.fail_reason = ""
        self.supported_languages = ["zh_CN", "zh_TW"]
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
        self.config_type["有效词条"] = {'type': "multi_selection",
                                        'options': ['暴击伤害', '暴击', '攻击百分比', '生命百分比', '防御百分比',
                                                    '攻击', '生命', '防御',
                                                    '共鸣效率', '普攻伤害加成',
                                                    '重击伤害加成', '共鸣解放伤害加成',
                                                    '共鸣技能伤害加成']}
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
            '强化策略': '传统: 满级后一次判断\n渐进式: Lv5/10 有首核即过 → Lv15/20/25 ≥ 锚线11/18/26.5, 不及格即停',
            '当前套装': '在"套装配置"tab中管理词条和权重',
            '启用评分模式': '条分=档位值÷均值×10×权重(每条上限12.5): 暴击1.0/爆伤0.9/攻%0.85/共效0.7/专伤0.6/固定三系0.5\n无效词条=0分',
            '最低得分>=': '传统模式满级5词条总分>=此值保留',
        }

    def evaluate_only(self, on_done=None):
        """
        评估模式 v2: 遍历背包声骸(每行6格) — 点格子→读右侧详情→评分记录→指纹去重→滚屏→到底结束。
        0 词条(全新0级/列表尾) 即认为到底, 结束。
        完成后调用 on_done(json_path, screenshot_dir)。
        """
        import json as _json, tempfile, shutil

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
        count_box = (0.02, 0.02, 0.25, 0.09)

        seen_sigs = set()          # 已处理声骸的去重签名(名字+全行档位值, 防滚动重叠漏拦)
        last_sig = None            # 上一次成功处理的详情全量签名(判点选未切换)
        no_new_screen = 0          # 连续滚动后无新格的次数 → 到底
        empty_scan = 0             # 网格区连续扫描为空的次数 → 真到底(0级角标 +0 也能被识别, 空=列表底)
        stop_all = False           # 到底/达上限 → 正常收尾并输出报告
        handled = 0                # 已记录数量(与左上总数比对做步数上限)
        total_limit = None         # 左上 "声骸N/3000" 的上限
        col_centers = []           # 6列基准 x(像素), 用于行内缺列补全防漏点

        # ── debug 数据集: 每格存 全屏原图/ROI框叠图 + detail/grid/count 区域裁剪, 每次 OCR 结果
        #    记入 ocr_text.txt —— 离线核对坐标与 OCR 输入输出, 无需重开云游戏。
        #    输出目录 logs/eval_debug/<时间戳>/, 独立于报告临时目录, 不随报告删除(约1GB/200声骸)。
        dbg_dir = None
        dbg_no = 0
        if True:   # 不需要数据集时改为 False
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
            for box, color in ((detail_box, (0, 0, 255)), (grid_box, (0, 255, 0)), (count_box, (255, 0, 0))):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                cv2.rectangle(boxed, (x1, y1), (x2, y2), color, max(2, fw // 600))
            cv2.imwrite(os.path.join(dbg_dir, f'{tag}_boxes.png'), boxed)
            for name, box in (('detail', detail_box), ('grid', grid_box), ('count', count_box)):
                x1, y1, x2, y2 = int(box[0] * fw), int(box[1] * fh), int(box[2] * fw), int(box[3] * fh)
                cv2.imwrite(os.path.join(dbg_dir, f'{tag}_{name}.png'), frame[y1:y2, x1:x2])

        def read_count():
            """OCR 左上 '声骸166/3000': 前者=背包声骸总数(或当前滚动位置), 后者=容量上限。
            返回**前者**作为步数上限(评估不得超过它); 失败返回 None。
            放大 OCR 防小字/斜杠被拆: 全部文本按坐标拼接后再解析; 无斜杠时取第一段数字。"""
            try:
                texts = self.ocr(*count_box, target_height=300)
                dbg_ocr('count', texts)
                ordered = sorted(texts, key=lambda b: (getattr(b, 'y', 0), getattr(b, 'x', 0)))
                joined = ''.join(getattr(b, 'name', '') or '' for b in ordered)
                m = re.search(r'(\d+)\s*/\s*(\d+)', joined)
                if m:
                    return int(m.group(1))
                nums = re.findall(r'\d+', joined)
                if nums:
                    return int(nums[0])
            except Exception:
                pass
            return None

        def scan_grid():
            """OCR 网格区角标 → 聚行 → 按 6 列基准补全缺列(防 OCR 漏格), 返回完整网格点
            (nx, ny) 归一化列表, 按行从上到下、行内从左到右。全部按实际帧尺寸换算, 分辨率自适应。"""
            fw = float(getattr(self.executor.method, 'width', 0) or 1920.0)
            fh = float(getattr(self.executor.method, 'height', 0) or 1200.0)
            row_tol = max(20.0, fh * 0.03)   # 行聚类容差(~1200帧→36px)
            col_gap = max(50.0, fw * 0.046)  # 列间距阈值(~1920帧→88px)
            texts = self.ocr(*grid_box)
            dbg_ocr('grid', texts)
            marks = []
            for b in texts:
                name = getattr(b, 'name', '') or ''
                if '+' in name and re.search(r'\d', name):
                    marks.append((b.x + b.width // 2, b.y + b.height // 2))
            if not marks:
                return []
            # 聚行
            marks.sort(key=lambda m: m[1])
            rows = []
            for mx, my in marks:
                for r in rows:
                    if abs(r['y'] - my) <= row_tol:
                        r['y'] = (r['y'] * len(r['cells']) + my) // (len(r['cells']) + 1)
                        r['cells'].append((mx, my))
                        break
                else:
                    rows.append({'y': my, 'cells': [(mx, my)]})
            rows.sort(key=lambda r: r['y'])

            # 列基准: 跨行合并 mark x, 间距>col_gap 视为新列(上限 6 列)
            all_x = sorted(mx for r in rows for mx, _ in r['cells'])
            cols = []
            for x in all_x:
                if cols and x - cols[-1] <= col_gap:
                    cols[-1] = (cols[-1] + x) / 2
                else:
                    cols.append(float(x))
            if len(cols) >= 6:
                col_centers[:] = cols[:6]
            base = col_centers if len(col_centers) == 6 else cols

            out = []
            for r in rows:
                row_xs = [mx for mx, _ in r['cells']]
                row_cols = sorted({min(range(len(base)), key=lambda i: abs(base[i] - mx)) for mx in row_xs})
                for ci in row_cols:
                    out.append((base[ci], r['y']))
                # 列基准齐而本行覆盖列数 <6(该行有格被 OCR 漏识别) → 补全缺列坐标
                if len(base) == 6 and len(row_cols) < 6:
                    for ci in range(6):
                        if ci not in row_cols:
                            out.append((base[ci], r['y']))
            out.sort(key=lambda p: (p[1], p[0]))
            return [(mx / fw, my / fh) for mx, my in out]

        def scroll_grid(notches=15):
            """光标移到滚动热区并下滑"""
            try:
                self.scroll_relative(0.52, 0.5, -notches)
            except Exception as e:
                self.log_debug(f'scroll failed: {e}')

        def read_detail():
            """OCR 右侧详情面板。返回 (echo_name, paired_all, detail_sig):
              echo_name  声骸名(面板顶部唯一中文行, y < 0.28*fh; 用于签名唯一性)
              paired_all 全部属性行 [(name, value_str), ...]  (主属性+词条, 按 y 序)
              detail_sig 名字 + 全量属性行签名(点选切换/唯一性检测)
            词条筛选由调用方按词条档位 is_stat_match 过滤(主属性数值超档自动丢弃)。

            布局注意: detail_box 下界 0.635(归一化) 是为覆盖第 5 词条(y≈0.607 + 文字高≈0.025);
            此前的 0.615(=738px@1920x1200) 把满级第 5 词条截在框外 → 报告永远最多 4 词条。
            """
            texts = self.ocr(*detail_box)
            dbg_ocr('detail', texts)
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
                return echo_name, [], ''
            paired_all = self._pair_props(properties, values)
            detail_sig = f'{echo_name}|' + '|'.join(f'{n}={v}' for n, v in paired_all)
            return echo_name, paired_all, detail_sig

        def dedup_key(echo_name, paired_all):
            """去重签名 = 声骸名 + 全部属性行的档位值(主属性+词条), 档位值稳定不受 OCR 抖动影响。
            全量 OCR 文本签名(含原始数值)对同一只每次识别会因个别字符抖动而不同 → 跨屏重叠时
            seen_sigs 拦不住 → 重复记录; 档位值是离散集合, 同一声骸多次识别结果一致。"""
            parts = [echo_name]
            for raw_n, v_str in paired_all:
                norm = self._normalize_stat(raw_n, v_str)
                v = parse_number(v_str)
                tier_v = snap_to_tier(norm, v)
                parts.append(f'{norm}={tier_v if tier_v is not None else round(v, 2)}')
            return '|'.join(parts)

        try:
            # 键数硬拒: 套装有效词条 <5 不允许评估(通用跳过)
            ok, msg = self._check_set_keys(self.config.get('当前套装', '通用'))
            if not ok:
                raise Exception(msg)
            total_limit = read_count()
            if dbg_dir:
                self.log_info(f'调试数据集目录: {os.path.abspath(dbg_dir)}', notify=True)
            self.log_info(f'背包声骸总数/位置: {total_limit}' if total_limit else '未识别到数量, 用滚动检测兜底')

            while not stop_all:
                # 每屏动态重读上限: "声骸N/3000" 的 N 若是滚动位置, 向下滚会单调增大,
                # max 跟随保证不误截断(且防 OCR 抖动回退); 若是背包总数则恒等
                new_lim = read_count()
                if new_lim:
                    total_limit = new_lim if total_limit is None else max(total_limit, new_lim)
                cells = scan_grid()
                if not cells:
                    # 网格区 OCR 不到角标: 0级角标 +0 也能被识别, 连续为空 ≈ 列表真到底;
                    # 首屏即空(且一个都未记录)才 raise, 提示可能不在背包界面
                    empty_scan += 1
                    if empty_scan >= 2:
                        if evaluated == 0 and not results:
                            raise Exception('未在背包界面检测到声骸网格(角标), 请确认在背包声骸列表界面')
                        self.log_info('到达背包底部(网格区无角标), 评估结束', notify=True)
                        break
                    scroll_grid()
                    self.sleep(0.6)
                    last_sig = None
                    continue
                empty_scan = 0

                processed_any = False
                empty_hits = 0       # 连续点空/未切换/已处理的格数, 防止空转
                for nx, ny in cells:
                    # 点格子 → 右侧详情
                    self.click(nx, ny, after_sleep=0.8)
                    dbg_shot(f'click_{nx:.2f}_{ny:.2f}')
                    echo_name, paired_all, sig = read_detail()
                    if not paired_all:
                        # 详情可能未刷新 → 再点一次重读
                        self.click(nx, ny, after_sleep=0.8)
                        echo_name, paired_all, sig = read_detail()
                    key = dedup_key(echo_name, paired_all) if paired_all else ''
                    if (not paired_all
                            or (last_sig is not None and sig == last_sig)
                            or (key and key in seen_sigs)):
                        # 空格/点选未切换(行尾补全的空白格/OCR 漏识重复)/已处理过的声骸(滚动重叠)
                        # → 跳过本格继续, 避免提前滚动漏掉本行后面真实格; 空转过多再滚屏
                        empty_hits += 1
                        if empty_hits >= 8:
                            self.log_debug('连续点选无新声骸, 本屏滚屏')
                            break
                        continue

                    processed_any = True
                    empty_hits = 0

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
                        # 按声骸名自动映射套装(多套装声骸: config 套装在候选内则优先, 否则首个);
                        # 未录入 → 回退 config(评估时=通用)
                        cfg_set = self.config.get('当前套装', '通用')
                        cands = get_sets_by_echo(echo_name)
                        set_name = get_set_by_echo(echo_name, prefer=cfg_set) or cfg_set
                        self.log_debug(f'[套装映射] {echo_name} → {set_name} (候选: {cands})')
                        valid_stats = get_expected_stats(set_name if set_name != '通用' else None)
                        # compute_weighted_score 内部会 parse_number(value_str), 需传字符串; 显式传套装名让其用映射套装权重
                        score, details = self.compute_weighted_score(
                            [(n, str(v)) for n, v in stats], valid_stats, set_name=set_name
                        )
                        # 判定与渐进强化共用同一份逻辑 (见 judge_echo); 满级不达标但底子够(有效≥2条且≥18分) → 建议保留
                        (verdict, verdict_cn), threshold, keep = self.judge_echo(set_name, tier, score, stats)
                        if keep:
                            verdict, verdict_cn = 'keep', '建议保留'
                    else:
                        # 0级声骸(0词条): 无评估价值——**跳过不记录、不终止**。
                        # 0级集中在列表底部, 置 processed_any 让它继续滚动推进(不触发"无新格"提前结束),
                        # 列表真到底由"网格连续为空(empty_scan)"判定; key 入 seen_sigs 防重叠重复扫。
                        processed_any = True
                        seen_sigs.add(key)
                        self.log_debug(f'[评估跳过] {echo_name} | 0级(无词条)')
                        continue

                    last_sig = sig
                    seen_sigs.add(key)

                    ss_name = f"eval_{evaluated + 1:03d}_{verdict}_{score:.1f}.png"
                    ss_path = os.path.join(ss_dir, ss_name)
                    # 截图 = 右侧详情完整展示: 名字(y~122)/COST/主属性/词条(含第5, y~728)/声骸技能行
                    # 此前固定截网格左上角(0.09,0.09,0.37,0.55) → 与当前声骸无关, 已改为右侧面板
                    echo_img = self.box_of_screen(0.665, 0.07, 0.995, 0.65).crop_frame(self.frame)
                    cv2.imwrite(ss_path, echo_img)

                    results.append({
                        "index": evaluated + 1, "name": echo_name, "tier": tier, "score": round(score, 2),
                        "threshold": threshold, "verdict": verdict, "verdict_cn": verdict_cn,
                        "screenshot": ss_name,
                        "stats": [{"name": n, "value": float(v), "detail": d,
                                   "ratio": round((snap_to_tier(n, v) or 0) / (get_mean(n) or 1), 3)}
                                  for (n, v), d in zip(stats, details)]
                    })
                    self.log_info(f"[评估#{evaluated + 1}] {echo_name} | {tier}/5词条 | 得分={score:.2f} | {verdict_cn}")
                    evaluated += 1
                    handled += 1
                    self.info_set('评估数量', evaluated)

                    if total_limit and handled >= total_limit:
                        self.log_info(f'已达背包声骸总数/步数上限 {total_limit}, 评估结束', notify=True)
                        stop_all = True
                        break

                if stop_all:
                    break

                if not processed_any:
                    # 本屏无新声骸(空格/未切换占满) → 滚动一屏
                    scroll_grid()
                    self.sleep(1.2)
                    last_sig = None   # 换屏后不再沿用上一屏的签名(新屏首格总是先读)
                    no_new_screen += 1
                    if no_new_screen >= 3:
                        self.log_info('连续滚动无进展, 评估结束', notify=True)
                        break
                else:
                    no_new_screen = 0
                    scroll_grid()   # 处理完本屏 → 滚下一屏
                    self.sleep(1.2)
                    last_sig = None   # 换屏后不再沿用上一屏的签名(新屏首格总是先读)

            # 汇总 JSON
            set_name = self.config.get('当前套装', '通用')
            output = {
                "set": set_name,
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
            score, detail_lines = self.compute_weighted_score(paired_stats, valid_stats)
            self.info_set('声骸得分', f'{score:.2f}')
            self.log_info(f'评分详情: {" | ".join(detail_lines)}')
            self.log_info(f'声骸总分: {score:.2f}')
            if score < self.config.get('最低得分>='):
                self.fail_reason = f'得分不足_{score:.2f}'
                self.log_info(f'总分 {score:.2f} < {self.config.get("最低得分>=")} 丢弃')
                return False

        return True

    def check_echo_progressive(self, properties, values):
        """
        渐进式强化判断(新标度 条分≈7.5~12.5):
          Lv5  第一条 → 必须在套装预期词条中
          Lv10 第二条 → 有≥1有效词条
          Lv15 第三条 → 累积得分 ≥ 锚线11(通用)
          Lv20 第四条 → 累积得分 ≥ 锚线18(通用)
          Lv25 第五条 → 累积得分 ≥ 锚线26.5(通用), 否则丢弃
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

        # 3. 确定预期词条列表
        set_name = self.config.get('当前套装', '通用')
        expected_stats = get_expected_stats(set_name if set_name != '通用' else None)

        # 4. 渐进式判断(与评估共用 judge_echo: Lv5/10 结构判定, Lv15+ 锚线)
        if tier <= 2:
            (verdict, _), _, _ = self.judge_echo(set_name, tier, 0.0, normalized)
            if verdict == 'fail':
                self.fail_reason = '无有效词条'
                self.log_info(f'[渐进T{tier}] 词条均非有效 : {[n for n, _ in normalized]}, 丢弃')
                return False
            self.log_info(f'[渐进T{tier}] 存在有效词条(不限分) ✅ 继续')
            return True

        # tier 3-5: 先算总分再判定
        score, details = self.compute_weighted_score(
            [(n, str(v)) for n, v in normalized], expected_stats
        )
        self.info_set('声骸得分', f'{score:.2f}')
        self.log_info(f'[渐进T{tier}] 得分: {" | ".join(details)}')
        self.log_info(f'[渐进T{tier}] 总分: {score:.2f}')

        (verdict, _), threshold, _ = self.judge_echo(set_name, tier, score, normalized)
        if verdict == 'fail':
            self.fail_reason = f'T{tier}得分不足_{score:.2f}<{threshold}'
            self.log_info(f'[渐进T{tier}] {score:.2f} < {threshold}, 停止强化')
            return False
        self.log_info(f'[渐进T{tier}] {score:.2f} >= {threshold} ✅ 继续')
        return True

    def judge_echo(self, set_name, tier, score, stats):
        """公共判定(评估与渐进强化共用): 返回 ((verdict, verdict_cn), threshold, keep)。
        Lv5/Lv10 (1-2 词条): 结构判定——存在"首条核心词条"(_core_first, 缺省=全部有效词条;
          通用=weight>0)即过, 不限分
        Lv15/20/25 (3-5 词条): 总分 ≥ 锚线(_tier_threshold = 有效词条最低 (tier-1) 条平均档加权和)
        verdict: pass(满级达标) / pending(达标且未满级) / fail(不达标)
        keep: 满级不达标但"底子值得花钱重铸"——有效条数 ≥2 且有效分 ≥18(锁2追3 + 成本线);
        强化流程 keep 不豁免(仍丢弃), 仅评估报告标注"建议保留"。
        """
        if tier <= 2:
            if set_name == '通用':
                ok = any(DEFAULT_WEIGHTS.get(n, 0.0) > 0 for n, _ in stats)
            else:
                core = get_set_core_first(set_name) or []
                ok = any(n in core for n, _ in stats)
            return (('pending', '待强化') if ok else ('fail', '不达标')), 0.0, False
        threshold = _tier_threshold(set_name, tier)
        if score >= threshold:
            return (('pass', '达标') if tier >= 5 else ('pending', '待强化')), threshold, False
        # 不达标: 满级时判断是否"建议保留"(有效条数≥2 且 有效分≥18)
        keep = False
        if tier >= 5:
            if set_name == '通用':
                eff = sum(1 for n, _ in stats if DEFAULT_WEIGHTS.get(n, 0.0) > 0)
            else:
                core = get_set_core_first(set_name) or []
                eff = sum(1 for n, _ in stats if n in core)
            keep = eff >= 2 and score >= 18
        return ('fail', '不达标'), threshold, keep

    def compute_weighted_score(self, paired_stats, valid_stats, set_name=None):
        """
        评分: 条分 = 档位/均值 × 10 × 权重(上限自然 12.5/条), 无效 0 分。
        权重来源: 套装 JSON (get_set_weights); 通用模式用 DEFAULT_WEIGHTS 表。
        set_name: 显式指定套装名(评估按声骸名映射时用); None 时回退 config['当前套装']。
        达标线: _tier_threshold = 套装有效词条平均档加权分(10×权重)中最低 (tier-1) 条之和;
                Lv5/10 走"有效词条存在"结构判定, 不用分数。
        """
        if set_name is None:
            set_name = self.config.get('当前套装', '通用')
        set_weights = get_set_weights(set_name if set_name != '通用' else None)

        total = 0.0
        details = []

        for stat_name, value_str in paired_stats:
            v = parse_number(value_str)
            # stat_name 已是 OCR 归一化名, 与 tier 键统一
            tier_name = stat_name

            if set_weights is not None:
                weight = set_weights.get(stat_name, 0.0)
                is_valid = weight > 0
            else:
                weight = DEFAULT_WEIGHTS.get(stat_name, 0.0)
                is_valid = weight > 0

            if not is_valid:
                details.append(f'{stat_name}={v} 无效(0)')
                continue

            tier_val = snap_to_tier(tier_name, v)
            mean_val = get_mean(tier_name)
            if tier_val is None or mean_val is None:
                details.append(f'{stat_name}={v} 无档位数据')
                continue

            contribution = (tier_val / mean_val) * 10 * weight
            total += contribution
            details.append(f'{stat_name}={v}→{tier_val}/{mean_val}×10×{weight}={contribution:.2f}')

        return total, details

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


def parse_number(text):
    try:
        return float(text.replace('％', '%').split('%')[0])
    except (ValueError, IndexError):
        return 0.0
