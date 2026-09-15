"""
运行面板 — 任务/策略/套装选择, 启停, 状态, 日志。
"""
import json
import os
import threading

from PySide6.QtCore import QTimer, QSettings, Signal, QObject
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QPushButton, QLabel, QFrame,
                               QCheckBox)

from ok import og

from src.echo_stats import DEFAULT_WEIGHTS
from src.echo_set_templates import get_set_weights


class RunTab(QWidget):
    _log_signal = Signal(str)
    _eval_done_signal = Signal(str, str)  # json_path, ss_dir
    _eval_error_signal = Signal(str)
    _task_done_signal = Signal(str)  # message

    def __init__(self, ok_engine, log_bridge, log_area, parent=None):
        super().__init__(parent)
        self.ok_engine = ok_engine
        self.log_area = log_area
        self._task = None
        self._running = False
        self._thread = None
        self._settings = QSettings("OK-Echo", "RunTab")

        self._setup_ui()
        self._load_settings()

        log_bridge.log_signal.connect(self._append_log)

        # 线程安全信号
        self._log_signal.connect(self._append_log)
        self._eval_done_signal.connect(self._on_eval_done_ui)
        self._eval_error_signal.connect(self._on_eval_error_ui)
        self._task_done_signal.connect(self._on_task_done_ui)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 第1行: 任务选择 + 策略 ──
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("模式:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(["强化声骸", "评估声骸"])
        row1.addWidget(self.task_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["渐进式", "传统"])
        row1.addWidget(self.strategy_combo)

        row1.addSpacing(16)
        self.set_label = QLabel("套装:")
        row1.addWidget(self.set_label)
        self.set_combo = QComboBox()
        self.set_combo.setMinimumWidth(140)
        self._load_sets()
        row1.addWidget(self.set_combo)

        row1.addStretch()
        layout.addLayout(row1)

        # 传统评分选项 (先创建, 后面放进 traditional_opts)
        self.opt_score_enable = QCheckBox("启用评分模式")
        self.opt_score_min = QComboBox()
        self.opt_score_min.setMinimumWidth(60)
        for v in [24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48]:
            self.opt_score_min.addItem(str(v))
        self.opt_score_min.setCurrentText("32")

        # ── 第2行: 传统模式选项 ──
        self.traditional_opts = QWidget()
        trad = QHBoxLayout(self.traditional_opts)
        trad.setContentsMargins(0, 0, 0, 0)
        self.opt_double_crit = QCheckBox("必须有双爆")
        self.opt_double_crit.setChecked(True)
        trad.addWidget(self.opt_double_crit)
        self.opt_all_valid_before_crit = QCheckBox("双爆前全有效")
        self.opt_all_valid_before_crit.setChecked(True)
        trad.addWidget(self.opt_all_valid_before_crit)
        self.opt_first_must_valid = QCheckBox("首条必须有效")
        self.opt_first_must_valid.setChecked(True)
        trad.addWidget(self.opt_first_must_valid)
        trad.addSpacing(8)
        trad.addWidget(self.opt_score_enable)
        trad.addWidget(QLabel("最低得分≥"))
        trad.addWidget(self.opt_score_min)
        trad.addWidget(QLabel("首条双爆≥"))
        self.opt_first_crit = QComboBox()
        self.opt_first_crit.setMinimumWidth(60)
        self.opt_first_crit.addItems([str(x) for x in [6.3, 6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5]])
        self.opt_first_crit.setCurrentText("6.9")
        trad.addWidget(self.opt_first_crit)
        trad.addWidget(QLabel("双爆总计≥"))
        self.opt_total_crit = QComboBox()
        self.opt_total_crit.setMinimumWidth(60)
        self.opt_total_crit.addItems([str(x) for x in [6.9, 7.5, 8.1, 8.7, 9.3, 9.9, 10.5, 12.0, 13.8, 15.0, 16.5, 18.0]])
        self.opt_total_crit.setCurrentText("13.8")
        trad.addWidget(self.opt_total_crit)
        trad.addWidget(QLabel("有效词条≥"))
        self.opt_valid_count = QComboBox()
        self.opt_valid_count.setMinimumWidth(50)
        self.opt_valid_count.addItems(["1", "2", "3", "4", "5"])
        self.opt_valid_count.setCurrentText("3")
        trad.addWidget(self.opt_valid_count)
        trad.addStretch()
        self.traditional_opts.setVisible(False)
        layout.addWidget(self.traditional_opts)

        self.strategy_combo.currentTextChanged.connect(
            lambda s: self.traditional_opts.setVisible(s == "传统"))
        self.strategy_combo.currentTextChanged.connect(
            lambda s: self._update_strategy_info(s))

        # 策略说明
        self.strategy_info = QLabel()
        self.strategy_info.setWordWrap(True)
        self.strategy_info.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        layout.addWidget(self.strategy_info)

        # 评估说明 (选评估时可见)
        self.strategy_info_eval = QLabel(
            "评估模式 — 只读遍历背包, 截图+打分, 生成HTML报告\n\n"
            "评估按声骸名自动映射套装权重/判定, 未录入的声骸回退通用\n\n"
            "完成后弹出保存框 → 生成 eval_report.html + 截图文件夹\n"
            "报告: 截图+名称+得分+判定+词条明细(按档位着色), 可按得分/判定/名称筛选\n"
            "不强化/不上锁/不丢弃 — 纯评估\n\n"
            "达标线: Lv5/10 有首核即过 | Lv15/20/25 ≥ 11/18/26.5(通用) | 满级不达标但≥2条有效且≥18分 → 建议保留重铸\n"
            "⏳待强化=未满级通过, ✅达标=满级通过, 🔵建议保留重铸=底子够可洗, ❌不合格"
        )
        self.strategy_info_eval.setWordWrap(True)
        self.strategy_info_eval.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        self.strategy_info_eval.setVisible(False)
        layout.addWidget(self.strategy_info_eval)

        # 评分说明 (始终可见)
        self.score_info = QLabel(
            "评分: 条分 = 档位值÷期望值 ×10×权重(期望 = 官方公示概率期望; 平均档 = 10 分, 满档 ≈ 13.1~14.0)\n"
            "通用权重: 暴击1.0 爆伤0.7 攻击%/生命%/防御% 0.5 共效0.6 专伤0.4 小攻/小生命/小防御 0.25\n"
            "暴击6.3%→8.40分, 10.5%→14.00分; 套装模式权重由套装模板决定, 无效词条=0分\n"
            "判定: 达标线 A = 10×本只出现有效词条的权重和; 基准线 B = 套装有效键最低 tier-1 条之和 ×10\n"
            "满级: A≥B 且 总分≥A → 达标; 总分≥B → 保留; 未过线但「锁 N 刷 M 后达标概率≥60%」→ 建议重铸; Lv5/10 有首核即过"
        )
        self.score_info.setWordWrap(True)
        self.score_info.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; padding: 4px 8px; "
            "background: rgba(128,128,128,0.06); border-radius: 4px; }"
        )
        layout.addWidget(self.score_info)

        self._update_strategy_info(self.strategy_combo.currentText())

        # 通用选项
        row_gen = QHBoxLayout()
        self.opt_pause = QCheckBox("成功后暂停")
        self.opt_pause.setChecked(True)
        row_gen.addWidget(self.opt_pause)
        row_gen.addStretch()
        layout.addLayout(row_gen)


        self.task_combo.currentTextChanged.connect(
            lambda t: self._on_task_changed(t))
        self._on_task_changed(self.task_combo.currentText())

        # ── 第3行: 启停按钮 ──
        row3 = QHBoxLayout()

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setMinimumWidth(100)
        self.start_btn.setStyleSheet("QPushButton { font-weight: bold; font-size: 14px; }")
        self.start_btn.clicked.connect(self._start)
        row3.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row3.addWidget(self.stop_btn)

        row3.addStretch()
        # 状态
        self.success_label = QLabel("成功: 0")
        self.fail_label = QLabel("失败: 0")
        self.score_label = QLabel("得分: -")
        for lbl in [self.success_label, self.fail_label, self.score_label]:
            lbl.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 8px;")
            row3.addWidget(lbl)

        layout.addLayout(row3)

        # ── 分隔 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        hint = QLabel('运行日志 → 见「调试工具」tab')
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addStretch()

    def _update_strategy_info(self, strategy):
        if strategy == "渐进式":
            self.strategy_info.setText(
                "渐进式: 每级单独评估, 不达标即停丢\n"
                "Lv5  首条 → 有首核词条即过(不限分)\n"
                "Lv10 第二条 → 有≥1有效词条即过\n"
                "Lv15 第三条 → 累积得分 ≥ 锚线11\n"
                "Lv20 第四条 → 累积得分 ≥ 锚线18\n"
                "Lv25 第五条 → 累积得分 ≥ 锚线26.5, 达标上锁\n"
                "未满级声骸: 已有词条先做渐进判断, 通过则继续强化"
            )
        else:
            self.strategy_info.setText(
                "传统: 拉满到Lv25后一次性判断\n"
                "判断条件: 必须有双爆 / 首条双爆≥阈值 / 双爆总计≥阈值\n"
                "有效词条≥设定数量 / 第一条必须有效\n"
                "未满级声骸: 继续强化至满级再判断"
            )

    def _on_task_changed(self, task_name):
        is_enhance = "强化" in task_name
        self.strategy_combo.setVisible(is_enhance)
        self.strategy_info.setVisible(is_enhance)
        self.traditional_opts.setVisible(is_enhance and self.strategy_combo.currentText() == "传统")
        # 套装语境只对强化有意义(评估=通用权重; 声骸个体与套装无自动映射)
        self.set_label.setVisible(is_enhance)
        self.set_combo.setVisible(is_enhance)
        if not is_enhance:
            self.strategy_info_eval.setVisible(True)
        else:
            self.strategy_info_eval.setVisible(False)

    # ── 设置持久化 ──
    def _load_settings(self):
        idx = self.task_combo.findText(self._settings.value("task", "强化声骸"))
        if idx >= 0:
            self.task_combo.setCurrentIndex(idx)
        idx = self.strategy_combo.findText(self._settings.value("strategy", "渐进式"))
        if idx >= 0:
            self.strategy_combo.setCurrentIndex(idx)

    def _save_settings(self):
        self._settings.setValue("task", self.task_combo.currentText())
        self._settings.setValue("strategy", self.strategy_combo.currentText())

    # ── 套装 ──
    def _load_sets(self):
        path = os.path.join("assets", "echo_set_templates.json")
        current = self.set_combo.currentText()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            names = list(data.get("sets", {}).keys())
        except Exception:
            names = []
        self.set_combo.clear()
        self.set_combo.addItem("通用")
        self.set_combo.addItems(names)
        if current in names:
            self.set_combo.setCurrentText(current)

    def _append_log(self, text):
        self.log_area.append(text)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_status(self):
        task = self._get_task()
        if task is None:
            return
        try:
            self.success_label.setText(f"成功: {task.info_get('成功声骸数量') or 0}")
            self.fail_label.setText(f"失败: {task.info_get('失败声骸数量') or 0}")
            score = task.info_get('声骸得分')
            self.score_label.setText(f"得分: {score}" if score is not None else "得分: -")
            eval_count = task.info_get('评估数量')
            if eval_count:
                self.score_label.setText(f"评估: {eval_count}个")
        except Exception:
            pass

    # ── 启停 ──
    def _start(self):
        self._save_settings()
        task = self._get_task()
        if task is None:
            self._append_log("[ERROR] 任务未就绪")
            return
        if self._running:
            return

        is_eval = "评估" in self.task_combo.currentText()
        task.config['强化策略'] = self.strategy_combo.currentText()
        # 评估按声骸名自动映射套装(见 evaluate_only); 这里置"通用"仅作映射失败时的兜底
        task.config['当前套装'] = '通用' if is_eval else self.set_combo.currentText()

        if is_eval:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._append_log("══════════ 开始评估 ══════════")
            self._append_log("评估按声骸名自动映射套装权重, 仅打分, 不修改声骸")

            def _on_eval_done(json_path, ss_dir):
                self._eval_done_signal.emit(json_path, ss_dir)

            def _run_eval():
                try:
                    # [ww-echo cloud patch] 评估也把游戏窗口切到前台再跑
                    hwnd_window = getattr(og.device_manager, 'hwnd_window', None)
                    if hwnd_window is not None and hwnd_window.hwnd:
                        hwnd_window.bring_to_front()
                    task.evaluate_only(on_done=_on_eval_done)
                except Exception as e:
                    self._eval_error_signal.emit(str(e))

            self._thread = threading.Thread(target=_run_eval, daemon=True)
            self._thread.start()
            return

        if not is_eval and self.strategy_combo.currentText() == '传统':
            task.config['必须有双爆'] = self.opt_double_crit.isChecked()
            task.config['双爆出现之前必须全有效词条'] = self.opt_all_valid_before_crit.isChecked()
            task.config['第一条必须为有效词条'] = self.opt_first_must_valid.isChecked()
            task.config['首条双爆>='] = float(self.opt_first_crit.currentText())
            task.config['双爆总计>='] = float(self.opt_total_crit.currentText())
            task.config['有效词条>='] = int(self.opt_valid_count.currentText())
            task.config['启用评分模式'] = self.opt_score_enable.isChecked()
            task.config['最低得分>='] = float(self.opt_score_min.currentText())

        task.config['成功后暂停'] = self.opt_pause.isChecked()

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._append_log("══════════ 开始强化 ══════════")
        self._append_log(f"策略: {task.config['强化策略']}  套装: {task.config['当前套装']}")

        self._thread = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._thread.start()

    def _stop(self):
        task = self._get_task()
        if task:
            task.disable()
            task.unpause()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                self._append_log("⚠ 任务线程仍在运行, 将在后台自行结束")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log("══════════ 已停止 ══════════")

    def _run_task(self, task):
        try:
            og.app.start_controller.start(task)
        except Exception as e:
            self._task_done_signal.emit(f"[ERROR] {e}")
        else:
            self._task_done_signal.emit("══════════ 结束 ══════════")

    def _on_task_done_ui(self, msg):
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log(msg)

    def _on_eval_done_ui(self, json_path, ss_dir):
        """在主线程中处理评估完成后的 UI 操作。"""
        import json as _json, shutil
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        save_path, _ = QFileDialog.getSaveFileName(
            None, "保存评估报告", "eval_report.html",
            "HTML (*.html)"
        )
        if not save_path:
            shutil.rmtree(os.path.dirname(json_path), ignore_errors=True)
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 评估结束 (已取消) ══════════")
            return

        try:
            dest_dir = os.path.dirname(save_path)
            ss_dest = os.path.join(dest_dir, "eval_screenshots")
            if os.path.exists(ss_dest):
                shutil.rmtree(ss_dest)
            if os.path.exists(ss_dir):
                shutil.copytree(ss_dir, ss_dest)

            with open(json_path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            html = _build_eval_html(data)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)

            if QMessageBox.question(None, "完成",
                                    f"报告已保存:\n{save_path}\n\n打开查看?") == QMessageBox.Yes:
                os.startfile(save_path)
        except Exception as e:
            self._append_log(f"[ERROR] 保存失败: {e}")
        finally:
            shutil.rmtree(os.path.dirname(json_path), ignore_errors=True)
            self._running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._append_log("══════════ 评估结束 ══════════")

    def _on_eval_error_ui(self, error_msg):
        self._append_log(f"[ERROR] {error_msg}")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _get_task(self):
        if self._task is not None:
            return self._task
        try:
            from src.task.EnhanceEchoTask import EnhanceEchoTask
            self._task = og.executor.get_task_by_class(EnhanceEchoTask)
            return self._task
        except Exception:
            return None


# 评估报告样式: 词条按档位(档位/均值)着色, 筛选区样式
_EVAL_CSS = """
body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#f5f5f5}
.card{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.summary{display:flex;gap:24px;font-size:16px;flex-wrap:wrap}
.summary span{padding:4px 12px;border-radius:4px}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:8px 12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
th{background:#fafafa;font-weight:bold;position:sticky;top:0}
img{border-radius:4px;border:1px solid #ddd}
.stat{margin:2px 0;padding:1px 5px;border-radius:3px;border:1px solid rgba(0,0,0,0.06)}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px;background:#fafafa;padding:10px;border-radius:6px}
.filters input[type=number]{padding:2px 4px;border:1px solid #ddd;border-radius:3px}
.sep{color:#ccc}
.cnt{margin-left:auto;color:#666}
button{padding:4px 10px;cursor:pointer;border:1px solid #ddd;border-radius:3px;background:#fff}
details.rules summary{cursor:pointer;font-weight:bold;font-size:15px}
.rules-body{font-size:13px;line-height:1.75;margin-top:10px;color:#333}
.rules-body h3{margin:12px 0 4px;font-size:14px;color:#1565c0}
.rules-body ul{margin:4px 0 4px 20px}
.rules-body code{background:#f5f5f5;padding:1px 4px;border-radius:3px}
.wtable{width:auto;margin-top:6px}
.wtable th,.wtable td{padding:4px 10px}
.w{display:inline-block;margin:2px 4px 2px 0;padding:1px 6px;border-radius:3px;background:#e3f2fd;color:#1565c0}
"""

# 评估报告筛选脚本(原生 JS, 无外部依赖): 得分区间 + 判定多选 + 名称包含
_EVAL_JS = """
function applyFilter(){
  var min=parseFloat(document.getElementById('fmin').value);
  var max=parseFloat(document.getElementById('fmax').value);
  var nm=document.getElementById('fname').value.trim();
  var st=document.getElementById('fset').value;
  var vs=Array.prototype.slice.call(document.querySelectorAll('.fv'))
            .filter(function(c){return c.checked}).map(function(c){return c.value});
  var shown=0;
  document.querySelectorAll('#tbody tr').forEach(function(tr){
    var s=parseFloat(tr.getAttribute('data-score'));
    var v=tr.getAttribute('data-verdict');
    var n=tr.getAttribute('data-name')||'';
    var ok=true;
    if(!isNaN(min)&&!(s>=min)) ok=false;
    if(!isNaN(max)&&!(s<=max)) ok=false;
    if(vs.length&&vs.indexOf(v)<0) ok=false;
    if(nm&&n.indexOf(nm)<0) ok=false;
    if(st&&(tr.getAttribute('data-set')||'')!==st) ok=false;
    tr.style.display=ok?'':'none';
    if(ok) shown++;
  });
  document.getElementById('cnt').textContent='显示 '+shown+' / '+TOTAL;
}
['fmin','fmax','fname'].forEach(function(id){
  document.getElementById(id).addEventListener('input',applyFilter)});
document.getElementById('fset').addEventListener('change',applyFilter);
document.querySelectorAll('.fv').forEach(function(c){
  c.addEventListener('change',applyFilter)});
document.getElementById('fclear').addEventListener('click',function(){
  document.getElementById('fmin').value='';
  document.getElementById('fmax').value='';
  document.getElementById('fname').value='';
  document.getElementById('fset').value='';
  document.querySelectorAll('.fv').forEach(function(c){c.checked=true});
  applyFilter();
});
applyFilter();
"""


def _ratio_color(ratio):
    """词条档位着色: 单色相(蓝 hue=210)连续渐变, 深=高档、浅=低档。
    ratio=档位值/均值(约 0.65~1.35), 映射 lightness 92%(浅)→46%(深)。"""
    t = (ratio - 0.65) / 0.7
    t = max(0.0, min(1.0, t))
    lightness = 92 - 46 * t
    return f'hsl(210, 60%, {lightness:.0f}%)'


def _build_rules_html(results):
    """评估规则说明(折叠卡片) + 本次报告涉及套装的权重表 —— 让报告自带"分数/判定怎么来的"。"""
    used = {}
    for r in results:
        name = r.get("set") or "通用"
        if name not in used:
            used[name] = dict(DEFAULT_WEIGHTS) if name == "通用" else dict(get_set_weights(name) or {})
    rows = []
    for name in sorted(used, key=lambda n: (n != "通用", n)):
        weights = used[name]
        if not weights:
            continue
        items = "".join(f'<span class="w">{k} {v}</span>'
                        for k, v in sorted(weights.items(), key=lambda kv: -kv[1]))
        rows.append(f'<tr><td>{name}</td><td>{items}</td></tr>')
    weights_html = ('<table class="wtable"><thead><tr><th>套装</th><th>有效词条（权重）</th></tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table>') if rows else ''
    return f'''<details class="card rules">
<summary>评估规则（评分 / 达标线 / 判定 / 本次用到的套装权重）</summary>
<div class="rules-body">
<h3>评分</h3>
<p>条分 = <b>档位值 ÷ 该词条期望值 × 10 × 权重</b>（无效词条记 0 分，总分 = 各条之和）。<br>
<b>期望值</b> = 官方公示的<b>概率期望档位值</b>（Σ 档位值×概率，见 <code>assets/echo_probability.json</code>，统一保留 1 位小数）；官方档位概率不等（双暴低档更常见），
故期望比算术平均低约 10%（双暴）/ 2%~3%（其余）→ <b>平均档 = 10.0 分，满档 ≈ 13.1~14.0 分</b>。<br>
词条只认"落在档位表上的离散值"；详情面板前 2 行是主属性，不计入词条。词条名/声骸名走容错归一化（剥图标误读、拆字、错字）。<br>
词条后的 <code>[前 X%]</code> = 该档位在官方分布中的<b>分位</b>（概率表里 ≥ 该档的概率之和）—— 这是<b>跨词条可比</b>的质量度量：
同一句"达平均档（r ≥ 1.0）"在暴击上其实只覆盖前 53%，在暴击伤害上却是前 30%，用分位才能对齐口径（暴击 8.7 与 攻击% 8.6 都在前 22%）。</p>
<h3>达标线（锚线）</h3>
<p><b>达标线 A = 10 × 本只"出现的有效词条"的权重之和</b>（n = 词条数，L = n−1）。<br>
"有效" = 该套装启用、权重 &gt; 0 的词条；<b>基准线 B</b>（旧规则）= 该套装有效键最低 L 条之和 × 10
（配置未定制的套装即通用线 <b>11 / 18 / 26.5</b>）。<br>
A 要求"这只有效词条每条都达到自己的平均档位"（平均档 = 有价值）。出现有效词条数 k ≥ L 时
<b>A ≥ B 恒成立</b>；k &lt; L 时 A 的求和项变少、可能低于 B —— 此时该只<b>最高只能到"保留"</b>（基准线是下限）。<br>
Lv5 / Lv10 为结构判定：只要存在"首条核心词条"即通过，不限分。</p>
<h3>判定（五档）</h3>
<p>两条线：<b>达标线 A</b>（平均档水平）、<b>基准线 B</b>（旧规则线）。满级按下表逐级命中：</p>
<ul>
<li><b>达标</b>：<b>A ≥ B</b> 且 总分 ≥ A —— 达标线本身必须站在基准线之上</li>
<li><b>保留</b>：总分 ≥ B —— 过了基准门槛即算（<b>含 A &lt; B 的情形</b>：出现有效词条太少、达标线不成立的，最高只能到这档）</li>
<li><b>建议重铸</b>：值得花频整器 —— 判据是<b>「锁 L 条 + 刷 5−L 条」后能不能<b>期望达标</b></b>（穷举 L=1~4 与"锁哪几条"）：
<b>E_feat = 10 × Σw(可用池) ÷ (13−L)</b>（官方：词条类型等概率、锁定的类型不会再出现）；
<b>期望档位 r̄ = [Σ(rᵢ·wᵢ)锁定 + W_new] ÷ [Σw锁定 + W_new]</b>（新刷的那部分按档位 1.0 计）。<br>
方案要<b>同时</b>满足两道门：<b>① 重铸后的达标线站得住</b>（10×Σw_after ≥ B —— 否则这只永远达不到标，
最典型的就是"锁 1 条低权重词条 + 刷 4 条"）、<b>② r̄ ≥ 1.0</b>（等价于"期望分 ≥ 重铸后的达标线"）。
<b>③ 蒙特卡洛达标概率 ≥ 60%</b>（3000 次模拟：期望只是均值、实际约五成把握，而胚子可无限刷，
花 30 元买低概率不值）。在满足的方案里取<b>成本最低</b>（<b>成本 = max(1, L−1) 个频整器</b>），报告给出
「锁哪几条 · 刷几条 · 约多少元 · <b>达标概率</b> · 期望分 · r̄ · 届时达标线」。判据刻意不是"期望分 ≥ 保留线 B"——
那会允许"花 60 元只买到一个保留档位"</li>
<li><b>不合格</b>：其余</li>
</ul>
<p><b>得分下方的「完成度 X%」</b>：本只得分 ÷ <b>该套装 Top-5 权重词条全满档</b>的分数 —— 100% = 毕业；
只出 3 条有效的件上限天然约 72%。它同时反映"有效条数"与"档位高低"，是看"离毕业多远"的主指标。<br>
（早期版本还展示过「击败 X%」= 按官方概率模拟"随机满级声骸"分布后本只的分位；它<b>主要反映"抽到几条有效词条"</b>、
而档位高低只影响 ±40%，"5 条全最低档"就已击败 97% —— 与玩家"离毕业多远"的比较习惯不符，已<b>不再展示</b>。）</p>
<p><b>待强化</b>：未满级 且 总分 ≥ B；未达 B 则 <b>不合格</b>。<br>
<b>0 级 / 无词条</b>：无评估价值，不写入报告。<br>
<b>保留 / 建议重铸仅为报告建议，强化流程不豁免</b>（不达标仍丢弃）。</p>
<h3>套装如何判定</h3>
<p>优先读游戏详情面板的<b>套装图标</b>（与 <code>assets/echo_icons/</code> 34 套模板做灰度 ZNCC，s1 ≥ 0.60 且与次优间隔 ≥ 0.05 才采信）；
置信不足时回退"声骸名 → 套装候选"，都拿不到则按通用。报告中「套装」列可悬停查看来源。</p>
<h3>本次报告涉及的套装权重</h3>
<p>权重决定该词条算多少分，也决定达标线取哪些词条（权重越低越先被算进锚线）。</p>
{weights_html}
</div>
</details>'''


def _build_eval_html(data):
    """生成评估报告 HTML。"""
    total = data.get("total", 0)
    results = data.get("results", [])
    ts = data.get("evaluated_at", "")

    pass_n = sum(1 for r in results if r["verdict"] == "pass")
    pend_n = sum(1 for r in results if r["verdict"] == "pending")
    fail_n = sum(1 for r in results if r["verdict"] == "fail")
    zero_n = sum(1 for r in results if r["verdict"] == "zero")
    keep_n = sum(1 for r in results if r["verdict"] == "keep")
    hold_n = sum(1 for r in results if r["verdict"] == "hold")

    verdict_cn_map = {"pass": "达标", "hold": "保留", "keep": "建议重铸",
                      "pending": "待强化", "fail": "不合格", "zero": "0级/无词条"}
    color_map = {"pass": "#4caf50", "hold": "#009688", "keep": "#2196f3",
                 "pending": "#ff9800", "fail": "#f44336", "zero": "#9e9e9e"}

    rows = []
    for r in results:
        v = r["verdict"]
        color = color_map.get(v, "#888")
        vcn = verdict_cn_map.get(v, r.get("verdict_cn", ""))
        stat_lines = []
        for s in r.get("stats", []):
            detail = s.get("detail") or f"{s.get('name')}={s.get('value')}"
            ratio = s.get("ratio")
            bg = ""
            if isinstance(ratio, (int, float)):
                bg = f' style="background:{_ratio_color(ratio)}"'
            stat_lines.append(f'<div class="stat"{bg}>{detail}</div>')
        stats_html = "".join(stat_lines) or '<div class="stat" style="color:#bbb">未强化/无词条</div>'
        name = r.get("name", "")
        # OCR 原文与规范名不同(错字已被容错匹配纠正)时, 把原文放进 title 供追溯
        name_raw = r.get("name_raw") or name
        name_title = f' title="OCR 识别为: {name_raw}"' if name_raw != name else ''
        # 套装来源(resolve_set_name): icon=详情面板图标判定 / name=声骸名候选兜底 / default=通用; 旧报告无字段 → "—"
        set_name = r.get("set") or "—"
        set_src = {"icon": "套装图标判定", "name": "声骸名兜底",
                   "default": "默认(通用)"}.get(r.get("set_src"), "")
        # 主指标"完成度" = 得分 ÷ 该套装 Top-5 全满档 —— 玩家直觉的"离毕业多远"(100% = 毕业)
        # 注: 旧的"击败 X%"(相对随机产出的分位)已按用户要求**不再展示** —— 它对"抽到几条有效词条"远比
        #     "档位多高"敏感(5 条全最低档就已击败 97%), 与玩家的比较体系不符;
        #     实现仍留在 src/echo_score_sim.score_percentile 供离线分析用。
        from src.echo_score_sim import completeness
        comp = completeness(r.get("set"), r["score"])
        comp_html = (f'<br><b style="font-size:12px">完成度 {comp:g}%</b>' if comp is not None else '')
        # 建议重铸: 附"锁哪几条 / 刷几条 / 约多少元 / 达标概率 / 期望量"(reforge_plan 的结果)
        # 判据已改为**蒙特卡洛达标概率 ≥ 60%** —— "期望达标"实际只有约五成把握, 而胚子可无限刷,
        # 不值得为低概率花频整器(30 元/个); 期望量(e_feat / r̄ / 期望分)仍列出供对照
        rf = r.get("reforge")
        rf_html = (f'<br><span style="color:#999;font-size:11px">锁 {"+".join(rf["lock"])}'
                   f' · 刷 {rf["refresh"]} 条 · ≈ {rf["cost"]} 元'
                   f' · <b>达标概率 {rf.get("p_pass", 0) * 100:.0f}%</b>'
                   f' · 期望 {rf["expected"]} 分 · r̄ {rf.get("rbar", "—")}'
                   f' · 届时达标线 {rf.get("a_after", "—")}</span>'
                   ) if rf else ''
        rows.append(
            f'<tr data-score="{r["score"]}" data-verdict="{v}" data-name="{name}" data-set="{set_name}">'
            f'<td>{r["index"]}</td>'
            f'<td><img src="eval_screenshots/{r["screenshot"]}" width="180"></td>'
            f'<td{name_title}>{name}</td>'
            f'<td title="{set_src}">{set_name}</td>'
            f'<td>{r["score"]}{comp_html}</td>'
            f'<td style="color:{color};font-weight:bold">{vcn}{rf_html}</td>'
            f'<td>{stats_html}</td></tr>')

    names = sorted({r.get("name", "") for r in results if r.get("name")})
    datalist = "".join(f'<option value="{n}">' for n in names)
    set_counts = {}
    for r in results:
        name = r.get("set") or "通用"
        set_counts[name] = set_counts.get(name, 0) + 1
    set_options = '<option value="">全部套装</option>' + "".join(
        f'<option value="{n}">{n}（{c}）</option>'
        for n, c in sorted(set_counts.items(), key=lambda kv: -kv[1]))
    rules_html = _build_rules_html(results)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>声骸评估报告</title>
<style>{_EVAL_CSS}</style></head>
<body>
<h1>声骸评估报告</h1>
<div class="card">
<p>评估时间: {ts} | 共 <b>{total}</b> 个</p>
<div class="summary">
<span style="background:#e8f5e9;color:#2e7d32">达标 {pass_n}</span>
<span style="background:#e0f2f1;color:#00695c">保留 {hold_n}</span>
<span style="background:#e3f2fd;color:#1565c0">建议重铸 {keep_n}</span>
<span style="background:#fff3e0;color:#e65100">待强化 {pend_n}</span>
<span style="background:#ffebee;color:#c62828">不合格 {fail_n}</span>
<span style="background:#eceff1;color:#607d8b">0级/无词条 {zero_n}</span>
</div>
</div>
{rules_html}
<div class="card">
<div class="filters">
<span>得分: ≥ <input id="fmin" type="number" step="0.1" style="width:70px"></span>
<span>≤ <input id="fmax" type="number" step="0.1" style="width:70px"></span>
<span class="sep">|</span>
<span>判定:</span>
<label><input type="checkbox" class="fv" value="pass" checked> 达标</label>
<label><input type="checkbox" class="fv" value="hold" checked> 保留</label>
<label><input type="checkbox" class="fv" value="keep" checked> 建议重铸</label>
<label><input type="checkbox" class="fv" value="pending" checked> 待强化</label>
<label><input type="checkbox" class="fv" value="fail" checked> 不合格</label>
<label><input type="checkbox" class="fv" value="zero" checked> 0级</label>
<span class="sep">|</span>
<span>名称: <input id="fname" list="namelist" placeholder="包含匹配" style="width:130px"></span>
<span class="sep">|</span>
<span>套装: <select id="fset">{set_options}</select></span>
<datalist id="namelist">{datalist}</datalist>
<button id="fclear">清除筛选</button>
<span id="cnt" class="cnt"></span>
</div>
<table>
<thead><tr><th>#</th><th>截图</th><th>名称</th><th>套装</th><th>得分</th><th>判定</th><th>词条明细</th></tr></thead>
<tbody id="tbody">{"".join(rows)}</tbody>
</table>
</div>
<script>const TOTAL={total};
{_EVAL_JS}</script>
</body></html>'''
