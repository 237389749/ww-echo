# 底层耦合体检（2026-11-13；P0 + P1 + P2 + 外壳拆分 已落地）

> 目的：回答“引擎自持之后，`ww_engine` / `ww_app_shell` / `src` / `ui` / `config` 的依赖方向还乱不乱”。
> 方法：`tools/analysis/import_coupling.py` 静态扫全部 `.py`（stdlib，不 import 项目），
> 按层统计唯一 import 对、跨层违规、UI 对 engine 内部模块的 import、Qt 直接依赖、模块级循环；
> 另用 `--timing` 实测 import 耗时。
>
> **状态**：2026-11-13 完成体检，并已落地 P0（§0.1）、P1（§0.2）、P2（§0.3）、第三阶段外壳拆分（§0.4）；
> 只剩 BOM 清理（§6）。
> 复现：`python tools/analysis/import_coupling.py --out logs/analysis/coupling.md --timing`

## 0. 一句话结论

**引擎边界干净（0 条 engine→项目代码）；P0 + P1 之后跨层反向依赖全部归零** ——
domain→engine、**domain→task_adapter**、UI→entry、entry→task、UI→engine 内部都是 **0**，
`import_coupling.py` 的违规表为空。

P1 之后 `src.echo_inventory`（以及 CLI `tools.echo_plan`）不再经过 task adapter →
**不 import PySide6 / qfluentwidgets / ww_engine**，import 从 ≈0.85 s 降到 **0.18 / 0.21 s**。

P2 之后 `import ww_engine` 从 **0.90 s → 0.21 s**（目标 <0.5 s）：根包只 eagerly 导入
「stdlib + QtCore（`communicate`）+ psutil」，`EngineApp`/`DeviceManager`/`TaskExecutor`/`TaskManager`/
`BaseTask`/`FeatureSet` 等走 PEP 562 `__getattr__` 按需导入；engine 非 GUI 核心里的 `FluentIcon` 已去掉
（qfluentwidgets 从根包导入链上彻底消失）。

第三阶段把**应用外壳**拆成独立包 `ww_app_shell/`（`EngineApp`/`StartController`/overlay/`show_alert`）：
engine 里直接 import Qt 的模块从 **6 个降到 1 个**（`gui/Communicate.py` 的 `Signal` 中枢），
QtWidgets 全部落在 shell；`og` 下移到 `ww_engine.locator`，静态依赖图**只剩 1 个上游自带的 SCC**
（`rotypes` 4 模块），根包↔外壳的环已消除。
全局单例（`og`、`communicate`、`OK.exit_event`）是**运行时服务定位**，不是 import 环；domain 自己不碰 `og`，
不建议为了“消灭 og”重写。

## 0.1 P0 已落地（2026-11-13）

| # | 改动 | 结果 |
|---|---|---|
| 1 | `echo_icon_match` / `echo_set_templates` 改用 stdlib logging，但 logger 名走 `ww_engine.<module>`（`src/logging_utils.py`），复用 engine 的文件/UI handler，**不 import engine** | domain→engine **0**；`echo_set_templates` import **0.95 s → 0.05 s** |
| 2 | 删除 `src/globals.py` + `config['my_app']` | domain→engine/Qt 又少 1 条（死文件） |
| 3 | 删除 `src/task/process_feature.py` + `feature_processor` 配置项 | entry→task **0**；`FeatureSet` 默认 `None` 行为一致 |
| 4 | 新增 `src/run_modes.py`（`MODE_LOCAL/MODE_CLOUD`），`config` 再导出；UI 直接 import domain | UI→entry **0**；entry→domain +1（正常方向） |
| 5 | UI 改走 engine 根 API：`from ww_engine import og, communicate, basic_options`；`debug_tab` 的 `Alert` 改成公共 `communicate.notification` | UI→engine 内部 **0**；`tools/ui_shot` 同步改根 API |

`mainui` 仍从 `config` 拿 `MODE_LOCAL/MODE_CLOUD`（`config` 再导出），这是 entry 内部引用，不算违规。

## 0.2 P1 已落地（2026-11-13）：纯函数抽到 domain + task adapter 少碰 engine 内部

| # | 改动 | 结果 |
|---|---|---|
| 1 | 新增 **`src/echo_parse.py`**：`parse_number` / `normalize_stat`（task 侧原名 `_normalize_stat`）/ `dedup_key`，连同逐字白名单 `_STAT_CHARS`、LCS 回退、名字标点清洗 | OCR 文本解析彻底留在 domain |
| 2 | 新增 **`src/echo_scoring.py`**：`compute_weighted_score`（档位/期望×10×权重，口径逐行未动） | 评分纯计算留在 domain |
| 3 | `EnhanceEchoTask` 保留同名**薄封装**：静态方法 `_normalize_stat` / `dedup_key`、实例方法 `compute_weighted_score`（它仍负责 `set_name=None → config['当前套装']` 这一句任务运行时默认值）；模块级 `parse_number` 再导出 | **调用面不变**：线上评估 / `tools/offline_eval_report.py` / 测试仍走同一入口 |
| 4 | `src.echo_inventory` 改从 `src.echo_parse|echo_scoring` import，删掉“借 task 实例算分”的 `_SCORE_TASK` 桩 | **domain→task_adapter 0**（最后一条硬违规清零） |
| 5 | task adapter 少碰 engine 内部：`ww_engine.feature.Box` / `ww_engine.util.file` → 根 API（`get_bounding_box` / `clear_folder`，后者补进 `__all__`）；`FluentIcon.ADD` → `None`（本项目 UI 不渲染任务图标） | task adapter **不再直接 import Qt / engine 内部模块**（§4） |

等价性证据：`python tools/analysis/p1_equiv_check.py`（默认对比 P1 前提交 `3e698cf`）——
四个函数在 152 个边界样本上**逐例 0 差异**（含 `details` 明细字符串）。
**无 Qt 环境验收**：用 `sys.meta_path` 屏蔽 `PySide6` / `qfluentwidgets` / `ww_engine` / `shiboken6` 后，
`import src.echo_inventory` 与 `import tools.echo_plan` 都成功，且 `sys.modules` 里这些前缀**一个都没有**
（`echo_score`/`dedup_key` 也照常算分）—— P1 的验收条款“CLI 不再需要 Qt”成立。

## 0.3 P2 已落地（2026-11-13）：根包惰性导入 + engine 核心去 `FluentIcon`

| # | 改动 | 结果 |
|---|---|---|
| 1 | `ww_engine/__init__.py` 只 eagerly 导入轻依赖（`Config`/`ConfigOption`/`GlobalConfig`/`basic_options`/`Handler`/`Logger`/`process`/`file`/`communicate`/异常）；`EngineApp`/`DeviceManager`/`TaskExecutor`/`TaskManager`/`BaseTask`/`TriggerTask`/`FindFeature`/`OCR`/`Box`/`get_bounding_box`/`Feature`/`FeatureSet` 登记进 `_LAZY_IMPORTS`，由 **PEP 562 `__getattr__`** 按需导入并缓存（含 `__dir__`，子包如 `rotypes` 有兜底） | `import ww_engine` **0.90 s → 0.21 s**；裸 import 后 `sys.modules` 里没有 cv2/PIL/qfluentwidgets/rotypes/pynput |
| 2 | `OK` 内部（`app` property / `do_init` / `init_device_manager`）改成**函数内 import**：重模块只在真跑引擎时才拉起 | `from ww_engine import OK, og` 不再暗示 QtWidgets；`from ww_engine import EngineApp` 用法不变 |
| 3 | engine 核心去 `FluentIcon`：`util.config.ConfigOption(icon=None)`、`util.GlobalConfig` 不再传 icon、`task.task` 的 `group_icon=None` | **qfluentwidgets 从根包导入链上消失**（它单独值 ≈0.6 s）；`ConfigOption.icon` 全仓无消费者 |
| 4 | `task.TaskExecutor` 的 `QCoreApplication.translate('app','Error')` → `'Error'`；`task.task` 的 NPU 驱动报错同样改字面量（引擎 i18n 已在补记 22 删除，`translate` 本就原样返回）；`gui.util.Alert` 的 `QMessageBox` 改成函数内导入 | engine 非 GUI 核心的 Qt 依赖只剩 `app`（壳），见 §0.4 |
| 5 | 新增守卫 `tests/test_engine_lazy.py`：① 子进程实测「裸 import 不拉重依赖」② `__all__` 全解析且惰性名字与直接子模块导入**同一对象** | 谁再把重 import 加回 `__init__` 顶部，单测立刻红（测试基线 182 → 184） |

**代价/取舍**：`import ww_engine` 的 QtCore 部分（`communicate` 是 `Signal` 中心，所有 UI/引擎消费方都要它）
是刻意的地板 —— 再往下压就要把 `communicate` 做成惰性代理，收益只对手写脚本有意义，
本轮刻意不做（见 §6“不建议做”）。

## 0.4 第三阶段已落地（2026-11-13）：应用外壳拆成 `ww_app_shell`

| # | 改动 | 结果 |
|---|---|---|
| 1 | 新建 **`ww_app_shell/`**：`app.py`（EngineApp）、`start_controller.py`（StartController）、`overlay_window.py` / `overlay_widget.py`（覆盖层）、`alert.py`（`show_alert` 的 QMessageBox）。`ww_engine/app.py`、`gui/StartController.py`、`gui/overlay/`、`gui/debug/` 删除（`git mv` 保留历史） | **QtWidgets 全部离开 engine**；engine 里直接 import Qt 的模块 **6 → 1**（`gui/Communicate.py`） |
| 2 | `ww_engine/gui/util/Alert.py` 只留 `alert_info`/`alert_error`（纯 `communicate.notification` 信号，无 QtWidgets）；`show_alert` 移到 `ww_app_shell/alert.py`。`gui/tasks/TaskManger.py` → `ww_engine/task/TaskManager.py`（本来就不是 GUI） | `gui/` 只剩信号中枢与空 `__init__` |
| 3 | **`og` 下移到 `ww_engine/locator.py`**（`OkGlobals` + `og`，根包 re-export）：外壳只依赖 `ww_engine.locator` 等**具体子模块**，不再 import 根包 → 消除 `根包 ↔ 外壳` 的模块级环 | SCC：**只剩 1 个**（`rotypes` 4 模块，上游自带）；`涉及非 engine 模块的环 = 0` |
| 4 | 组合根保留外壳入口：`ww_engine/__init__.py` 的 `_LAZY_IMPORTS['EngineApp'] = ('ww_app_shell.app', ...)`、`OK.app` 函数内 import 外壳；`from ww_engine import EngineApp/OK` 用法不变 | engine→shell 只有 **1 条边**（组合根），shell→engine **18 条**（正常方向） |
| 5 | 守卫扩到 4 项：新增「engine 里只有组合根能 import `ww_app_shell`」「外壳不许 import engine 根包」（AST 判定，注释/文档串不算） + 裸 import 不许拉起 `ww_app_shell` | 测试基线 184 → **186** |

**为什么 `communicate` 留在 engine**：它被 `device/*`、`feature/FeatureSet`、`task/*`、`util/config`、`util/logger`
共 7 个核心模块直接 emit；搬走会让 engine→shell 变成到处都有的边，而它只依赖 QtCore（`Signal`/`QObject`）。
它是“engine ↔ UI 的契约面”，单点 Qt 依赖是刻意的取舍（§6“不建议做”）。

## 1. 分层与矩阵（外壳拆分后）

| 层 | 范围 | 允许依赖 |
|---|---|---|
| engine | `ww_engine.*` | 只能依赖第三方 + engine 自己；**只有 `ww_engine/__init__.py`（组合根）可引用 shell** |
| shell | `ww_app_shell.*` | engine 的**具体子模块**（不得 import engine 根包）+ Qt |
| domain | `src.*`（不含 `src.task`） | 标准库 + domain 自己（**不依赖 engine/task_adapter/ui/entry**） |
| task_adapter | `src.task.*` | domain + engine 根 API |
| ui | `ui.*` | domain + engine 根 API + Qt |
| entry | `config.py` / `mainui.py` | ui + engine + domain |
| tools/tests | `tools.*` / `tests.*` | 任意（工具/测试允许跨层） |

**跨层唯一模块对**（行=importer，列=imported；`—` 是层内/对角不统计）：

| importer \ imported | engine | shell | domain | task_adapter | ui | entry | tools | tests |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| engine | — | **1** | 0 | 0 | 0 | 0 | 0 | 0 |
| shell | **18** | — | 0 | 0 | 0 | 0 | 0 | 0 |
| domain | 0 | 0 | — | 0 | 0 | 0 | 0 | 0 |
| task_adapter | 2 | 0 | 6 | — | 0 | 0 | 0 | 0 |
| ui | 6 | 0 | 11 | 1 | — | 0 | 0 | 0 |
| entry | 1 | 0 | 1 | 0 | 1 | — | 0 | 0 |
| tools | 1 | 0 | 18 | 4 | 2 | 1 | — | 0 |
| tests | 3 | 0 | 19 | 3 | 0 | 0 | 0 | — |

- **engine → shell = 1**：只有组合根（`ww_engine/__init__.py` 的惰性表 + `OK.app`）指向 `ww_app_shell.app`。
- **shell → engine = 18**：外壳用 engine 的 `communicate`/`locator`/`util.*`/`device.capture` —— 正常方向。
- **engine → 项目代码（src/ui/config）= 0**：vendored 引擎没有反向依赖。
- **domain → task_adapter = 0**（P1 清零）、**domain → engine = 0**（P0 清零）、
  **UI → entry = 0**、**entry → task_adapter = 0**：P0 已清。
- task_adapter → engine = 2（`BaseEchoTask`/`EnhanceEchoTask` 用根 API）、ui → engine = 6、entry → engine = 1
  —— 都是“从根拿 `og`/`communicate`/`OK`”，是允许的公共入口。
- tools 的跨层（domain 18 / task 4）是工具的正常行为：`p1_equiv_check.py` 需要读 task 侧和 domain 侧。

## 2. 当前跨层违规

**0 条**。`import_coupling.py` 的违规表为空：
- P1 清掉了最后一条 domain→task_adapter（`echo_inventory → EnhanceEchoTask`）；
- 第三阶段把「engine 子模块 → shell」也纳入违规检测（只放行组合根）。

**模块级循环**：长度 >1 的 SCC **只剩 1 个**，是 `rotypes` 上游自带的 4 模块环
（`rotypes/{delegate,idldsl,inspectable,roapi}`）；**涉及 `src`/`ui`/`shell` 的循环 = 0**。
> 2026-11-13 修了体检工具的假边：`from . import X` 写在 `pkg/__init__.py` 里时 level=1 指**包自身**，
> 旧实现按父包解析，凭空造出 `ww_engine.rotypes → ww_engine`，把根包并进了同一个 SCC（见 §7）。

## 3. UI 对 engine 内部模块的 import

**P0 后为 0**：`debug_tab` / `main_window` / `settings_tab` 已统一从 `ww_engine` 根拿
`og`、`communicate`、`basic_options`；`Alert` 不再被 UI import（调试页改用公共 notification 信号）。

## 4. Qt / qfluentwidgets 渗透（外壳拆分后）

| 层 | 直接 import Qt/qfluentwidgets 的模块 |
|---|---|
| engine (1) | `gui.Communicate`（只 QtCore：`Signal`/`QObject`） |
| shell (5) | `app`、`start_controller`、`overlay_window`、`overlay_widget`、`alert`（QtWidgets/QtGui 都在这里） |
| ui (9) | 全部页面/窗口（正常） |
| entry (1) | `mainui`（正常） |
| tools (1) | `tools.ui_shot`（离屏渲染，正常） |

**task_adapter 与 engine 的非 GUI 核心都已出表**（P1/P2/第三阶段）：
- `util.config` / `util.GlobalConfig` / `task.task` 不再 import `qfluentwidgets`（默认图标已改 `None`）；
- `task.TaskExecutor` / `task.task` 不再 import `PySide6.QtCore`（`translate` → 字面量）；
- `QMessageBox` 只在 `ww_app_shell.alert` 里出现；
- engine 侧唯一 Qt 依赖是 `gui.Communicate`（QtCore 信号中枢），这是刻意的契约面（§0.4）。

## 5. import 耗时（P0 前 → P0 后 → P1 后 → P2 后，本机中位）

| 模块 | P0 前 | P0 后 | P1 后 | P2/第三阶段后 | 说明 |
|---|---:|---:|---:|---:|---|
| `src.echo_stats` | 0.045 | 0.043 | 0.033 | 0.033~0.13 | 纯 domain（低值=机器空闲时） |
| `src.echo_panel` | 0.047 | 0.047 | 0.040 | 0.032~0.14 | 纯 domain |
| `src.char_profiles` | 0.047 | 0.047 | 0.040 | 0.036~0.08 | 纯 domain |
| `ww_engine` | 0.97 | 0.90~0.99 | 0.76~0.90 | **0.21~0.49** | P2 惰性导入；**相对 QtCore 的增量 ≈0.08 s**（见下） |
| `ww_app_shell` | — | — | — | **0.49~0.74** | 外壳：QtWidgets + engine 子模块，只有开窗口时才付 |
| `src.echo_set_templates` | **0.95** | **0.05** | 0.038 | 0.031~0.046 | P0 去掉 `Logger` |
| `src.echo_icon_match` | **1.07** | **0.20** | 0.174 | 0.162~0.26 | P0 去掉 `Logger`；剩 cv2/numpy |
| `src.echo_combos` | **1.05** | **0.073** | 0.062 | 0.056~0.08 | 受益于 `echo_set_templates` |
| `src.echo_inventory` | 0.94 | **0.85** | **0.177** | 0.173~0.34 | P1：不再经 `EnhanceEchoTask` |
| `tools.echo_plan` | 0.99 | **0.85** | **0.208** | 0.177~0.28 | P1：**不再 import Qt**（只剩 cv2 + numpy） |

**口径提醒（2026-11-13 实测踩到）**：这台机器上 `PySide6.QtCore` 单次 import 在 **0.13~0.50 s** 之间波动
（同一命令隔几分钟复测差 3 倍，`import sys` 恒为 0），所以**绝对值不可跨时刻比较**。稳态判据用两条：
① **相对成本** —— `import ww_engine` 减 `import PySide6.QtCore` 的中位差 **≈0.076 s**（7 次交替测量）；
② **成分** —— `-X importtime` 里裸 import 只有 QtCore/psutil/logger/stdlib，**没有** qfluentwidgets/cv2/PIL/rotypes/pynput/shell。
`ww_engine` 的分解（空闲时刻）：QtCore ≈131 ms、`util.process`(psutil) ≈28、`util.logger` ≈24，其余 stdlib。
这组数字说明：**P0 把 domain 拉回几十毫秒，P1 把库存/组合穷举 CLI 拉回 0.2 s 内，
P2 把引擎根包从 0.9 s 拉到 0.2 s 量级，第三阶段把 QtWidgets 彻底移出 engine 的导入链。**

## 6. 剩余可改进项

### 小项
1. **3 个文件的 UTF-8 BOM**：`src/echo_panel.py`、`tests/test_echo_combos.py`、`tests/test_echo_panel.py`
   （能跑，`ast.parse` 会报 `U+FEFF`；纯格式）。

### 已完成（存档）
- **P0**（2026-11-13）：domain 去 `Logger` / 删死文件 / `MODE_*` 下移 / UI 走根 API → §0.1。
- **P1**（2026-11-13）：抽 `src/echo_parse|echo_scoring`、`EnhanceEchoTask` 留薄封装、task adapter 少碰 engine 内部 → §0.2。
- **P2**（2026-11-13）：根包 `__getattr__` 惰性导入 + 去核心 `FluentIcon` + 守卫 `tests/test_engine_lazy.py` → §0.3。
- **第三阶段**（2026-11-13）：应用外壳拆到 `ww_app_shell`、`og` 下移 `locator`、SCC 归零 + 边界守卫 → §0.4。

### 不建议做
- 不要为了“消灭 `og`”重写任务/UI：`og` 是服务定位，不是 import 环；domain 已经不碰它。
- **不要为了把 0.2 s 压到 0.03 s 去惰性化 `communicate`**：它是 `Signal` 中心，每个 UI/引擎消费方都要 QtCore；
  只有“连 Qt 都不装的纯脚本”受益，而那种脚本（如 `tools/echo_plan.py`）现在根本不 import `ww_engine`。
- 不要把 `ww_app_shell` 再拆细（overlay/alert/start_controller 各成包）：它们只在开窗口时被一起拉起，
  拆细只会增加导入路径的维护成本。
- 不要重写 `ww_engine` 的截图/键鼠/overlay：引擎边界已经干净，真正的风险在 OCR/真机，不在语言/分层。
- 不要用 Rust 解决这些耦合：它们都是 Python 包 `__init__` 的导入副作用和少量函数放错层。

## 7. 附：其它发现

- `ui` 层还有 11 条内部依赖（页面之间/widgets），属正常；`tools/tests` 跨层是正常。
- 没有发现 `src` 或 `ui` 被 engine 反向 import；旧“19 模块 SCC”里的根包 hub **大半是体检工具的假边**
  （见下条），修完后真正的环只剩 `rotypes` 上游 4 模块。
- **修了 `import_coupling.py` 的假边（2026-11-13）**：`from . import X` 写在 `pkg/__init__.py` 里时，
  level=1 指的是**包自身**（不是父包）。旧实现按父包解析，把 `ww_engine/rotypes/__init__.py` 的
  `from . import roapi` 记成了 `ww_engine.rotypes → ww_engine`，于是根包/rotypes/外壳被并进同一个 SCC。
  现在 `resolve_relative` 带 `is_package` 参数；矩阵也补回了 `engine` 列（否则看不到 shell→engine 的 18 条边）。
- `ww_engine` 内部 `from ww_engine import og` 的写法已统一改成 `from ww_engine.locator import og`
  （`TaskExecutor`）；这样根包与 `TaskExecutor` 之间也不再成环。

## 8. 验证命令

```powershell
python tools/analysis/import_coupling.py --check
python tools/analysis/import_coupling.py --timing --out logs/analysis/coupling.md
python tools/analysis/p1_equiv_check.py      # 纯函数抽取前后逐例对比（默认对比 3e698cf）
python -m unittest discover -s tests         # 196 项（含惰性导入 + 外壳边界 + 运行模式/网格几何守卫）
python -X importtime -c "import ww_engine"   # 根包导入成本（裸 import 不应出现 qfluentwidgets/cv2/shell）
python tools/echo_plan.py --list             # 纯 CLI 冒烟（P1 后不再需要 Qt）
```
