# 界面修复交接（2026-11-22）— ✅ B1~B4 已全部完成

> 读者：接手修复的会话/人。先读 `CLAUDE.md` 的项目纪律，再读 `docs/UI_REVIEW_2026-11-22.md`
> （评审证据与设计方向）。**本文是可执行工单**：每一项都有现象、改法、验收命令、风险。
>
> 起点：分支 `engine/vendor`，单测 **360**；证据图在 `docs/ui_review_2026-11-22/`。
>
> ## ⚠ 进度（2026-11-22 更新）
>
> **B1 / B2 / B3 / B4 全部完成**（补记 74/75/76/77）：`python tools/ui_probe.py --strict` → **5/5**、
> `python -m unittest discover -s tests` → **465 项 / OK (skipped=2)**、
> `python tools/verify_report_js.py <报告.html>` → **11 项全 PASS**；7 页亮/暗离屏渲染逐页目检。
> 新增工具：`tests/test_ui_guards.py`（29 项）/ `tests/test_report_layout.py`（22 项）/
> `tools/ui_page_shot.py` / `tools/verify_report_js.py`。**只剩真机走查**（见 §7 末尾）。
>
> B3 实际做法（照原稿做会踩的点）：①**筛选/排序只能遍历 `tr.main`**，旧写法 `querySelectorAll('#tbody tr')`
> 会把详情行当数据行；②排序搬主行前**先取**配对详情行（`appendChild` 后 `nextElementSibling` 就变了）；
> ③详情行可见性 = 主行可见 **且** 已展开，否则筛掉的行会留孤儿详情；④报告是纯 HTML+JS，**交互必须跑浏览器验**
> （`tools/verify_report_js.py`），单测只能断言"字符串里有这段 JS"；⑤依赖说明放**页首**
> （原稿说的"页脚"在 160 行表格最底下没人看得到）；⑥HTML 不认 Markdown，正文不许有 `**`（有单测）。
>
> B2 实际做法（照原稿做会踩的点）：①运行页两栏后**日志工具条必须换行**（横排最小宽 586px → 整页 942 > 940 窗口
> 内容区 750）；②左栏只有 ~360px，5 张任务卡都得换 `WrapSettingCard`；③导航 `minimumExpandWidth` 默认 1008 >
> 本窗口最小 940，不改成 900 的话 `expand()` 会被 resize 立刻收回，且 `expand()` 必须在 `_init_geometry()` 之后调；
> ④结果表列宽**不能按 `widget.fontMetrics()` 算** —— 库的 `TableItemDelegate` 把每格字体强制成 `getFont(13)`、
> QSS 还有左右各 16px 内边距，**可用文本宽 ≈ 列宽 − 44px**（按 9pt 算会整表变 `125...`）。
>
> B1 实际做法与本文原稿的差异（照原文做会踩）：
> 1. **U-01 的 5 行子类不够**：`RIGHT_RESERVED=74` 会让文字钻到按钮底下 6px；而且"编辑区 ≥20px"≠读得出数值 ——
>    两个 31px 按钮吃掉 71px，控件 < ~105px 就把 `0.10` 显示成 `0.1C`。现已改成**问布局要预留量**
>    （`hBoxLayout.sizeHint().width()`），并把 6 个过窄的数值框加宽到 124，验收口径升级成"放得下文本 + 4px"。
> 2. **C3/C4 原来的静态检查永远 FAIL**：`_function_body` 从"行首+1"切片，正则 `^\s*def` 在字符串开头就命中
>    函数自己 → 返回 1 字符。已改成**跑真代码**（喂假 task / 假记录看输出），并把纯函数挪到零依赖的
>    `ui/present.py`（`ui/run_tab.py` 会拉起引擎，离屏建过窗口时退出会段错误 0xC0000005）。
> 3. **U-02 的调试页还要多修一层**：`QStackedWidget` 按**最高**子页预留高度（截图页预览图 min 200 → OCR 页
>    也被撑到 419），整页能滚了但日志卡仍被顶出视口；已加 `_fit_stack()` 按当前页定高。
> 4. **U-11 只做了配色这一半**（否则 C5 不可能 PASS）；行折叠/色点仍在 §5 的 B3。

---

## 0. 30 秒版

- 有 **5 个能量出来的缺陷**，已做成探针：`python tools/ui_probe.py --strict` ——
  **B1 前 0/5，现已 5/5**（后续批次别把它跑回去）。
- 按批次做，每批单独提交、单独更新文档：
  **B1（P0，约 1 天）→ B2（结构/易用）→ B3（报告）→ B4（打磨）**。
- 最要紧的一项：**所有数值输入框看不到数字**（qfluentwidgets 1.11.3 + PySide6 6.12.0 的
  SpinBox 在 Qt 6.12 下 `lineEdit` 被压成 1px）。这不是"审美问题"，是功能不可用。

```powershell
# 现状自检（应看到 5 个 FAIL）
python tools/ui_probe.py --strict             # 现在应为 5/5、退出码 0

# 回归基线
python -m unittest discover -s tests          # Ran 465 tests / OK (skipped=2)
```

---

## 1. 起点、命令与截图限制

| 项 | 值 / 命令 |
|---|---|
| 分支 | `engine/vendor`（不要合 main；沿用现有分支策略） |
| 解释器 | 系统 Python 3.13.16；`pip install -r requirements.txt` 已装齐 |
| UI 依赖 | **PySide6 6.12.0 + PySide6-Fluent-Widgets 1.11.3**（U-01 的根因组合） |
| 单测 | `python -m unittest discover -s tests` → **465**（改测试后同步 `docs/BASELINE.md` B1 与 CLAUDE） |
| 页面截图 | `python tools/ui_shot.py --size 1120x760 [--dark] [--eval] --out logs/ui_fix/light` |
| 单页/最小窗口截图 | `python tools/ui_page_shot.py <page> 892x570 out.png [--bottom]`（B1 新增；`--list` 看可选页） |
| 报告截图 | `python tools/shot_report.py logs/tmp/replay6.html --widths 1440 1024` |
| 缺陷探针 | `python tools/ui_probe.py [--strict]` |
| 评审证据 | `docs/UI_REVIEW_2026-11-22.md` + `docs/ui_review_2026-11-22/*.png` |

**截图限制（重要）**：离屏平台屏幕只有 800×800，顶层窗口会被夹住 —— `ui_shot.py --size 940x620` 实际得到
640×480。1120×760 可用（已修 `showNormal`）。最小窗口的验收**用 `tools/ui_page_shot.py`**（B1 已把它
从临时脚本转正：直接 resize 页面 widget、支持 `--bottom` 滚到底），不要拿 `ui_shot` 的 940 截图下结论。

---

## 2. 工单总表

| ID | 优先级 | 批次 | 一句话 | 主要文件 | 探针 |
|---|---|---|---|---|---|
| U-01 | P0 | B1 | 数值框看不到数值 | `ui/widgets.py` + `set_config_tab.py` + `plan_tab.py` | C1 |
| U-02 | P0 | B1 | 套装配置/调试页在最小窗口裁切 | `set_config_tab.py` / `debug_tab.py` | C2 |
| U-03 | P0 | B1 | 评估模式显示强化计数（恒 0） | `run_tab.py` + `EnhanceEchoTask.py` | C3 |
| U-04 | P0 | B1 | 评估汇总把「不合格/不建议强化」合并 | `run_tab.py` | C4 |
| U-05 | P1 | B2 | 运行页首屏看不到日志 | `run_tab.py` | 目检 |
| U-06 | P1 | B2 | 导航默认纯图标 | `main_window.py` | 目检 |
| U-07 | P1 | B2 | 图标优先/精确模式无持续指示 | `run_tab.py` | 目检 |
| U-08 | P1 | B2 | 组合穷举动作/结果都在折叠下 | `plan_tab.py` | 目检 |
| U-09 | P1 | B2 | 结果表可读性（复合列/对齐/行话） | `plan_tab.py` | 目检 |
| U-10 | P1 | B3 | 报告行 150px、词条公式墙 | `run_tab.py`（HTML/CSS/JS） | 目检 |
| U-11 | P1 | B3 | 判定色对比度 2.2~3.7:1、两套调色板 | `run_tab.py` | C5 |
| U-12 | P1 | B2 | 文案残留 Markdown `**` / 英文 | `plan_tab.py` / `dev_tab.py` | 搜索 |
| U-13 | P1 | B2 | 空状态缺失（日志/设备下拉） | `run_tab.py` / `settings_tab.py` | 目检 |
| U-14 | P1 | B2 | 设置页说明不换行、窄窗被裁 | `settings_tab.py` | 目检 |
| U-15~19 | P2 | B4 | 标题层级 / InfoBar 遮挡 / 关于页 / 开发者页 / 暗色层级 | 多 | 目检 |
| U-20 | P2 | B3 | 报告图片外链、筛选不持久、无打印样式 | `run_tab.py` | 目检 |
| U-21 | P2 | B3 | 报告规则文案漏"低置信才读明文" | `run_tab.py` | 目检 |

---

## 3. B1（P0）——先做这四项

### U-01 数值框看不到数值

**现象**：套装配置 13 个权重、低权重门槛、组合穷举所有门槛/补正/条件补正，输入框只显示上下箭头。
键盘输入也看不见。真实 Windows / 200% DPI 同样复现。

**根因**（已定位）：`qfluentwidgets 1.11.3` 的 `SpinBoxBase` 在 QAbstractSpinBox 上额外挂了
`QHBoxLayout`；Qt 6.12 下内部 `QLineEdit` 几何变成 `QRect(0, 1, 1, 31)`。`text()` 有值，但画不出来。

**改法**（已验证，最小改动）：

1. `ui/widgets.py` 末尾加：

```python
from qfluentwidgets import DoubleSpinBox, SpinBox

class _SpinFix:
    """qfluentwidgets 1.11.3 + PySide6 6.12: SpinBox 的 LineEdit 被压成 1px → 看不见数值。
    在 resizeEvent 里手动摆编辑区（右侧给两个 31px 按钮留 74px）。"""
    RIGHT_RESERVED = 74

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.lineEdit().setGeometry(9, 1, max(20, self.width() - self.RIGHT_RESERVED), self.height() - 2)

class NumberDoubleSpinBox(_SpinFix, DoubleSpinBox):
    pass

class NumberSpin(_SpinFix, SpinBox):
    pass
```

2. 两个使用文件用**别名导入**，把改动压到 import 行（调用面不变）：

```python
# ui/set_config_tab.py / ui/plan_tab.py
from ui.widgets import NumberDoubleSpinBox as DoubleSpinBox, NumberSpin as SpinBox
```

3. 全仓只有这两个文件用 SpinBox（`grep -n "SpinBox" ui/*.py` 确认）。
4. 不要改 site-packages（项目纪律）；也不要把 PySide6 盲目降级（会影响 OCR/引擎，得重跑真机）。

**验收**：

```powershell
python tools/ui_probe.py --strict        # C1 PASS
python tools/ui_shot.py --size 1120x760 --out logs/ui_fix/light
# 目检 套装配置页：权重显示 1.00 / 0.70 / 0.50…；组合穷举门槛显示 0
```

真机（Windows 200% DPI）再看一眼 `python mainui.py` → 套装配置，确认不是离屏假象。

**回归**：把 C1 的逻辑转成 `tests/test_ui_guards.py`（offscreen 可跑），至少断言
`SetConfigTab` 里所有 `DoubleSpinBox` 的 `lineEdit().width() >= 20`。

---

### U-02 套装配置 / 调试工具在最小窗口裁切

**现象**：892×570（=940×620 窗口内容区）下，模板卡、导入/导出、权重表、首条判定互相覆盖；
表格只露 1 行。证据：`docs/ui_review_2026-11-22/03_setconfig_892.png`。

**根因**：`ui/set_config_tab.py` 根是 `QVBoxLayout(self)`，`layout.addWidget(self.table, 1)`；
整页没有滚动容器。`ui/debug_tab.py` 同样（日志在 620 高时只剩 60px 且被裁）。

**改法**（套用项目已有模式，见 `settings_tab.py` 的 `make_scroll_transparent`）：

```python
from qfluentwidgets import SingleDirectionScrollArea
from ui.widgets import make_scroll_transparent   # 当前文件只导入了 WrapSettingCard, 需要补

outer = QVBoxLayout(self)
outer.setContentsMargins(0, 0, 0, 0)
scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
scroll.setWidgetResizable(True)
view = QWidget()
layout = QVBoxLayout(view)          # 原来的 layout 指向 view
layout.setContentsMargins(24, 20, 24, 24)
...
self.table.setMinimumHeight(260)    # 表格内部滚动，别跟固定卡片抢高度
layout.addWidget(self.table)        # 去掉 stretch=1
...
scroll.setWidget(view)
outer.addWidget(scroll)
```

`debug_tab.py` 同样处理；日志卡给 `setMinimumHeight(260)`。

**验收**：`python tools/ui_probe.py --strict` C2 PASS（页面级 `SingleDirectionScrollArea` 且
`verticalScrollBar().maximum() > 0`）；892×570 下目检无重叠、右侧有滚动条。

**坑**：`QTableWidget` 自己也是 `QAbstractScrollArea` —— 探针里不能用它当"页面能滚"的证据
（已踩，C2 只认 `SingleDirectionScrollArea`）。

---

### U-03 评估模式的状态卡显示强化计数

**现象**：评估跑 12 分钟，顶部一直「成功: 0 / 失败: 0 / 得分: -」。
**根因**：`ui/run_tab.py::_refresh_status` 读 `成功声骸数量/失败声骸数量/声骸得分`；
`EnhanceEchoTask.evaluate_only` 只写 `info_set('评估数量', evaluated)`（每记录一只写一次）。

**改法**：

1. 评估链：在 `_register_fail()` 里 `self.info_incr('评估失败')`（或维护计数并 `info_set`）；
   收尾时 `info_set('评估结束原因', stop_reason)`。
2. `run_tab`：把状态文本抽成纯函数，便于单测：

```python
def status_texts(task, is_eval: bool) -> tuple[str, str, str]:
    if is_eval:
        return (f"已记录: {task.info_get('评估数量') or 0}",
                f"失败: {task.info_get('评估失败') or 0}",
                "")                      # 或"已用时间"，得分在评估里没意义
    return (f"成功: {task.info_get('成功声骸数量') or 0}",
            f"失败: {task.info_get('失败声骸数量') or 0}",
            f"得分: {task.info_get('声骸得分') if task.info_get('声骸得分') is not None else '-'}")
```

`_refresh_status` 调它；`_start` 里按 `is_eval` 初始化。

**验收**：`python tools/ui_probe.py --strict` C3 PASS；用假 task 的纯函数单测覆盖两种模式；
真机跑评估时数字应随记录增长。

---

### U-04 评估汇总把「不合格 / 不建议强化」合并

**现象**：「上次评估结果」显示「不合格 36」，报告是「不合格 21 + 不建议强化 15」。
**根因**：`_update_eval_summary` 用 `verdict` 码映射，`fail → 不合格`；报告侧
（`_build_eval_html`）已按 `verdict_cn` 拆开（`run_tab.py:902-906`）。

**改法**：抽一个共享的计数函数，报告与汇总都用它：

```python
def count_verdicts(results) -> dict[str, int]:
    """六档（按 verdict_cn；旧报告没有 verdict_cn 时退回 verdict 码）。"""
    out = {"达标": 0, "保留": 0, "建议重铸": 0, "建议强化": 0, "不建议强化": 0, "不合格": 0}
    code_map = {"pass": "达标", "hold": "保留", "keep": "建议重铸", "pending": "建议强化"}
    for r in results:
        cn = r.get("verdict_cn") or ""
        if cn.startswith("保留"):        # 含「保留(词条缺失)」
            out["保留"] += 1
        elif cn in out:
            out[cn] += 1
        elif r.get("verdict") in code_map:
            out[code_map[r["verdict"]]] += 1
        elif r.get("verdict") == "fail":
            out["不建议强化"] += 1
        # zero 不入报告，忽略
    return out
```

`_update_eval_summary` 用它；`_build_eval_html` 的 pass/hold/keep/pend/fail/bad 六个计数也换成它，
避免两处口径再次漂移。展示顺序固定：达标 → 保留 → 建议重铸 → 建议强化 → 不建议强化 → 不合格，
数量为 0 的不显示。

**验收**：C4 PASS；单测：构造 2 达标 + 3 不合格 + 4 不建议强化 + 1 保留(词条缺失) →
汇总文本里六档分开、保留并入保留。

---

## 4. B2（结构/易用）

### U-05 运行页：固定状态条 + 双栏（日志必须可见）

- 现状：整页 `SingleDirectionScrollArea`（`run_tab.py:85-89`），日志卡 stretch 在滚动容器里只按
  sizeHint 分高；1120×760 只露出标题/工具栏约 70px，940×620 完全在折叠下。
- 改法（推荐）：去掉页面滚动，改成

```
QVBoxLayout(self)
├─ 状态卡（固定，含开始/停止/进度/计数/耗时 + 模式徽标）
└─ QSplitter(Horizontal)  stretch=1
   ├─ 左：设置卡组（SingleDirectionScrollArea，min 320 / 初始 360）
   └─ 右：日志卡（stretch 3，最小高 300）
```

规则说明与「上次评估结果」放左栏底部（可滚动）或改成弹窗（规则内容较长，弹窗更省空间）。
- 验收：1120×760 下不滚动就能看到 ≥6 行日志；940×620 下日志至少 200px 或整页可滚但状态条固定；
  `--eval` 模式同样。
- 风险：`HeaderCardWidget.viewLayout` 是横向的（见 CLAUDE），正文要自套纵向容器；
  日志卡 `vBoxLayout.setStretchFactor(view,1)` 别丢。

### U-06 导航默认展开

- `main_window.py:91` 只设了 `setExpandWidth(190)`，从未 `expand()`。
- 改法：`_init_navigation()` 末尾 `self.navigationInterface.expand(useAni=False)`；
  可选：退出时记住是否收起（QSettings）。
- 验收：启动即看到 7 个中文标签；窗口最小宽 940 时左栏不挤压内容。

### U-07 模式徽标

- 现状：图标优先/精确模式只在启动日志打印（`run_tab.py:516-518`）。
- 改法：状态卡加一枚 `CaptionLabel`（「套装判定：图标优先 / 精确」），随 `opt_precise` 与
  task 切换更新；报告 meta 里也写一行（`data["set_mode"]`），便于事后核对 `set_src` 分布。
- 验收：切换精确模式再开始，状态卡与报告都能看到当前模式。

### U-08 组合穷举：动作条常驻 + 方案摘要

- 现状：`run_btn/cancel/csv/progress/status` 在结果卡内（`plan_tab.py:410-425`），位于第 10 个区块，
  760 高首屏看不到。
- 改法（推荐）：把它们移出滚动区，做成页面顶部/底部的**常驻动作条**：
  `[方案摘要：5 件套 · 凝夜白霜 · 攻击 · 满级件 · 门槛 120/100] [开始穷举] [取消] [导出 CSV] [进度]`；
  结果卡保留表格，跑完 `scroll.ensureWidgetVisible(self.result_table)`。
- 验收：1120×760 首屏可见「开始穷举」；跑完自动滚到结果；改参数不用来回滚。
- 注意：`_flow_row`（流式布局）继续复用，窄窗要换行。

### U-09 结果表重排

- 现状：9 列，`评分和/有效分`（158px）比排序键 `排序分E`（88px）更宽；数字左对齐；
  `加成区 60+45+0`、`排序分E`、`共效 9.2%⚠` 都是行话；`COST` 恒 12。
- 改法：
  1. 拆列：`# | 5 只声骸 | E(排序) | 伤害 | 评分 | 有效分 | 暴击/爆伤 | 加成 属/专/通 | 共效`；
  2. 数字列 `Qt.AlignRight | Qt.AlignVCenter`，统一 1 位/2 位小数；
  3. 删 `COST` 列，状态行写「ΣCOST 12 · 5 件」；
  4. 表头/单元格 `setToolTip` 解释 E、加成、有效分、⚠；表上方一行提示「按 E 排序；评分只含副词条」；
  5. 行高控制：5 只声骸一列允许换行，但限制为 2 行（名字 + `#实例·COST` 换行）。
- 验收：1120 下无 `1...` 截断；`python tools/echo_plan.py` 结果与表一致（列语义）；截图对比。

### U-12 文案清理

- 用户可见 `**`：`plan_tab.py:170`（tooltip）、`:387`、`:451`、`:454`（结果卡说明）。
  改成普通文本或 `QLabel` 富文本（统一选一种）。
- 英文：`dev_tab.py` 的 `Run Code` / `Run(已禁用)` 改中文；技术名（BitBlt/WGC）保留。
- 全仓检查：`grep -n '\*\*' ui/*.py`（排除注释）应为 0。

### U-13 空状态

- 运行页日志空态：「等待开始 · Ctrl+Enter」；
- 设备设置的目标窗口/截图/交互下拉空态：「未检测到窗口 — 点「刷新列表」」；
- 组合穷举结果表空态：一行说明「导入库存 → 选套装 → 开始穷举」。
- 验收：断开设备/首次启动时没有空白控件。

### U-14 设置页说明换行

- `settings_tab.py` 的 `SettingCard/SwitchSettingCard` 换成 `ui.widgets.WrapSettingCard`
  （组合穷举/套装配置已用同款），或描述改 `setWordWrap(True)`。
- 验收：940 宽下「目标窗口」「截图方式」说明不被裁。

---

## 5. B3（报告）

### U-10 行折叠

- 默认行 56px：缩略图 40×64、名称、套装、COST/主属性、得分+完成度、判定色块；
  点击展开：180px 截图 + 5 行词条（数值右对齐；公式与分位放 `title`；无效词条折叠成一行）。
- 实现要点（HTML/JS 在 `_build_eval_html`）：
  - 主行 `<tr class="main" data-...>`，详情行 `<tr class="detail" hidden>`；
  - 筛选/排序只遍历 `tbody tr.main`（当前 JS 是 `querySelectorAll('tr')`，必须改，否则详情行会被当成数据）；
  - 排序移动主行时必须把配对的详情行一起移动（建议用 `row.nextElementSibling` 成对搬）；
  - 展开状态在筛选后保持或重置（选一个，写清楚）。
- 验收：1000px 高 ≥8 行；筛选/排序/展开组合正确；`data-*` 不变（加列不破坏筛选）。

### U-11 判定色阶

- 行内 `VERDICT_COLOR`（`run_tab.py:706`）与摘要 chips（`:1034-1039`）统一成一套；
  建议值（白底 ≥4.5，暗色另配）：
  `达标 #1F6B4A / 保留 #42576B / 建议重铸 #3B4E9B / 建议强化 #8A5A00 / 不建议强化 #8C3B2E / 不合格 #7A1C16`。
- 行内改成「色点 + 深色文字」或浅底 chip；摘要用同一色（深浅一致）。
- 验收：`python tools/ui_probe.py --strict` C5 PASS；目检 1440/1024。

### U-20 报告可分享/可打印

- 报告依赖同级 `eval_screenshots/`：加「导出单文件（内嵌缩略图）」或至少在页脚写明目录依赖；
- 筛选写进 `location.hash`（刷新/分享保持）；
- `@media print`：隐藏筛选条、展开所有行、去掉卡片阴影。

### U-21 规则文案

- 现在写「优先图标 → 名字兜底」，漏了「低置信 → 下滑读明文」与「精确模式」；
  改成按当前模式生成，或把两条路都写清。

---

## 6. 陷阱与边界（请先看）

1. **不要升级/降级依赖来解决 U-01**：升级 qfluentwidgets 要回归所有 Fluent 控件；降级 PySide6
   要重跑 411 项单测 + 真机 OCR。子类方案已验证，风险最小。
2. **不要改判定/评分/遍历逻辑**：本次只动呈现层；`set_src`、`text+icon` 验收闸、精确模式语义
   都是上一轮刚定的（CHANGELOG 补记 72）。
3. **离屏截图不等于真机**：SpinBox 的"看不见"是真机也复现的 bug；但反过来，离屏也缺字体
   （不注册 msyh 会出方块）。新截图先 `register_fonts`（`tools/ui_shot.py` 里有）。
4. **`--size 940x620` 目前截图会变成 640×480**（离屏屏幕 800×800 夹窗口）。最小窗口验收用
   `tools/ui_probe.py` 的 C2 或直接抓页面，不要拿截图下结论。
5. **QTableWidget 是 QAbstractScrollArea**：写"页面可滚"检查时别把它算进去。
6. **InfoBar 是叠加层**：截图里会盖住标题；这是真实效果，改布局时给它留出顶部空间或改内联提示。
7. **改报告 JS 时**：筛选、排序、计数共用 `tr` 集合；加详情行必须同步改三处（筛选/排序/显示计数）。
8. **每加一个测试/改一个测试，文档里的项数要同步**（BASELINE B1、CLAUDE 接力状态、handoff、README）——
   现为 **465**（2026-11-22 A 批 +12、B 批 +32、C 批 +9）。

---

## 7. 验收清单（每批提交前）

```powershell
python -m unittest discover -s tests                  # 期望 OK；数量按实际更新文档
python tools/ui_probe.py --strict                     # 应 5/5 PASS（B1 已达成）
python tools/ui_shot.py --size 1120x760 --out logs/ui_fix/light
python tools/ui_shot.py --size 1120x760 --dark --out logs/ui_fix/dark
python tools/ui_shot.py --size 1120x760 --eval --out logs/ui_fix/eval
python tools/shot_report.py logs/tmp/replay6.html --widths 1440 1024 --out logs/ui_fix/report
```

- B1（**已完成**）：C1~C5 PASS；套装配置 1120 截图能看到权重；`--eval` 下状态卡文案正确。
- B2（**已完成**）：目检运行页日志可见（892×570 下 11 行 / 1120×760 下 27 行）、导航有文字、
  穷举首屏有开始按钮、表格数字右对齐且不截断、无 `**`。
- B3（**已完成**）：报告 1000px 高可见 **9 行**（1440）/ **15 行**（1024）、C5 PASS、
  `tools/verify_report_js.py` 11 项全 PASS。
- B4（**已完成**）：状态卡只有一个标题、关于页有数据版本+诊断入口、代码框等宽、深色画布/卡片拉开层次
  （`ui_shot.py --dark` 逐页目检）。

真机（必须一次）：`python mainui.py` → 设备设置/套装配置/运行（评估）各看一遍，重点：
权重数值、200% DPI 下的间距、暗色、开始评估后计数是否增长。

---

## 8. 文档同步（每个批次）

| 文档 | 改什么 |
|---|---|
| `CHANGELOG.md` | 新增补记（编号接现有最后一条），写清根因/改法/验收数字 |
| `CLAUDE.md` | 「界面」「评估遍历」「接力状态」对应段落；测试数 |
| `docs/BASELINE.md` | B1 测试数；B4 截图口径（若 ui_shot 行为变了） |
| `handoff.md` | 真机状态 / 下一棒 |
| `docs/UI_REVIEW_2026-11-22.md` | 在各问题后加「已修：提交 xxx」或状态列 |

---

## 9. 附录

### 9.1 证据图

| 图 | 说明 |
|---|---|
| `docs/ui_review_2026-11-22/01_run_1120.png` | 运行页：日志在首屏之外 |
| `docs/ui_review_2026-11-22/02_plan_filled_1120.png` | 穷举结果：行话、`**`、InfoBar 遮挡 |
| `docs/ui_review_2026-11-22/03_setconfig_892.png` | 套装配置最小窗口重叠 |
| `docs/ui_review_2026-11-22/04_report_1440.png` | 报告 150px 行、公式墙 |

### 9.2 关键度量

- SpinBox：`lineEdit` `1×31px`（120×33 控件），14/14 个；抓图最暗像素 110（只有箭头）。
- 报告判定色对白底：`#4caf50` 2.78、`#009688` 3.67、`#2196f3` 3.12、`#ff9800` 2.16、`#f44336` 3.68。
- 亮色画布/卡片：`#f0f4f9` / `#f7f9fc`；暗色：`#202020` / `#272727`。
- 报告行高 ≈150px（1440）、≈250px（1024 折行）；组合穷举 33,286 组 / 0.75s。

### 9.3 文件地图（改哪里）

| 文件 | 负责 |
|---|---|
| `ui/main_window.py` | 外壳/导航/主题/几何/快捷键 |
| `ui/run_tab.py` | 运行/评估页、状态卡、日志、报告 HTML/CSS/JS、`VERDICT_*` |
| `ui/plan_tab.py` | 组合穷举页：全部输入卡 + 结果表 + CSV |
| `ui/set_config_tab.py` | 套装模板编辑（权重表/首条门槛/导入导出） |
| `ui/settings_tab.py` | 设备设置（运行模式/窗口/截图/交互/主题） |
| `ui/debug_tab.py` | 调试工具（OCR/截图/覆盖层/文件夹） |
| `ui/dev_tab.py` | 开发者（Run Code 占位 / 模板特征） |
| `ui/about_tab.py` | 关于/免责声明/链接 |
| `ui/widgets.py` | `WrapSettingCard` / `FlowLayout` / `make_scroll_transparent`（新增 NumberSpin 放这里） |
| `src/task/EnhanceEchoTask.py` | 评估/强化任务；`info_set` 计数在评估链 |
| `tools/ui_shot.py` | 7 页离屏截图（已修 800×800 问题） |
| `tools/ui_page_shot.py` | 按页面内容区尺寸抓单页（最小窗口验收；`--bottom` 滚到底） |
| `tools/ui_probe.py` | 本文 5 项缺陷探针（交接验收，`--strict` 应 5/5） |
| `tools/verify_report_js.py` | 报告交互端到端验收（QtWebEngine 真跑点击/筛选/排序/hash，11 项） |
| `tools/shot_report.py` | 报告 HTML 离屏截图 |
| `tests/test_ui_guards.py` | 界面回归守卫 29 项（B1~B4 的长期守卫） |
| `tests/test_report_layout.py` | 报告结构守卫 22 项（行折叠/打印/hash/chip/文案） |

### 9.4 探针当前输出（起点）

**B1 起点（0/5，留作对照）**

```
[FAIL] C1 SpinBox 数值可见: 14/14 个 LineEdit 宽 < 20px（首个 1px），首个抓图最暗像素 110
[FAIL] C2 套装配置/调试页可滚: SetConfigTab 没有页面级滚动容器（表格自身的滚动不算）
[FAIL] C3 评估状态显示评估数量: run_tab._refresh_status 未引用 评估数量
[FAIL] C4 评估汇总按 verdict_cn 拆分: run_tab._update_eval_summary 仍按 verdict 码合并
[FAIL] C5 报告判定色对比度 ≥4.5: 最低 pending #ff9800 = 2.16:1（需 ≥4.5）

0/5 通过
```

**B1 之后（5/5，实测）**

```
[PASS] C1 SpinBox 数值可见: 0/14 个 LineEdit 宽 < 20px（首个 37px），文本被裁 0 个，首个抓图最暗像素 0
[PASS] C2 套装配置/调试页可滚: SetConfigTab 页面滚动范围 230px，debug_tab 有滚动容器
[PASS] C3 评估状态显示评估数量: 评估 → 已记录: 7 / 失败: 2 / 结束: 到达0级尾部；强化口径不变
[PASS] C4 评估汇总按 verdict_cn 拆分: 10 只 · 达标 2 · 保留 1 · 不建议强化 4 · 不合格 3
[PASS] C5 报告判定色对比度 ≥4.5: 最低 建议强化 #8A5A00 = 5.93:1（需 ≥4.5）

5/5 通过
```
