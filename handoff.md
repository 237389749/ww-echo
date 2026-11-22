# 交接（stage 31 之后：引擎自持 + ok-ww 残留剥离 + 首条低权重门槛）

> 给下一个会话：先读 `CLAUDE.md`（项目手册，含「组合穷举」一节）与本文；功能规格原文在 `panel_plan.md`
> （末尾有「实施状态」，列了与原文的差异与定案口径）。
> **2026-11-13 会话总结**：`docs/SESSION_2026-11-13.md`（接管审核 / 对账 / 耦合 P0 的提交与未完成项）。
> **2026-11-14 会话总结**：`docs/SESSION_2026-11-14.md`（真机评估：分辨率 / 结构标定 / 布局模型 / 停止 /
> 去数量识别 / 滚动距离模型；含证据链与未验证项）。
> **2026-11-18 会话总结**：`docs/SESSION_2026-11-18.md`（遍历 54→155：滚动/列拟合/无重叠守卫；套装改读「合鸣效果区的套装名文字」；环境下界 3.10 + 依赖钉死 + 装进系统 Python；非管理员误报已修）。
> **2026-11-19 会话总结**：`docs/SESSION_2026-11-19.md`（面板链闭环：端点判据改「画面不变」/ 面板明文套装名一律采信 / COST 改主属性反推 / +0 面板不再产假记录；真机 146 条、`text` 86%；
> 下一棒 = 真机复跑验收四个数，`tools/analysis/verify_eval_run.py` 已按该口径升级）。
> **2026-11-20 会话总结**：`docs/SESSION_2026-11-20.md`（上半场 43→146 的三层根因：滚动 px/格 8→19.7、中途 0 词条=读失败、主属性百分比变体被整只跳过；**下半场 report3→report6**：逐只读套装 / 停用效果原文 / 图标锚定等级框 / +0 收工 / 主属性族通用分 / 报告筛选 / 窄窗口流式卡片。**report6 八项验收全绿（160 条，text 87%，0 失败，20.2 分钟）**，单测 349）。
> **2026-11-22 界面评审**：`docs/UI_REVIEW_2026-11-22.md`（证据 + 设计方向）+
> **`docs/UI_FIX_HANDOFF.md`（可执行工单，按 B1~B4 分批；含每项改法/验收/坑）**。
> **B1 已落地（补记 74）**：`tools/ui_probe.py --strict` **5/5**、单测 **378**；剩 B2（运行页双栏/导航/穷举动作条/
> 结果表/文案）、B3（报告行折叠/可分享/规则文案）、B4（打磨）。接手修界面的会话从 `docs/UI_FIX_HANDOFF.md` §4 起。

## 一、已完成的阶段（阶段二十四~三十已提交并 `push origin main`；阶段三十一在分支 `engine/vendor`，未合并）

| 阶段 | 提交 | 内容 |
|---|---|---|
| 二十四 | `37829ac` | 审阅驱动的统一与清理（删多入口、单一来源、debug 开关） |
| 二十五 | `54c124f` | 官方静态数据层 L0~L2（`src/wuwa_data.py` + `tools/gen_echo_data.py`） + **37 张官方套装图标** + COST/主属性进报告 |
| 二十六 | `5d32374` / `abf5468` | **界面重构**：`FluentWindow` + 左导航、卡片式页面、运行页日志卡、快捷键、尺寸/页面记忆；修深色滚动页发白 |
| 二十七 | `d51f6e3` | **主属性数值校验**（生成物 `main_props` + `src/echo_main_prop.py` + 报告 `⚠ 数值可疑`）；定案「防御百分比」 |
| 二十八 | `7246757` | 生成物补 `pieces`（套装效果的"几件套"：2 件套 31 / 5 件套 31 / 3 件套 5 / 1 件套 1） |
| — | `7d20e1d` | 交接文档 `handoff.md` + CLAUDE.md 指针 |
| **二十九** | `219357d` / `ea53b5d` | **声骸组合穷举 + 伤害排名**：`src/echo_panel.py` / `src/echo_combos.py` / `src/echo_inventory.py` / `tools/echo_plan.py` / `ui/plan_tab.py` + 单测；评估结束顺手写 `<报告>.json`；修 JSON 途径「攻击%↔固定攻击」误判 |
| — | 本次 | **首份真机评估报告(135 只)体检 + COST 漏读修复**：实时 `read_cost_badge()`(角标区 3× 放大重读) + 离线 `infer_cost()`(第 2 行反推)，当时 130 项单测 |
| **三十** | 本次 | **ok-ww 农场残留剥离**（月卡/技能热键/模板库 257→5/MouseReset/WWScene/登录窗口类/自动启动/blur/ok-ww 链接）+ **Lv5/Lv10 只认首条 + 可选 `_low_first` 低权重门槛**（轻云出月 0.1 / 前 2 档） |
| **三十一** | `09bf8b3`（`engine/vendor`） | **引擎自持**：把 ok-script 1.0.160 精简 vendor 到 `ww_engine/`（75 文件 / 10.2k 物理行），删除 150 文件 / 35.3k 行；不再依赖 `ok-script`、不再打 site-packages 补丁。**未合并 main**，等 P4 真机验收 |

**基线（改东西后必须复跑；环境/提交口径见 `docs/BASELINE.md`）**
- `python -m unittest discover -s tests` → **378 项**（`OK (skipped=2)`；需 Python **3.10+**；
  3.13 / 3.14 已实测通过，见 `docs/BASELINE.md`。引擎已 vendored，不再有缺 `ok` 的 ImportError）
- `python -c "import ww_engine; print('ok')"` → 引擎可导入（全模块导入 0 错误）；**P2 后 `import ww_engine` ≈0.21 s**
  （根包惰性导入，裸 import 不拉 cv2/qfluentwidgets/PIL/rotypes/pynput/外壳 —— 守卫在 `tests/test_engine_lazy.py`）
- `python tools/offline_eval_report.py`（109 只真实数据）→ 判定分布 `pass 38 / hold 35 / keep 0 / pending 7 / fail 29`
  （六档文案：达标 38 / 保留 35 / 建议重铸 0 / 建议强化 7 / 不建议强化 12 / 不合格 17）、
  **主属性数值可疑 0 条**、套装来源 `{icon:108, name:1}`
  ⚠ 旧的 `39/38/1/7/12/12` 是**「听唤语义之愿」权重调整前**的 `eval_report.html` 口径（与 `_core_first` 无关，
  后者对这份数据零影响）；逐套装只有听唤那一行变。复现/核对方式见 `eval_rules.md` §8 开头、CHANGELOG 补记 21。
  **⚠ 2026-11 的 Lv5/Lv10 首条改动可能改变「建议强化/不建议强化」两行**；当前仓库无 `logs/eval_debug/`，需在素材机重跑后更新 B2。
- `python tools/eval_icon_match.py` → 217/219（99.1%）
- `python tools/ui_probe.py --strict` → 界面缺陷探针 **5/5**（退出码 0；C1~C5 见 `docs/UI_FIX_HANDOFF.md`）
- `python tools/ui_shot.py [--dark]` → 离屏渲染 **7 页**（改 UI 后必跑；深色兜底见下）；
  **最小窗口**（940×620 内容区）用 `python tools/ui_page_shot.py <page> 892x570 out.png [--bottom]`（`ui_shot` 会被离屏屏幕夹成 640×480）
- `python tools/echo_plan.py --list` → 库存概览（109 只 / 47 个名字 / COST `{1:55, 3:35, 4:19}`）

## 一.5、阶段三十做了什么（2026-11-13）

**ok-ww 农场残留剥离**（用户口径："服务于声骸强化/评分用不上的都可以删；云游戏和本地两种模式都要能跑"）：
- `assets/coco_annotations.json` 257 → **5** 个特征（`echo_enhance_confirm` / `echo_dropped` / `echo_not_dropped` /
  `echo_locked` / `echo_not_locked`），`assets/images/` 43 → **3** 张；角色/战斗/地图/BOSS/登录/庭院/月卡/声骸吸收融合模板全删。
- `config.py` 删：月卡配置、`Game Hotkey`（8 个战斗键）、`monthly_card` 特征注册、`blur_area`、登录窗口类 `top_hwnd_class`、
  自动启动游戏（`calculate_pc_exe_path`/`start_exe` 恒 False）、`links`/`about`/launcher 日志、`scene`、`trigger_tasks`。
- 删 `ui/hotkey_tab.py`（8 页 → 7 页）、`src/task/MouseResetTask.py`、`src/scene/`；`BaseEchoTask` 去掉 `key_config`/`game_lang`。
- 云/本地两模式保留：`apply_run_mode` 的 exe/hwnd_class/title/Pynput/BitBlt/ratio 全部未动，只把 `start_exe` 固定为 False。
- **代码层面本来就没有自动刷图/刷声骸任务**（阶段一已删 `combat/`、`char/`、YOLO），这次清的是它的模板资产、配置与 UI 入口。

**Lv5/Lv10 首条判定**（用户口径：语义 1 + 可选低权重门槛）：
- `judge_echo` tier ≤ 2 改为**只看 `stats[0]`**：首条在 `_core_first` 内即过（旧实现 `any(...)` 允许第二条兜底）。
- 新增按套装可选的 `_low_first`：`{"below": 权重上限, "top": 前 N 档}`；首条权重 ≤ below 时必须位于该词条档位表前 N 档。
  预置给 `轻云出月`（0.1 / 前 2 档，四个专伤占位键必须 11.6 或 10.9）；其余套装不配置即不受影响。
  「套装配置」页可勾选启用并调阈值/档位名次；保存时保留 `_icon`/`_echoes`/`_low_first`。
- 新增单测：`test_judge_rules` 5 例（只认首条/低权重门槛/阈值可调/未配置不影响/轻云真实模板闭环）+ `test_echo_set_templates` 4 例（解析/默认关/非法配置/合法配置）。
- **B2 分布需在素材机重跑**：首条改动会影响 tier ≤ 2 的未满级件，当前仓库无 `logs/eval_debug/`，未重跑。

## 一.6、阶段三十一做了什么（2026-11-13）

**引擎自持**（用户口径："做 B：vendor 一份精简 ok-script；精简由你规划"）：
- 从 `ok-script==1.0.160` 复制 61 个文件（12,111 行）到 `ww_engine/`，删除 150 个文件（35,267 行）；
  实际落地 75 个 `.py` / **10,226 物理行**（8,449 非空行；含重写的外壳与包 `__init__`）。
  > 早期文档写的 8,540 是**非空行**计数，和 §1 的 12,111/35,267（物理行）不同口径；本表已按物理行改正。
- 保留：feature/Box/FeatureSet、task/task.py + TaskExecutor、device/DeviceManager + BitBlt/WGC/Hwnd + PostMessage/Pynput、
  util 子集、rotypes、overlay、最小 StartController/TaskManager。
- 重写：`ww_engine/__init__.py`（最小 OK/og）、`ww_engine/app.py`（最小 EngineApp）、`gui/StartController.py`、
  `gui/tasks/TaskManger.py`、`device/DeviceManager.py`（Windows-only）、`ScreenshotFolder`。
- 删除：ok-script 原生 GUI/resources、ADB/模拟器/浏览器/Nemu/DesktopDuplication、Genshin/PyDirect/Foreground、
  update/打包/Analytics/i18n、paperclip、paddle/rapid/dgocr/opencc 分支。
- 4 处 site-packages 补丁直接写进 vendored 代码；删除 `tools/patches/` 与安装步骤；`requirements.txt` 不再有 `ok-script`。
- 验证：`python -m unittest discover -s tests` **177 项 / OK (skipped=2)**（审核后 182）；`tools/ui_shot.py` **7 页**；
  `ww_engine` 全模块导入 0 错误；`OK(config)` + `MainWindow` 离屏集成通过；OCR onnxocr 初始化 1.3s。
- **未做/需真机**：本地/云游戏实际截图、点击、评估、强化走查；P4 真机验收清单见 `docs/ENGINE_VENDOR_PLAN.md` §6。

## 一.7、接管审核（2026-11-13，同一分支）

**结论先说**：离线基线（182 项单测 / 7 页 / 导入 0 错误）全过，但**真机 OCR 主链路原本会崩**——
离线逻辑单测和"全模块导入"都覆盖不到。已修并补守卫；P4 仍需真机跑。

- **P0：OCR 一调用就 AttributeError**（阶段三十一裁剪 TaskExecutor 时删了属性初始化，`task.py` 的
  `fix_texts()` 仍引用）：`locale` / `text_fix` / `ocr_po_translation` 三个属性只在类注解里，
  `config['ocr']['auto_simplify']=True` → 每次 OCR 走 `self.executor.locale.name()` 必炸。
  处理：按规划**删掉整段 i18n/opencc 后处理**（`fix_texts`/`fix_match_regex`/`add_text_fix` 及 4 处调用），
  OCR 结果改在 `onnx_ocr` 里 `strip()`；`ocr_fun` 只留 onnxocr，删除 rapid/dgocr/paddleocr 三个死实现；
  `config.py` 去掉 `auto_simplify`。另删 `BaseTask` 里已无实现的 `is_scene`/`wait_scene`/`adb_ui_dump`。
- **P0 邻接**：`TaskExecutor.execute` 的错误信息标题用了 `QCoreApplication.tr('app','Error')`（返回 `'app'`），
  改成 `translate('app','Error')`。
- **P1**：`ui/run_tab._copy_log` 用了未导入的 `QGuiApplication`（复制日志必炸）→ 补 import。
- **新增守卫** `tests/test_engine_task.py`（5 项）：①静态检查 `task.py` 引用的 `executor.<attr>` 都存在于
  `TaskExecutor`；②用假 OCR 走 `ocr()` → `onnx_ocr()`（strip/阈值/负尺寸/match）；③`ocr_fun` 只回 onnx。
- **真实 OCR 冒烟**：用 onnxocr + 合成帧（"暴击伤害 21.0%" / "攻击 8.0%"）跑 `task.ocr()`，
  两行置信度 0.99 / 0.97，坐标正确；模型初始化约 1.1s。
- **台账修正**：`ww_engine` 行数改物理行口径（10,226）；测试基线 177 → **182**（素材齐全 186）；
  明确阶段三十一在 `engine/vendor`（未合并 main）；`task/task.py` 实际裁到 1,163 物理行（原计划 ~1,000）。
- **仍未做**：真机 P4（本地/云游戏各一轮）；`process.create_shortcut` / GPU 探测函数等残留留第二阶段。

## 一.8、与「声骸策略工坊」对账（2026-11-13）

参考工程 `ww-echo-policy-calculator-main/`（Echo Studio，`echo_app` 3.1.0）。其求解器 `echo_policy` 是 Git 依赖，
本机没有缓存且 GitHub 不可达 → **只做了静态/数值对账，没有运行它的求解器**。
复现：`python tools/analysis/calculator_reconcile.py --check`（报告 `docs/CALCULATOR_RECONCILIATION.md`）。

**一致**：13 类词条档位表逐项相同；锁成本映射相同（1~2 锁 = 1 个频整器、3 锁 = 2、4 锁 = 3）。

**关键数字**
- 我们的 **A（达标）线在完成度上≈73.2%**（73.1%~74.8%），参考默认目标 70% —— 结构同源、只差 3.2pp；
  **B（保留）线中位 49.2%**（13 键新套 25.6%、轻云 9.6%），参考没有"保留地板"这一档。
- **通用权重几乎是 linear 爱弥斯的平均档权重，但共效偏高**：暴伤/攻击%/固定/共效 = 0.70/0.50/0.25/**0.50**；
  linear 爱弥斯 = 0.75/0.51/0.26/0.40；Wuwa 中位 = 1.01/0.65/0.32/0.35（仇远 0.70）。
  前三项与 linear 几乎一致；Wuwa 与 linear 本身不一致（critdmg/暴击 ≈1.0 vs 0.75）。
- **强化阈值可能过严**：参考测试暴露"新声骸开满 5 条 = 50 调谐器（每条 10）"；只算调谐器时 tier 4
  继续的盈亏平衡概率仅 1%~6%（tier 3: 2%~12%）。我们的 `ENCHANT_MIN_PROB=0.60` 借自重抽（30 元/次）的
  直觉，但强化每条只要 10 调谐器 —— **两者成本结构差两个数量级，判据不该共用 0.60**。
- **重抽选法不用改**：P≥0.60 下成本 1 的可行方案期望 ≤1.67，必然优于成本 ≥2；同成本取 P 最高=期望最低。
- **主属性不进评分**是结构性差异：参考总分含主词条原始分（漂泊者强化助手固定 50/120），我们的 A/B/完成度
  只算副词条 → 在"只算副词条"口径下 A 偏严。

**已落地（2026-11-13 用户拍板）**：① 通用共效 **0.6→0.5**（`DEFAULT_WEIGHTS`），**通用 B 仍固定 17.5**
（`_GENERAL_WEIGHTS` 改为固定代表档位，避免 0.6 档消失后 B 自动抬到 18.5）；② OCR 详情面板低置信重读
（任一行 <0.85 整面板重读一次取较优）+ 评估启动页面锚点「声骸N/3000」；③ `reforge_plan` 增
`expected_units`/`expected_cost` 并在报告展示。

**待拍板**：① P1 把「建议强化」与「建议重铸」的概率门拆开（或改期望调谐器对比），需真实 B2 量化影响；
② P2 主属性进评分（先做展示）。

## 一.9、底层耦合体检（2026-11-13；P0 + P1 + P2 已落地）

静态扫全仓 import（`tools/analysis/import_coupling.py`），结论见 `docs/COUPLING.md`：

- **engine 边界干净**：`ww_engine` 对 `src/ui/config` **0 条出边**；涉及 `src/ui` 的模块循环 **0**。
- **P0 已落地**：domain 改 stdlib `logging`（经 `src/logging_utils.get_logger` 走 `ww_engine.*` 命名空间复用 engine
  文件/UI handler，**不 import engine**）、删除 `src/globals.py` + `config['my_app']`、
  删除 `process_feature` 空实现、`MODE_*` 移到 `src/run_modes.py`、UI 改走 engine 根 API
  （`og`/`communicate`/`basic_options`，`Alert` 改公共 notification）。
- **P1 已落地（`5a0ee55`）**：`parse_number`/`normalize_stat`/`dedup_key` → `src/echo_parse.py`，
  `compute_weighted_score` → `src/echo_scoring.py`；`EnhanceEchoTask` 保留同名**薄封装**（调用面不变，
  等价性 `tools/analysis/p1_equiv_check.py` 152 例 0 差异）；`src.echo_inventory` 改走 domain 并删掉
  “借 task 实例算分”的桩；task adapter 改 engine 根 API（`get_bounding_box`/`clear_folder`）并把任务图标置 `None`
  → **不再 import Qt**。
- **P2 已落地（`343d80b`）**：`ww_engine/__init__` 改 **PEP 562 惰性导入**（`_LAZY_IMPORTS` 覆盖
  `EngineApp`/`DeviceManager`/`TaskExecutor`/`TaskManager`/`BaseTask`/`TriggerTask`/`FindFeature`/`OCR`/
  `Box`/`get_bounding_box`/`Feature`/`FeatureSet`；`OK` 内部改函数内 import）；engine 核心去 `FluentIcon`
  （`ConfigOption(icon=None)` / `task.group_icon=None` / `translate` → 字面量）→ `qfluentwidgets` 退出 engine 导入链；
  守卫 `tests/test_engine_lazy.py`（子进程实测裸 import 不拉重依赖 + `__all__` 惰性来源同一对象）。
- **第三阶段已落地（`058bee9`）**：应用外壳拆成 **`ww_app_shell/`**（`EngineApp`/`StartController`/overlay/
  `show_alert`）；`ww_engine/gui` 只留 `Communicate`（QtCore 信号中枢）与 Qt-free 的 `alert_info/alert_error`；
  `og` 下移到 `ww_engine/locator.py`（根包再导出）→ 消掉 根包↔外壳 环；任务管理器改到 `ww_engine/task/TaskManager.py`。
- **结果**：P0 后 domain→engine / UI→entry / entry→task / UI→engine 内部归零；**P1 后 domain→task_adapter 也归零**，
  `import_coupling.py` 违规表为空；**P2 后 engine Qt 6 个**；**第三阶段后 engine Qt 只剩 1 个**（`gui/Communicate`，
  QtWidgets 全在 `ww_app_shell`），模块级 SCC **只剩 rotypes 上游 4 模块**（体检工具修了 `from . import X` 的假边之后）。
- **import 成本（P0 前→P0 后→P1 后→P2 后）**：`echo_set_templates` 0.95→0.05→0.038→**0.031 s**、
  `echo_icon_match` 1.07→0.20→0.174→**0.162 s**、`echo_combos` 1.05→0.073→0.062→**0.056 s**、
  `echo_inventory` 0.94→0.85→0.177→**0.173 s**、`echo_plan` 0.99→0.85→0.208→**0.177 s**、
  **`ww_engine` 0.97→0.90→0.76~0.90→0.21 s 量级**（相对 QtCore 增量 ≈0.08 s，`communicate` 保持 eager）；
  `ww_app_shell` 0.49~0.74 s（只在开窗口时付）。⚠ 这台机器的 QtCore import 在 0.13~0.50 s 间波动，
  文档一律标区间，判据看「相对增量 + 成分」。
- **下一步**：耦合只剩 BOM 清理。**不要**为了 `og`、把 0.2 s 压到 0.03（惰性化 `communicate`）或 Rust 去重写 engine/UI。

## 二、阶段二十九做了什么（组合穷举）

**分层**：`echo_panel.py`（面板聚合 + 伤害）→ `echo_combos.py`（穷举 + Top-K）→ `echo_inventory.py`（库存导入）
→ `tools/echo_plan.py`（CLI）/ `ui/plan_tab.py`（界面）。**界面不碰伤害公式**（同"判定唯一收口"的纪律）。

**契约（用户已定，实现必须遵守）**：模式 `5` / `3+2`（两套时**必须指定 4C 归属**）；5 只**互异**（按名字）、
`ΣCOST ≤ 12`、只用 5★、**套装计数按去重只数**；补正**一律视为生效**（不做件数条件判定）；
套装效果**不自动解析**；伤害 `E = 缩放属性总值 × (1+暴击率×暴击伤害) × (1+加成区)`，
加成区 = 属伤 + 专伤合计（各类型直接相加）+ 通用增伤，**共效不计**。

**四个"必须记住"的口径（都有实测依据）**
1. **面板 = `基础值 × (1 + 百分比/100) + 固定值`**（calculator 源码 formula 原文；**固定值在括号外**）。
   裸面板的 `攻击/生命/防御` 填**基础值（角色+武器，不含声骸）**，不是游戏内面板总值。
2. **声骸面板有 2 行主属性，两行都算**：第 1 行 = 主属性；第 2 行 = **COST 固有属性**
   （COST1 生命 2280 / COST3 攻击 100 / COST4 攻击 150，满级；`0064`/`0001` 两张面板已逐张看图核对）。
3. **`攻击/生命/防御` 有固定与百分比两个变体**：报告路径按 `%` 判，JSON 路径按官方取值网格判
   （`echo_main_prop.candidates()`）；**别只看名字就当固定值**。
4. **5★ 无法从评估产物判定**（没有稀有度字段）→ 导入即视为 5★，由用户口径保证。

**实测规模**：109 只数据集、`息界同调之律(10) + 听唤语义之愿(12)` 的 3+2 → 候选 22 只 / 11 个名字 /
**评估 3330 组 / 0.075 s**；排列合理（前 5 名差距 0.9%~1.9%）。

**样例输入（注意：裸面板是占位值，不是用户真实数据）**
```
python tools/echo_plan.py --mode 3+2 --set-a 息界同调之律 --set-b 听唤语义之愿 --cost4 A \
    --scaling 攻击 --bare 攻击=1200 --bare 暴击=5 --bare 暴击伤害=150 \
    --corr 重击伤害加成=30:套装3件套 --corr 声骸技能伤害加成=16:套装2件套 --corr 气动伤害加成=10:天赋
```

## 三、数据面（关键认知，别再走弯路）

### 首份真机评估报告（2026-10-08 22:50，135 只 / 48 个名字，`eval_report_202610082251.json`）

- 判定分布 `保留 54 / 达标 45 / 不合格 18 / 建议强化 15 / 不建议强化 3`（无"建议重铸"）；
  `层级 = 1 词条 17 / 3 词条 1 / 5 词条 117`；套装来源 `icon 118 / name 16 / default 1`；主属性数值可疑 **0**。
- **COST 角标漏读 27/135(20%)**（报告里这 27 只没有 COST，也没有官方主属性方案判定）→ 已修两处：
  ① 实时 `read_cost_badge()`：1× 读不到时只截角标区(0.685,0.19–0.792,0.25)放大 3× 再 OCR（用那 27 张截图
  离线验证 **27/27 读回**）；② 离线 `infer_cost()`：用第 2 行 COST 固有属性反推（1C 生命 std456 /
  3C 攻击 std20 / 4C 攻击 std30）。**交叉验证：角标与反推一致 108/108、缺失 27/27 反推出、0 不一致。**
  修完库存 135 只全部有 COST `{1:64, 3:54, 4:17}`。
- 未满级件 18 只，几乎都是 1 词条（`格洛犸图×6`/`风鳞蜃甲×3`/`共鸣回响·冠顶苍隼×3`…）——
  组合穷举**默认只用满级件**（`PlanRequest.max_level_only=True`，UI 勾选 / CLI `--all-levels` 反开关），
  要"看现有全部件"时取消勾选。
- 名字层残留：`风鳞屋甲`（应 `风鳞蜃甲`，图标也没救回来）落"通用"被排除；`侏侏'`/`阿磁磁` 是既有容错链已知失效类。
- **可跑性速查**（同套 5 件 / 3+2 当 3 件 / 当 2 件）：
  长路启航之星 8 名 ✓✓✓ · 隐世回光 11 ✓✓✓ · 轻云出月 10 ✓✓✓ · 雪落无声之愿 8 ✓✓✓ ·
  流金溯真之式 6 ✓✓✓ · 听唤语义之愿 6 ✓✓✓ · **息界同调之律 4 名、无 4C → 只能当 3+2 的一份**
  （要 4C 的话归属必须选有 4C 的那套：听唤语义之愿/雪落无声之愿/隐世回光/轻云出月/长路启航之星/流金溯真之式）。
- 试跑：3+2（息界同调之律+听唤语义之愿，4C 属 A）候选 25 只 / 2660 组 / 0.06s；
  同套 5（息界同调之律）**0 组** —— 因为该套只有 4 个名字（契约要求 5 只互异），不是 bug。

### 首次真机角色排名（2026-10-09：爱弥斯 / 绯雪，两套同套 5 件）

契约与口径都按"面板值 + 补正"喂进去（`攻击补正 30%` 记在 **攻击百分比**；`热熔/冷凝增伤补正` 记在对应**元素伤害加成**）：

- **爱弥斯**（长路启航之星 ×5，攻击模型，裸面板 攻击 1133 / 暴击 37.3% / 爆伤 150% / 热熔 32%，
  补正 暴击 +20、热熔 +30、攻击% +30）：候选 **19 只 / 8 名字 / 2799 组**。
  第 1 名 = `双极·渊陨重锋3C + 岩蛛S4型1C + 影烁者1C + 格洛犸图3C + 辛吉勒姆4C`（ΣCOST 12）→
  攻击 **3036.5**（1133×(1+132.7%)+400）、暴击 96.0% / 爆伤 265.4%、加成区 **155.4%**（热熔 92 + 专伤 63）→ E 27514。
- **绯雪**（雪落无声之愿 ×5，攻击模型，裸面板 攻击 1300 / 暴击 37.3% / 爆伤 150% / 冷凝 0，
  补正 暴击 +25、冷凝 +20、攻击% +30）：候选 **17 只 / 8 名字 / 672 组**。
  第 1 名 = `共鸣回响·鸣式·虚造神型4C + 冰盈舞者1C + 影烁者1C + 格洛犸图3C + 霜鳞蜃甲3C` →
  攻击 **3424.5**、暴击 103.8%（→100）/ 爆伤 225.0%、加成区 **125.4%**（冷凝 50 + 专伤 75）→ E 25086。
- 本轮顺带修/加的三处（都有实测依据）：
  **① 默认只用满级件**（`PlanRequest.max_level_only`，UI 复选框默认勾选 / CLI `--all-levels` 反开关）；
  **② 暴击率 100% 封顶**（实测组合会到 112%~119%，不封顶会把溢出当收益 —— 对绯雪的排名影响明显）；
  **③ 折掉完全重复的实例**（评估 `dedup_key` 键在原名上，OCR 把 `·` 读成 `・` 时同一只会被记两次 → 成对同分组合）。
- 手动核对：两套 Top-1 的 攻击/暴击/爆伤/加成区**逐项与词条相加一致**（见 `.scratch/verify_tops.txt`）。

- **所有游戏表数据都在 `search/wwdata37`**（`Arikatsu/WutheringWaves_Data` @3.7 的稀疏检出，表被转成 **JSON**）：
  `BinData/{phantom, phantommanageplan, property, item, drop, monster_Info, monsterDisplay, ui_resource, role, weapon, skillTree}` + `Textmaps/zh-Hans`。
- 扩容：`cd search/wwdata37; git -c http.proxy= -c https.proxy= sparse-checkout add BinData/<表名>`
  （本机 git 全局配了 `http.proxy=127.0.0.1:7890`，代理没开时**必须**用这个 -c 覆盖走直连）。
- **外接盘 E: 只对 UI 贴图有用**（`tools/icon_export/`）；表数据不需要它。
- **库存导入的数据源**：① **「运行」页评估后保存报告时同目录写出的 `<报告名>.json`（首选）** ——
  含 名字/套装/COST/主属性/词条，`tools/echo_plan.py --inventory <它>` 或页面「选择…」直接导入；
  ② `logs/eval_debug/<时间戳>/`（`image_report.md` + `<tag>_full.png` 图标识别定套装；需要
  `SAVE_DEBUG_DATASET=True` 且那份 `image_report.md` 是另外转录的）。
  **两条途径已用 109 只真实数据验证逐只等价**（`test_json_roundtrip_matches_dir_path`）。
  **注意**：JSON 途径没有 `%` 也没有等级，`攻击/生命/防御` 的固定 vs 百分比只能靠"词条数收窄官方网格窗口"判
  —— 这里踩过坑（满级 `攻击% 30.0` 曾被当成固定 30），改动这张表前先看
  `normalize_main_prop` 的 docstring 与那两个回归用例。

## 四、下一棒（按价值排序）

> **2026-11-22 界面修复（最先做）**：`docs/UI_FIX_HANDOFF.md` —— P0 五项：
> SpinBox 数值不可见（qfluentwidgets 1.11.3 + PySide6 6.12）/ 套装配置最小窗口重叠 /
> 评估状态显示强化计数 / 汇总合并「不合格·不建议强化」/ 报告判定色对比度不足。
> 探针：`python tools/ui_probe.py --strict`（现在 0/5）。评审证据：`docs/UI_REVIEW_2026-11-22.md`。
>
> **2026-11-20 下半场后的优先项**（详见 `docs/SESSION_2026-11-20.md` §11）：
> ①再真机跑一轮确认 report6 稳定（160 条 / text≥85% / 0 失败 / ≈20 分钟）；
> ②定 **共效口径**（`DEFAULT_WEIGHTS` 0.5 vs 37 套模板 0.6）；
> ③3 套 3.7 新套（茜染/衔梦/镜影）仍是 13 键种子（专伤 0.4、生命/防御 0.5），要不要按定位自定义；
> ④`+5` 面板图标 0.34~0.47（0.6 门槛）top-1 正确，可加"候选集约束 + 降门槛"。

1. **与 wuwa-calculator 对账**（`panel_plan.md` 步骤 4，最强的正确性验收）：同一组输入喂两边，伤害应一致。
   参考页 `.scratch/refs/wuwacalc.html`（`calculateDamage()` 在 ~49856 行；分区 formula 在 ~48307 行）。
   对账时要盯：① 固定值在括号外 ② 声骸 COST 固有属性算不算面板贡献 ③ 抗性默认（calculator 默认 20%，
   我们默认 10%）。
2. **真机界面走查**：导入库存 → 选套装/模式/4C 归属 → 填裸面板与补正 → 开始穷举 → 双击看明细 → 导出 CSV；
   顺带核对阶段二十六~二十八 的界面项（运行页日志卡、InfoBar、深色）。
3. **用户真实裸面板**：拿到后重跑一次，出真实排名（样例里的 1200 / 5% / 150% 是占位）。
4. **5★ 判定**（若要严格）：用主属性数值网格反推（不符网格 = 疑似 4★ 或 OCR 误读），见 `src/echo_main_prop.py`。
5. 图标识别兜底到强化模式 / 黑边校准（触发条件见 `CLAUDE.md`）。

## 五、跨会话的坑与经验（省时间）

- `HeaderCardWidget.viewLayout` 是**横向**的 → 正文自套纵向容器 + `card.vBoxLayout.setStretchFactor(card.view, 1)`；
  `TableWidget` 构造只收 `parent`；需要 `ConfigItem` 的 SettingCard 家族不要用。
- **`ComboBox` 没有 `setEditable`** → 用 `EditableComboBox`（补正来源下拉踩过）。
- 深色：`QScrollArea` viewport 用 palette 画底 → 必须过 `ui/widgets.make_scroll_transparent`；
  **不要**在 `apply_theme` 里手动 unpolish/polish 整树。
- **受限沙箱里 `QSettings` 写不进注册表**（写后读回 None）→ `tools/ui_shot.py --dark` 原本会静默出浅色图；
  已加兜底（`show()` 后再 `apply_theme("DARK", remember=False)`）。另外**直接 grab 一个裸 QWidget 会得到白底**
  （没有窗口背景）→ 要照"已填数据"的页面时，把它挂进 `FluentWindow` 再 grab（见 `.scratch/plan_page_shot.py`）。
- **别再用 `python -c "..."`**（PowerShell 引号/编码反复踩坑）→ 一律写成 `.py` 文件执行；
  要看中文输出就 `Out-File -Encoding utf8` 再用编辑器读（控制台是 GBK，直接看会乱码）。
- **`.scratch/` 不在版本库里**（它在 `ww-echo` 父目录）：本文与 CLAUDE 引用的 `.scratch/xxx.py` 只在本机存在。
  脚本/期望输出的索引与基线口径见 `docs/BASELINE.md`；新增复现脚本请放 `tools/analysis/`。
- `BinData.pairs()` 返回 **(件数, fetter_id)**（件数在前）。
- **真机状态（2026-11-20 更新）**: 评估已真机跑到 **report6：160 条、八项验收全绿**（`verify_eval_run.py`；
  text 139/160=87%、effect 0、重复 0、回顶 0、缺 COST 0、失败 0、20.2 分钟、`+0` 收尾）。**仍未验证**：
  强化 `run()` 的"切下一只"推进、「组合穷举」页数据填充走查、与 wuwa-calculator 的对账。
- **2026-11-20 晚：评估改成「图标优先」**（见 CHANGELOG 补记 72）：多候选名字先读固定表头的图标/环色，
  不滚面板；「精确模式」勾选 = 总是下滑读合鸣效果明文。依据 report6 139 张面板回归（top-1 99.3%、闸内 100%）
  + 下滑占整轮 46%。**需要再真机跑一轮拿新耗时基线**（预期 ≈12 分钟，`set_src` 以 `icon` 为主，
  验收闸已改为 `text+icon ≥85%`）。
- **⚠ 待决策（用户拍板后我再动手）：达标不拦"有效词条太少"**（2026-10-09，CHANGELOG 补记 13 /
  `eval_rules.md` §7）：达标只看 `A ≥ B` 且 `score ≥ A`，而 A 只统计"出现的那几条" —— 5 词条的件**只有 3 条有用**
  也可能达标（实测 #1 虚造神型 k=3 / A=21.0 / B=18.5 / score 22.51）。新报告满级 117 只里 **k < tier−1 有 61 只**，
  其中 **16 只仍判达标**。推荐口径 (a) `k < tier−1` 最高只能"保留"。分析脚本 `.scratch/why_pass.py`（本机，未入库）。
- **离线重放评估有两条路**（改评分/判定后不用开游戏）：①`tools/offline_eval_report.py`（素材目录，走 OCR+图标）
  ②`--from-json <报告.json>`（**最快**：直接用报告数据 + 当前套装配置重算，截图沿用）。
  改套装权重（如听唤共效 0.4→0.9、重击置 0）后就用它出对比报告。
