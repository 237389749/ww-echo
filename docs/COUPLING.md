# 底层耦合体检（2026-11-13；P0 + P1 已落地）

> 目的：回答“引擎自持之后，`ww_engine` / `src` / `ui` / `config` 的依赖方向还乱不乱”。
> 方法：`tools/analysis/import_coupling.py` 静态扫全部 `.py`（stdlib，不 import 项目），
> 按层统计唯一 import 对、跨层违规、UI 对 engine 内部模块的 import、Qt 直接依赖、模块级循环；
> 另用 `--timing` 实测 import 耗时。
>
> **状态**：2026-11-13 完成体检，并已落地 P0（§0.1）与 P1（§0.2）；**只剩 P2**（§6）。
> 复现：`python tools/analysis/import_coupling.py --out logs/analysis/coupling.md --timing`

## 0. 一句话结论

**引擎边界干净（0 条 engine→项目代码）；P0 + P1 之后跨层反向依赖全部归零** ——
domain→engine、**domain→task_adapter**、UI→entry、entry→task、UI→engine 内部都是 **0**，
`import_coupling.py` 的违规表为空。

P1 之后 `src.echo_inventory`（以及 CLI `tools.echo_plan`）不再经过 task adapter →
**不 import PySide6 / qfluentwidgets / ww_engine**，import 从 ≈0.85 s 降到 **0.18 / 0.21 s**。
剩下的是两个“成本类”问题（P2）：`ww_engine` 根包 ≈0.8~0.9 s（`__init__` 顶部拉起 app/DeviceManager/TaskExecutor），
以及 engine 非 GUI 核心里仍有的 Qt 依赖。
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

## 1. 分层与矩阵（P1 后）

| 层 | 范围 | 允许依赖 |
|---|---|---|
| engine | `ww_engine.*` | 只能依赖第三方 + engine 自己 |
| domain | `src.*`（不含 `src.task`） | 标准库 + domain 自己（**不依赖 engine/task_adapter/ui/entry**） |
| task_adapter | `src.task.*` | domain + engine 根 API |
| ui | `ui.*` | domain + engine 根 API + Qt |
| entry | `config.py` / `mainui.py` | ui + engine + domain |
| tools/tests | `tools.*` / `tests.*` | 任意（工具/测试允许跨层） |

**跨层唯一模块对**（省略层内对角；`engine` 行全 0）：

| importer \ imported | domain | task_adapter | ui | entry | tools | tests |
|---|---:|---:|---:|---:|---:|---:|
| engine | **0** | **0** | **0** | **0** | **0** | **0** |
| domain | — | **0** | 0 | 0 | 0 | 0 |
| task_adapter | 6 | — | 0 | 0 | 0 | 0 |
| ui | 11 | 1 | — | 0 | 0 | 0 |
| entry | 1 | 0 | 1 | — | 0 | 0 |
| tools | 18 | 4 | 2 | 1 | — | 0 |
| tests | 19 | 3 | 0 | 0 | 0 | — |

- **engine → 项目代码 = 0**：vendored 引擎没有反向依赖 `src/ui/config`。
- **domain → task_adapter = 0**（P1 清零；P0 后是 1）。
- **domain → engine = 0**（P0 清零）。
- **UI → entry = 0**、**entry → task_adapter = 0**：P0 已清。
- task_adapter → domain 从 4 涨到 6（新增 `src.echo_parse` / `src.echo_scoring`）——**这是正确方向**（adapter 依赖 domain）。
- tools 的跨层（domain 18 / task 4）是工具的正常行为：`p1_equiv_check.py` 需要读 task 侧和 domain 侧。

## 2. 当前跨层违规

**0 条**。`import_coupling.py` 的违规表为空（P1 清掉了最后一条 `src.echo_inventory → src.task.EnhanceEchoTask`）。

**没有涉及 `src`/`ui` 的模块级循环**：长度 >1 的 SCC 只有 2 个，全部在 `ww_engine` 内部
（`ww_engine` 根 ↔ app/DeviceManager/TaskExecutor 的 hub，以及 `rotypes` 上游自带），**涉及 `src`/`ui` 的循环 = 0**。

## 3. UI 对 engine 内部模块的 import

**P0 后为 0**：`debug_tab` / `main_window` / `settings_tab` 已统一从 `ww_engine` 根拿
`og`、`communicate`、`basic_options`；`Alert` 不再被 UI import（调试页改用公共 notification 信号）。

## 4. Qt / qfluentwidgets 渗透（P1 后）

| 层 | 直接 import Qt/qfluentwidgets 的模块 |
|---|---|
| engine (10) | `app`、`gui.Communicate`、`gui.StartController`、`gui.debug.OverlayWidget`、`gui.overlay.OverlayWindow`、`gui.util.Alert`、`task.TaskExecutor`、`task.task`、`util.GlobalConfig`、`util.config` |
| ui (9) | 全部页面/窗口（正常） |
| entry (1) | `mainui`（正常） |
| tools (1) | `tools.ui_shot`（离屏渲染，正常） |

**task_adapter 已不在表里**（P1：`EnhanceEchoTask` 的 `FluentIcon.ADD` → `None`）。

**关键点**：engine 的**非 GUI 核心**里仍有 5 个 Qt 依赖：
- `util.config` / `util.GlobalConfig` / `task.task`：`FluentIcon` 默认值/任务图标（纯展示，可改 `None`）；
- `task.TaskExecutor`：只用 `QCoreApplication.translate` 做错误文案（可懒 import）；
- `app`：应用外壳（QApplication），属于“要跑 GUI 才会用”的部分。

只要 `ww_engine/__init__.py` 还在模块顶部 import `app`/`DeviceManager`/`TaskExecutor`/`TaskManager`，
**任何 `ww_engine.*` 子模块 import 都会触发整个根包初始化** —— 这是 P2 的懒加载要解决的（domain 已不碰 engine，
所以现在这项成本只落在 task/UI 侧）。

## 5. import 耗时（P0 前 → P0 后 → P1 后，本机中位）

| 模块 | P0 前 | P0 后 | P1 后 | 说明 |
|---|---:|---:|---:|---|
| `src.echo_stats` | 0.045 | 0.043 | 0.033 | 纯 domain |
| `src.echo_panel` | 0.047 | 0.047 | 0.040 | 纯 domain |
| `src.char_profiles` | 0.047 | 0.047 | 0.040 | 纯 domain |
| `ww_engine` | 0.97 | 0.90~0.99 | 0.76~0.90 | 根包拉起 Qt/cv2/rotypes（P2 才动） |
| `src.echo_set_templates` | **0.95** | **0.05** | 0.038 | P0 去掉 `Logger` |
| `src.echo_icon_match` | **1.07** | **0.20** | 0.174 | P0 去掉 `Logger`；剩 cv2/numpy |
| `src.echo_combos` | **1.05** | **0.073** | 0.062 | 受益于 `echo_set_templates` |
| `src.echo_inventory` | 0.94 | **0.85** | **0.177** | P1：不再经 `EnhanceEchoTask` |
| `tools.echo_plan` | 0.99 | **0.85** | **0.208** | P1：**不再 import Qt**（只剩 cv2 + numpy） |

**P1 后口径**：单进程 import 5 次取中位（2026-11-13 22:38，Python 3.13.16 venv）；
`echo_plan` 的 0.208 s 基本就是 `cv2` 的成本（`echo_icon_match` 0.174 s）。
这组数字说明：**P0 把“纯 domain/离线组合”从 1 秒级拉回几十毫秒，P1 把“库存/组合穷举 CLI”也拉回 0.2 s 内**。

## 6. 剩余可改进项

### P2（第二阶段，较大）
1. **`ww_engine/__init__.py` 懒加载**：`OK/EngineApp/DeviceManager/TaskExecutor/TaskManager/BaseTask/...`
   改成 `__getattr__` 按需导入；`og`/`Logger`/`Config` 保持轻量。目标 `import ww_engine` <0.5 s。
2. **去掉 engine 核心的 `FluentIcon`**：`util.config`/`util.GlobalConfig`/`task.task` 的默认 `icon=None`；
   `TaskExecutor` 的 `QCoreApplication.translate` 改懒 import 或普通字符串。
3. **`ww_engine/gui` 的定位**：`Communicate`/`Alert`/`StartController`/overlay 是“应用外壳”而不是
   “Windows 自动化内核”；第二阶段可以拆成独立包（如 `ww_app_shell`），engine 只留 capture/interaction/task。

### 已完成（存档）
- **P0**（2026-11-13）：domain 去 `Logger` / 删死文件 / `MODE_*` 下移 / UI 走根 API → §0.1。
- **P1**（2026-11-13）：抽 `src/echo_parse|echo_scoring`、`EnhanceEchoTask` 留薄封装、task adapter 少碰 engine 内部
  → §0.2。

### 不建议做
- 不要为了“消灭 `og`”重写任务/UI：`og` 是服务定位，不是 import 环；domain 已经不碰它。
- 不要重写 `ww_engine` 的截图/键鼠/overlay：引擎边界已经干净，真正的风险在 OCR/真机，不在语言/分层。
- 不要用 Rust 解决这些耦合：它们都是 Python 包 `__init__` 的导入副作用和少量函数放错层。

## 7. 附：其它发现

- **3 个文件带 UTF-8 BOM**：`src/echo_panel.py`、`tests/test_echo_combos.py`、`tests/test_echo_panel.py`。
  Python 能跑，但 `ast.parse`/部分工具会报 `U+FEFF`；建议统一去掉（纯格式，不影响逻辑）。
- `ui` 层还有 11 条内部依赖（页面之间/widgets），属正常；`tools/tests` 跨层是正常。
- 没有发现 `src` 或 `ui` 被 engine 反向 import；`ww_engine` 的 19 模块 SCC 是根包 hub，不是业务环。

## 8. 验证命令

```powershell
python tools/analysis/import_coupling.py --check
python tools/analysis/import_coupling.py --timing --out logs/analysis/coupling.md
python tools/analysis/p1_equiv_check.py      # 纯函数抽取前后逐例对比（默认对比 3e698cf）
python -m unittest discover -s tests         # 182 项
python tools/echo_plan.py --list             # 纯 CLI 冒烟（P1 后不再需要 Qt）
```
