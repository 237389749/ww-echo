# 底层耦合体检（2026-11-13；P0 已落地）

> 目的：回答“引擎自持之后，`ww_engine` / `src` / `ui` / `config` 的依赖方向还乱不乱”。
> 方法：`tools/analysis/import_coupling.py` 静态扫全部 `.py`（stdlib，不 import 项目），
> 按层统计唯一 import 对、跨层违规、UI 对 engine 内部模块的 import、Qt 直接依赖、模块级循环；
> 另用 `--timing` 实测 import 耗时。
>
> **状态**：2026-11-13 完成体检，并已落地 P0（§0.1）；**P1/P2 尚未实施**（§6）。
> 复现：`python tools/analysis/import_coupling.py --out logs/analysis/coupling.md --timing`

## 0. 一句话结论

**引擎边界干净（0 条 engine→项目代码）；P0 之后 domain→engine、UI→entry、entry→task、UI→engine 内部全部归零。**
当前只剩 **1 条 P1**：

- `src.echo_inventory` → `src.task.EnhanceEchoTask`（借 4 个纯函数），
  把 `tools.echo_plan` 也拖进 PySide6/qfluentwidgets；`echo_plan` import 仍 ≈ **0.85 s**。

另有两条“第二阶段”项：`ww_engine` 根包 ~0.9 s（懒加载可解），task adapter 仍 import `FluentIcon`。
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

## 1. 分层与矩阵（P0 后）

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
| domain | — | **1** | 0 | 0 | 0 | 0 |
| task_adapter | 4 | — | 0 | 0 | 0 | 0 |
| ui | 11 | 1 | — | 0 | 0 | 0 |
| entry | 1 | 0 | 1 | — | 0 | 0 |
| tools | 15 | 3 | 2 | 1 | — | 0 |
| tests | 19 | 3 | 0 | 0 | 0 | — |

- **engine → 项目代码 = 0**：vendored 引擎没有反向依赖 `src/ui/config`。
- **domain → task_adapter = 1**：唯一一条硬分层违规（`echo_inventory` → `EnhanceEchoTask`）。
- **UI → entry = 0**、**entry → task_adapter = 0**：P0 已清。
- tools/tests 的跨层是工具/测试的正常行为，不算违规。

## 2. 当前跨层违规

| 严重度 | importer | imported | 原因 / 影响 |
|---|---|---|---|
| **P1** | `src.echo_inventory` | `src.task.EnhanceEchoTask` | 借 `parse_number` / `_normalize_stat` / `compute_weighted_score` / `dedup_key` 四个纯函数；domain→adapter 反向；`tools.echo_plan` 因此仍 import ≈0.85 s |

**没有涉及 `src`/`ui` 的模块级循环**：长度 >1 的 SCC 只有 2 个，全部在 `ww_engine` 内部
（`ww_engine` 根 ↔ app/DeviceManager/TaskExecutor 的 hub，以及 `rotypes` 上游自带），**涉及 `src`/`ui` 的循环 = 0**。

## 3. UI 对 engine 内部模块的 import

**P0 后为 0**：`debug_tab` / `main_window` / `settings_tab` 已统一从 `ww_engine` 根拿
`og`、`communicate`、`basic_options`；`Alert` 不再被 UI import（调试页改用公共 notification 信号）。

## 4. Qt / qfluentwidgets 渗透（P0 后）

| 层 | 直接 import Qt/qfluentwidgets 的模块 |
|---|---|
| engine (10) | `app`、`gui.Communicate`、`gui.StartController`、`gui.debug.OverlayWidget`、`gui.overlay.OverlayWindow`、`gui.util.Alert`、`task.TaskExecutor`、`task.task`、`util.GlobalConfig`、`util.config` |
| task_adapter (1) | `src.task.EnhanceEchoTask`（只 import `FluentIcon`） |
| ui (9) | 全部页面/窗口（正常） |
| entry (1) | `mainui`（正常） |
| tools (1) | `tools.ui_shot`（离屏渲染，正常） |

**关键点**：engine 的**非 GUI 核心**里仍有 5 个 Qt 依赖：
- `util.config` / `util.GlobalConfig` / `task.task`：`FluentIcon` 默认值/任务图标（纯展示，可改 `None`）；
- `task.TaskExecutor`：只用 `QCoreApplication.translate` 做错误文案（可懒 import）；
- `app`：应用外壳（QApplication），属于“要跑 GUI 才会用”的部分。

只要 `ww_engine/__init__.py` 还在模块顶部 import `app`/`DeviceManager`/`TaskExecutor`/`TaskManager`，
**任何 `ww_engine.*` 子模块 import 都会触发整个根包初始化**；P0 已让 domain 不再借 `Logger`，
但 CLI 仍经 `EnhanceEchoTask` 付这笔钱（§6 P1）。

## 5. import 耗时（P0 前 → P0 后，本机单次中位）

| 模块 | P0 前 | P0 后 | 说明 |
|---|---:|---:|---|
| `src.echo_stats` | 0.045 | 0.043 | 纯 domain |
| `src.echo_panel` | 0.047 | 0.047 | 纯 domain |
| `src.char_profiles` | 0.047 | 0.047 | 纯 domain |
| `ww_engine` | 0.97 | 0.90~0.99 | 根包拉起 Qt/cv2/rotypes（P2 才动） |
| `src.echo_set_templates` | **0.95** | **0.05** | P0 去掉 `Logger`；仍复用 engine 日志 handler |
| `src.echo_icon_match` | **1.07** | **0.20** | P0 去掉 `Logger`；剩 cv2/numpy |
| `src.echo_combos` | **1.05** | **0.073** | 受益于 `echo_set_templates` |
| `src.echo_inventory` | 0.94 | **0.85** | 仍经 `EnhanceEchoTask`（P1） |
| `tools.echo_plan` | 0.99 | **0.85** | 仍经 `echo_inventory`（P1） |

这组数字说明：**P0 把“纯 domain/离线组合”从 1 秒级拉回几十毫秒**；剩下的 0.85 s 全是
`echo_inventory → EnhanceEchoTask → ww_engine` 这一条 P1 链。

## 6. 剩余可改进项

### P1（中等，1~2 天）
1. **把 `EnhanceEchoTask` 里的纯函数抽到 domain**：
   `parse_number`、`_normalize_stat`、`dedup_key` → `src/echo_parse.py`；
   `compute_weighted_score` → `src/echo_scoring.py`（`EnhanceEchoTask` 保留薄封装/静态方法转发，避免破坏调用面）。
   然后 `echo_inventory` 只 import domain；`tools.echo_plan` 不再 import Qt。
2. **task_adapter 少碰 engine 内部**：`ww_engine.feature.Box` → 根 `Box`/`get_bounding_box`；
   `ww_engine.util.file.clear_folder` → 根导出或 stdlib；`EnhanceEchoTask` 的 `FluentIcon` → `None`。
3. **验收**：`python tools/analysis/import_coupling.py --check` 仍 0；domain→task 归零；
   `python tools/echo_plan.py --list` 在无 PySide6 的环境可跑（或至少 import <0.3 s）。

### P2（第二阶段，较大）
4. **`ww_engine/__init__.py` 懒加载**：`OK/EngineApp/DeviceManager/TaskExecutor/TaskManager/BaseTask/...`
   改成 `__getattr__` 按需导入；`og`/`Logger`/`Config` 保持轻量。目标 `import ww_engine` <0.5 s。
5. **去掉 engine 核心的 `FluentIcon`**：`util.config`/`util.GlobalConfig`/`task.task` 的默认 `icon=None`；
   `TaskExecutor` 的 `QCoreApplication.translate` 改懒 import 或普通字符串。
6. **`ww_engine/gui` 的定位**：`Communicate`/`Alert`/`StartController`/overlay 是“应用外壳”而不是
   “Windows 自动化内核”；第二阶段可以拆成独立包（如 `ww_app_shell`），engine 只留 capture/interaction/task。

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
python -m unittest discover -s tests        # 182 项
python tools/echo_plan.py --list            # 纯 CLI 冒烟
```
