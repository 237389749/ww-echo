# EnhanceEchoTask.py
import json
import re
import shutil
import time
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox
from qfluentwidgets import FluentIcon

from ok import FindFeature, Logger
from ok.feature.Box import get_bounding_box
from ok.util.file import clear_folder
from src.echo_stats import snap_to_tier, get_mean  # noqa
from src.echo_set_templates import get_expected_stats, get_all_set_names, get_set_weights
from src.task.BaseEchoTask import BaseEchoTask

# OCR 归一化名 -> echo_stats 档位表名
_OCR_TO_TIER_NAME: dict[str, str] = {
    '暴击': '暴击率',
    '暴击伤害': '暴击伤害',
    '攻击百分比': '百分比攻击',
    '生命百分比': '百分比生命',
    '防御百分比': '百分比防御',
    '攻击': '固定数值攻击',
    '生命': '固定数值生命',
    '防御': '固定数值防御',
    '共鸣效率': '共鸣效率',
    '普攻伤害加成': '普攻伤害加成',
    '重击伤害加成': '重击伤害加成',
    '共鸣解放伤害加成': '共鸣解放伤害加成',
    '共鸣技能伤害加成': '共鸣技能伤害加成',
}

logger = Logger.get_logger(__name__)

number_pattern = re.compile(r"^[\d.%％ ]+$")
property_pattern = re.compile(r"[\u4e00-\u9fff]{2,}")


class EnhanceEchoTask(BaseEchoTask, FindFeature):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "批量强化声骸(游戏与okww语言必须为简体/繁体中文)"
        self.description = "点击B进入背包, 在过滤器中选择需要强化的声骸, 并按照等级从0排序后开始."
        self.icon = FluentIcon.ADD
        self.group_name = "批量强化声骸"
        self.group_icon = FluentIcon.ADD
        self.fail_reason = ""
        self._syncing = False  # 防止 JSON↔UI 双向同步时递归
        self.supported_languages = ["zh_CN", "zh_TW"]
        self.instructions = (
            "套装词条&权重配置说明\n\n"
            "配置文件: assets/echo_set_templates.json\n"
            "用记事本或VSCode打开编辑\n\n"
            "=== 修改方法 ===\n\n"
            '1. 找到套装名 (如 "凝夜白霜")\n'
            "2. 修改词条和权重:\n"
            '   "暴击": 1.5,\n'
            '   "暴击伤害": 1.4,\n'
            '   "攻击百分比": 1.0\n\n'
            "3. 保存后在UI重新选择套装生效\n\n"
            "=== 导入/导出 ===\n\n"
            "使用下方按钮导入导出JSON文件\n"
            "导出=备份副本, 导入=替换当前模板"
        )
        self.default_config.update({
            '必须有双爆': True,
            '双爆出现之前必须全有效词条': True,
            '双爆总计>=': 13.8,
            '首条双爆>=': 6.9,
            '有效词条>=': 3,
            '第一条必须为有效词条': True,
            '有效词条': ['暴击', '暴击伤害', '攻击百分比', '攻击', '共鸣效率'],
            '成功后暂停': True,
            # 强化策略
            '强化策略': '渐进式',
            '当前套装': '通用',
            # 评分
            '启用评分模式': False,
            '最低得分>=': 3.0,
            # 词条权重 — 选套装时与JSON双向同步, 通用模式直接使用
            '暴击权重': 1.0,
            '暴击伤害权重': 1.0,
            '百分比攻击权重': 1.0,
            '固定攻击权重': 1.0,
            '百分比生命权重': 1.0,
            '固定生命权重': 1.0,
            '百分比防御权重': 1.0,
            '固定防御权重': 1.0,
            '共鸣效率权重': 1.0,
            '普攻加成权重': 1.0,
            '重击加成权重': 1.0,
            '解放加成权重': 1.0,
            '技能加成权重': 1.0,
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
        self.config_type['导出模板'] = {
            'type': 'button',
            'buttons': [{'text': '导出 | Export', 'callback': self._export_template}]
        }
        self.config_type['导入模板'] = {
            'type': 'button',
            'buttons': [{'text': '导入 | Import', 'callback': self._import_template}]
        }
        self.config_description = {
            '必须有双爆': '如果开启，声骸最终必须同时拥有暴击和暴击伤害。如果剩余孔位不足以凑齐双爆，则丢弃',
            '双爆出现之前必须全有效词条': '开启后，在暴击或暴击伤害词条出现之前，前面的所有词条必须都在有效词条列表中',
            '双爆总计>=': '当声骸同时存在暴击和爆伤时，需要满足 暴击 + (爆伤/2) >= 此数值',
            '首条双爆>=': '仅检查第一条出现的暴击或暴击伤害是否满足条件, 爆伤/2',
            '有效词条>=': '满级时需要的有效词条数量\n剩余孔位无法凑齐则提前丢弃',
            '第一条必须为有效词条': '如果开启，第一个副词条必须在有效词条列表中且符合数值要求，否则直接丢弃',
            '有效词条': '定义哪些属性被视为有效',
            '成功后暂停': '强化出符合条件的声骸时自动暂停任务并弹出通知，方便手动确认',
            '强化策略': '传统: 满级后一次性判断\n渐进式: Lv5首条须在预期中→Lv10跳过→Lv15得分≥1.5→Lv20≥2.25→Lv25≥3.75, 不及格即停',
            '当前套装': '套装词条&权重在assets/echo_set_templates.json\n选套装→用JSON配置, 选通用→用有效词条(权重1.0)',
            '导出模板': '弹出保存对话框, 将当前套装模板导出为JSON副本',
            '导入模板': '弹出选择对话框, 从JSON文件导入套装模板(自动备份旧文件)',
            # 评分模式
            '暴击权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '暴击伤害权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '百分比攻击权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '固定攻击权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '百分比生命权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '固定生命权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '百分比防御权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '固定防御权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '共鸣效率权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '普攻加成权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '重击加成权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '解放加成权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '技能加成权重': '选套装: 与JSON双向同步; 通用: 直接使用',
            '启用评分模式': '均值归一化: 单词条=档位值/均值\n暴击最低6.3%→6.3/8.4=0.75词条, 最高10.5%→10.5/8.4=1.25词条\n无效词条(不在有效列表)=0分不计入\n5词条总分3.75~6.25\n传统满级后检查, 渐进式自动启用',
            '最低得分>=': '传统模式满级5词条后总分>=此值保留\n渐进式用内置阈值(T3=1.5/T4=2.25/T5=3.75)不受影响',
        }

    # UI 权重键 → JSON 词条名
    _WEIGHT_KEY_TO_STAT: dict[str, str] = {
        '暴击权重': '暴击', '暴击伤害权重': '暴击伤害',
        '百分比攻击权重': '攻击百分比', '固定攻击权重': '攻击',
        '百分比生命权重': '生命百分比', '固定生命权重': '生命',
        '百分比防御权重': '防御百分比', '固定防御权重': '防御',
        '共鸣效率权重': '共鸣效率',
        '普攻加成权重': '普攻伤害加成', '重击加成权重': '重击伤害加成',
        '解放加成权重': '共鸣解放伤害加成', '技能加成权重': '共鸣技能伤害加成',
    }

    def validate(self, key, value):
        """配置变更钩子: 选套装→加载JSON到UI, 改权重→写回JSON。"""
        if self._syncing:
            return True, None
        self._syncing = True
        try:
            if key == '当前套装':
                self._sync_set_to_ui(value)
            elif key in self._WEIGHT_KEY_TO_STAT or key == '有效词条':
                self._sync_ui_to_set()
        finally:
            self._syncing = False
        return True, None

    def _sync_set_to_ui(self, set_name):
        """套装切换: 从 JSON 加载词条&权重到 UI 控件。"""
        if set_name == '通用':
            return
        weights = get_set_weights(set_name)
        if not weights:
            return
        # 同步有效词条多选
        self.config['有效词条'] = list(weights.keys())
        # 同步各权重滑块
        for ui_key, stat_name in self._WEIGHT_KEY_TO_STAT.items():
            w = weights.get(stat_name, 1.0)
            self.config[ui_key] = w

    def _sync_ui_to_set(self):
        """保存: 将当前 UI 的词条&权重写回 JSON。"""
        set_name = self.config.get('当前套装', '通用')
        if set_name == '通用':
            return
        stat_weights: dict[str, float] = {}
        for ui_key, stat_name in self._WEIGHT_KEY_TO_STAT.items():
            w = float(self.config.get(ui_key, 1.0))
            if w > 0:
                stat_weights[stat_name] = w
        # 也纳入未勾选为权重的有效词条(来自多选)
        valid_stats = self.config.get('有效词条', [])
        for s in valid_stats:
            if s not in stat_weights:
                stat_weights[s] = 1.0
        self._write_set_to_json(set_name, stat_weights)

    def _write_set_to_json(self, set_name, stat_weights):
        """写入 JSON 文件。"""
        import json
        path = os.path.join("assets", "echo_set_templates.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"version": 1, "sets": {}}
            data["sets"][set_name] = stat_weights
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            from src.echo_set_templates import load_templates
            load_templates(force=True)
        except Exception as e:
            self.log_error(f"保存套装模板失败: {e}")

    def find_echo_enhance(self):
        return self.ocr(0.82, 0.86, 0.97, 0.96, match='培养')

    def is_0_level(self):
        return self.ocr(0.65, 0.35, 1, 0.57, match=re.compile('声骸技能'))

    def run(self):
        self.info_set('成功声骸数量', 0)
        self.info_set('失败声骸数量', 0)
        clear_folder('screenshots')
        while True:
            enhance = self.find_echo_enhance()
            if not enhance:
                raise Exception('必须在背包声骸界面过滤后开始!')
            current_level = self.is_0_level()
            if not current_level:
                total = self.info_get('成功声骸数量') + self.info_get('失败声骸数量')
                if self.debug:
                    self.screenshot('无可强化声骸')
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
                self.log_info(f'ocr values: {texts}')
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

        paired_stats = []
        unmatched_values = values.copy()
        for prop in properties:
            matched_val_text = "0"
            if unmatched_values:
                closest_val = min(unmatched_values, key=lambda v: abs(prop.y - v.y))
                matched_val_text = closest_val.name
                unmatched_values.remove(closest_val)
            paired_stats.append((prop.name, matched_val_text))

        total_count = len(paired_stats)

        crit_rate_val = 0
        crit_dmg_val = 0
        has_crit_rate = False
        has_crit_dmg = False

        checked_first_crit = False
        has_encountered_crit = False

        valid_stats = self.config.get('有效词条') or []

        for p_raw, v_str in paired_stats:
            p = p_raw
            if '暴击伤害' in p:
                p = '暴击伤害'
            elif '暴击' in p:
                p = '暴击'
            elif '攻击' in p:
                p = '攻击' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '生命' in p:
                p = '生命' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '防御' in p:
                p = '防御' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '效率' in p:
                p = '共鸣效率'
            elif '普攻' in p:
                p = '普攻伤害加成'
            elif '重击' in p:
                p = '重击伤害加成'
            elif '解放' in p:
                p = '共鸣解放伤害加成'
            elif '技能' in p:
                p = '共鸣技能伤害加成'

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
        渐进式强化判断：
          Lv5  第一条 → 必须在套装预期词条中
          Lv10 第二条 → 不判断，继续
          Lv15 第三条 → 加权得分 >= 1.5，否则停
          Lv20 第四条 → 加权得分 >= 2.25，否则停
          Lv25 第五条 → 加权得分 >= 3.75，否则丢弃
        """
        self.fail_reason = ""

        # 1. 配对属性名和数值（与 check_echo_stats 相同逻辑）
        paired_stats = []
        unmatched_values = values.copy()
        for prop in properties:
            matched_val_text = "0"
            if unmatched_values:
                closest_val = min(unmatched_values, key=lambda v: abs(prop.y - v.y))
                matched_val_text = closest_val.name
                unmatched_values.remove(closest_val)
            paired_stats.append((prop.name, matched_val_text))

        tier = len(paired_stats)

        # 2. 归一化属性名
        normalized = []
        for p_raw, v_str in paired_stats:
            p = p_raw
            if '暴击伤害' in p:
                p = '暴击伤害'
            elif '暴击' in p:
                p = '暴击'
            elif '攻击' in p:
                p = '攻击' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '生命' in p:
                p = '生命' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '防御' in p:
                p = '防御' + ('百分比' if '%' in v_str or '％' in v_str else '')
            elif '效率' in p:
                p = '共鸣效率'
            elif '普攻' in p:
                p = '普攻伤害加成'
            elif '重击' in p:
                p = '重击伤害加成'
            elif '解放' in p:
                p = '共鸣解放伤害加成'
            elif '技能' in p:
                p = '共鸣技能伤害加成'
            v = parse_number(v_str)
            normalized.append((p, v))

        # 3. 确定预期词条列表
        set_name = self.config.get('当前套装', '通用')
        expected_stats = get_expected_stats(set_name if set_name != '通用' else None)

        # 4. 渐进式判断
        # Tier 1: 第一条必须在预期词条中
        if tier >= 1:
            first_name, first_val = normalized[0]
            if first_name not in expected_stats:
                self.fail_reason = f'首条非预期_{first_name}'
                self.log_info(f'[渐进T1] 首条 {first_name}={first_val} 不在套装预期 {expected_stats} 中, 丢弃')
                return False
            self.log_info(f'[渐进T1] 首条 {first_name}={first_val} ✅ 符合预期')

        # Tier 2: 不做判断
        if tier == 2:
            self.log_info(f'[渐进T2] 第二条不做判断, 继续')
            return True

        # Tier 3-5: 按累积得分判断
        score_thresholds = {3: 1.5, 4: 2.25, 5: 3.75}
        if tier in score_thresholds:
            score, details = self.compute_weighted_score(
                [(n, str(v)) for n, v in normalized], expected_stats
            )
            self.info_set('声骸得分', f'{score:.2f}')
            self.log_info(f'[渐进T{tier}] 得分: {" | ".join(details)}')
            self.log_info(f'[渐进T{tier}] 总分: {score:.2f}')

            threshold = score_thresholds[tier]
            if score < threshold:
                self.fail_reason = f'T{tier}得分不足_{score:.2f}<{threshold}'
                self.log_info(f'[渐进T{tier}] {score:.2f} < {threshold}, 停止强化')
                return False
            self.log_info(f'[渐进T{tier}] {score:.2f} >= {threshold} ✅ 继续')

        return True

    def compute_weighted_score(self, paired_stats, valid_stats):
        """
        权重来源: UI 滑块 (选套装时已与JSON双向同步, 通用模式直接使用)
        有效性: 选套装 → 权重>0的为有效; 通用 → 用有效词条列表
        """
        set_name = self.config.get('当前套装', '通用')
        using_set = set_name != '通用'

        total = 0.0
        details = []

        for stat_name, value_str in paired_stats:
            v = parse_number(value_str)
            tier_name = _OCR_TO_TIER_NAME.get(stat_name)
            if tier_name is None:
                details.append(f'{stat_name}={v} 未知词条')
                continue

            # 查权重 (从UI滑块取, 已自动同步)
            weight = float(self.config.get(self._stat_to_weight_key(stat_name), 1.0))

            # 有效性: 权重>0 = 有效
            if weight <= 0:
                details.append(f'{stat_name}={v} 无效(0)')
                continue

            if using_set:
                is_valid = weight > 0
            else:
                is_valid = stat_name in valid_stats

            if not is_valid:
                details.append(f'{stat_name}={v} 无效(0)')
                continue

            tier_val = snap_to_tier(tier_name, v)
            mean_val = get_mean(tier_name)
            if tier_val is None or mean_val is None:
                details.append(f'{stat_name}={v} 无档位数据')
                continue

            contribution = (tier_val / mean_val) * weight
            total += contribution
            details.append(f'{stat_name}={v}→{tier_val}/{mean_val}×{weight}={contribution:.2f}')

        return total, details

    @classmethod
    def _stat_to_weight_key(cls, stat_name: str) -> str:
        """词条名 → 权重滑块键 (反向映射)。"""
        for ui_key, s in cls._WEIGHT_KEY_TO_STAT.items():
            if s == stat_name:
                return ui_key
        return '暴击权重'  # fallback

    # ── 模板导入/导出 ──

    _TEMPLATE_PATH = os.path.join("assets", "echo_set_templates.json")

    def _export_template(self):
        path, _ = QFileDialog.getSaveFileName(
            None, "导出套装模板 | Export Template",
            "echo_set_templates.json",
            "JSON (*.json);;所有文件 (*)",
        )
        if path:
            try:
                shutil.copy(self._TEMPLATE_PATH, path)
                self.log_info(f"模板已导出到: {path}", notify=True)
            except Exception as e:
                self.log_error(f"导出失败: {e}")

    def _import_template(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "导入套装模板 | Import Template",
            "", "JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            # 校验 JSON
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(None, "导入失败 | Import Failed", f"文件格式错误: {e}")
            return

        reply = QMessageBox.question(
            None, "确认导入 | Confirm Import",
            f"将用所选文件替换当前模板\n(旧文件备份为 .bak)\n\n{path}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            if os.path.exists(self._TEMPLATE_PATH):
                shutil.copy(self._TEMPLATE_PATH, self._TEMPLATE_PATH + ".bak")
            os.makedirs(os.path.dirname(self._TEMPLATE_PATH) or ".", exist_ok=True)
            shutil.copy(path, self._TEMPLATE_PATH)
            from src.echo_set_templates import load_templates
            load_templates(force=True)
            self.log_info("模板已导入, 重新选择套装生效", notify=True)
        except Exception as e:
            self.log_error(f"导入失败: {e}")

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
                self.log_info('成功弃置!')
                success = True
                break
        if not success:
            raise Exception('上锁失败!')
        self.screenshot_echo(f'success/{self.info_get("成功声骸数量")}')
        self.log_info('成功并上锁')
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
