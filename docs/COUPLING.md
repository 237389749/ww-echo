# 底层耦合体检（2026-11-13）

> 目的：回答“引擎自持之后，`ww_engine` / `src` / `ui` / `config` 的依赖方向还乱不乱”。
> 方法：`tools/analysis/import_coupling.py` 静态扫全部 `.py`（stdlib，不 import 项目），
> 按层统计唯一 import 对、跨层违规、UI 对 engine 内部模块的 import、Qt 直接依赖、模块级循环；
> 另用 `--timing` 实测 import 耗时。**本文只做体检，未改代码。**
>
> 复现：`python tools/analysis/import_coupling.py --out logs/analysis/coupling.md --timing`

## 0. 一句话结论

**引擎边界是干净的（0 条 engine→项目代码），但“业务层/CLI 仍在为 engine 的 GUI 依赖付费”**：
- `domain` 有 **3 个模块 import `ww_engine`**（两个只借 `Logger`，一个是已死的 `src.globals`），
  任何 `from ww_engine import Logger` 都会拉起 Qt/cv2/rotypes，`src.echo_set_templates` 冷 import ≈ **0.95 s**；
- `domain` 有 **1 个模块反向依赖 task adapter**：`src.echo_inventory` → `EnhanceEchoTask`（借 4 个纯函数），
  把 `tools.echo_plan` 也拖进 PySide6/qfluentwidgets；
- `ui` 有 **5 处直接 import engine 内部模块**（`gui.Communicate` / `gui.util.Alert` / `util.GlobalConfig`），
  不是根 API；
- `entry`/`ui` 之间有一个小环（`ui.settings_tab` → `config` 只借两个常量），`config` 还 import 了一个
  **空实现的 task 函数**（`process_feature`）。

全局单例（`og`、`communicate`、`OK.exit_event`）是**运行时服务定位**，不是 import 环；domain 自己不碰 `og`
（只有死掉的 `src.globals` 碰），所以它**不是**当前主要矛盾，不建议为了“消灭 og”去重写。

## 1. 分层与矩阵

| 层 | 范围 | 允许依赖 |
|---|---|---|
| engine | `ww_engine.*` | 只能依赖第三方 + engine 自己 |
| domain | `src.*`（不含 `src.task`） | 标准库 + domain 自己（**不依赖 engine/task_adapter/ui/entry**） |
| task_adapter | `src.task.*` | domain + engine 根 API |
| ui | `ui.*` | domain + engine 根 API + Qt |
| entry | `config.py` / `mainui.py` | ui + engine + domain |
| tools/tests | `tools.*` / `tests.*` | 任意（工具/测试允许跨层） |

**跨层唯一模块对**（省略层内对角；`engine` 列为空表示 engine 没有出边）：

| importer \ imported | domain | task_adapter | ui | entry | tools | tests |
|---|---:|---:|---:|---:|---:|---:|
| engine | **0** | **0** | **0** | **0** | **0** | **0** |
| domain | — | **1** | 0 | 0 | 0 | 0 |
| task_adapter | 4 | — | 0 | 0 | 0 | 0 |
| ui | 10 | 1 | — | **1** | 0 | 0 |
| entry | 0 | **1** | 1 | — | 0 | 0 |
| tools | 15 | 3 | 2 | 1 | — | 0 |
| tests | 19 | 3 | 0 | 0 | 0 | — |

- **engine → 项目代码 = 0**：vendored 引擎没有反向依赖 `src/ui/config`，这条最关键的边界成立。
- **domain → task_adapter = 1**：唯一一条硬分层违规（`echo_inventory` → `EnhanceEchoTask`）。
- **ui → entry = 1**：`settings_tab` 只为 `MODE_LOCAL/MODE_CLOUD` 两个字符串。
- **entry → task_adapter = 1**：`config` → `process_feature`，而后者是 8 行空函数。
- tools/tests 的跨层是工具/测试的正常行为，不算违规。

## 2. 跨层违规明细（按严重度）

| 严重度 | importer | imported | 原因 / 影响 |
|---|---|---|---|
| **P1** | `src.echo_icon_match` | `ww_engine` | 只借 `Logger`；拉入 Qt/cv2/rotypes |
| **P1** | `src.echo_set_templates` | `ww_engine` | 只借 `Logger`；冷 import ≈0.95 s |
| **P1** | `src.globals` | `ww_engine` | 死文件；新 `OK` 不加载 `my_app` |
| **P1** | `src.echo_inventory` | `src.task.EnhanceEchoTask` | 借 `parse_number` / `_normalize_stat` / `compute_weighted_score` / `dedup_key` 四个纯函数；domain→adapter 反向 |
| **P2** | `config` | `src.task.process_feature` | 只是给 `feature_processor` 传一个空实现 |
| **P2** | `ui.settings_tab` | `config` | 只借 `MODE_LOCAL/MODE_CLOUD` 两个常量 |

**没有涉及 `src`/`ui` 的模块级循环**：长度 >1 的 SCC 只有 2 个，全部在 `ww_engine` 内部（`ww_engine` 根 ↔ app/DeviceManager/
TaskExecutor 的 hub，以及 `rotypes` 上游自带），**涉及 `src`/`ui` 的循环 = 0**。
也就是说：现在的问题是“层方向不对/边界漏”，不是“互相 import 死锁”。

## 3. UI 对 engine 内部模块的 import

| UI 模块 | engine 内部路径 | 更合适的入口 |
|---|---|---|
| `ui.debug_tab` | `ww_engine.gui.Communicate` | `from ww_engine import communicate`（根已导出） |
| `ui.debug_tab` | `ww_engine.gui.util.Alert` | UI 自己用 `InfoBar.error`，或 engine 根导出一个公共 alert |
| `ui.main_window` | `ww_engine.gui.Communicate` | 同 `communicate` |
| `ui.settings_tab` | `ww_engine.gui.Communicate` | 同 `communicate` |
| `ui.settings_tab` | `ww_engine.util.GlobalConfig` | `from ww_engine import basic_options`（根已导出） |

`ww_engine.__all__` 已经有 `communicate` / `basic_options`；UI 现在绕开根 API 直接拿子模块，
等于把 engine 内部目录结构变成对外契约。`Alert` 更适合由 UI 层自己实现（它只是 QMessageBox），
或者提升成 engine 的公共 API 并在 `__all__` 声明。

## 4. Qt / qfluentwidgets 渗透

| 层 | 直接 import Qt/qfluentwidgets 的模块 |
|---|---|
| engine (10) | `app`、`gui.Communicate`、`gui.StartController`、`gui.debug.OverlayWidget`、`gui.overlay.OverlayWindow`、`gui.util.Alert`、`task.TaskExecutor`、`task.task`、`util.GlobalConfig`、`util.config` |
| task_adapter (1) | `src.task.EnhanceEchoTask`（只 import `FluentIcon`） |
| domain (1) | `src.globals`（死文件） |
| ui (9) | 全部页面/窗口（正常） |
| entry (1) | `mainui`（正常） |
| tools (1) | `tools.ui_shot`（离屏渲染，正常） |

**关键点**：engine 的 **非 GUI 核心**里仍有 5 个 Qt 依赖：
- `util.config` / `util.GlobalConfig` / `task.task`：`FluentIcon` 默认值/任务图标（纯展示，可改 `None`）；
- `task.TaskExecutor`：只用 `QCoreApplication.translate` 做错误文案（可懒 import）；
- `app`：应用外壳（QApplication），属于“要跑 GUI 才会用”的部分。

只要 `ww_engine/__init__.py` 还在模块顶部 import `app`/`DeviceManager`/`TaskExecutor`/`TaskManager`，
**任何 `ww_engine.*` 子模块 import 都会触发整个根包初始化**；`domain` 借 `Logger` 因此付了整包的钱。

## 5. import 耗时（本机单次，仅供参考）

| 模块 | 中位 (s) | 说明 |
|---|---:|---|
| `src.echo_stats` | **0.045** | 纯 domain，无 engine |
| `src.echo_panel` | **0.047** | 纯 domain |
| `src.char_profiles` | **0.047** | 纯 domain |
| `ww_engine` | **0.97** | 根包拉起 Qt/cv2/rotypes |
| `src.echo_set_templates` | **0.95** | 几乎全是 `ww_engine` 的钱 |
| `src.echo_icon_match` | **1.07** | `ww_engine` + cv2/numpy |
| `src.echo_inventory` | **0.94** | `EnhanceEchoTask` → `ww_engine` |
| `src.echo_combos` | **1.05** | → `echo_set_templates` |
| `tools.echo_plan` | **0.99** | CLI 也被拖进 Qt 栈 |

这组数字说明：**“纯计算”本身是几十毫秒级，1 秒级开销几乎全是跨层 import 的 GUI 栈**。
`echo_plan --list` 是一个纯离线 CLI，不需要 PySide6/qfluentwidgets，却要为 engine 根包付 1 秒。

## 6. 可改进项（按优先级，尚未实施）

### P0（低风险，半天内）
1. **domain 不再借 engine 的 `Logger`**：`echo_icon_match` / `echo_set_templates` 改 `logging.getLogger(__name__)`；
   `mainui` 已把 `src` logger 接到 `log_bridge`，日志仍会进 UI。目标：`echo_set_templates` 回到 ~0.05 s；
   `echo_icon_match` 仍要 cv2/numpy（~0.2 s），但不再拉 Qt。
2. **删除 `src/globals.py` + `config['my_app']`**：新 `OK` 不加载 `my_app`，文件只有占位。
3. **删除 `src/task/process_feature.py`** 与 `feature_processor` 配置项（空实现，`FeatureSet` 默认 `None` 行为一致）。
4. **`MODE_LOCAL/MODE_CLOUD` 移到中立模块**（如 `src/run_modes.py`，由 `config` 再导出）或让 UI 从入口注入，
   去掉 `ui.settings_tab → config`。
5. **UI 改走 engine 根 API**：`communicate`、`basic_options`；`Alert` 由 UI 自己用 `InfoBar.error` 或提升为公共 API。

### P1（中等，1~2 天）
6. **把 `EnhanceEchoTask` 里的纯函数抽到 domain**：
   `parse_number`、`_normalize_stat`、`dedup_key` → `src/echo_parse.py`；
   `compute_weighted_score` → `src/echo_scoring.py`（`EnhanceEchoTask` 保留薄封装/静态方法转发，避免破坏调用面）。
   然后 `echo_inventory` 只 import domain；`tools.echo_plan` 不再 import Qt。
7. **task_adapter 少碰 engine 内部**：`ww_engine.feature.Box` → 根 `Box`/`get_bounding_box`；
   `ww_engine.util.file.clear_folder` → 根导出或 stdlib；`EnhanceEchoTask` 的 `FluentIcon` → `None`。
8. **验收**：`python tools/analysis/import_coupling.py --check` 仍 0；domain→engine/task 归零；
   `python tools/echo_plan.py --list` 在无 PySide6 的环境可跑（或至少 import <0.3 s）。

### P2（第二阶段，较大）
9. **`ww_engine/__init__.py` 懒加载**：`OK/EngineApp/DeviceManager/TaskExecutor/TaskManager/BaseTask/...`
   改成 `__getattr__` 按需导入；`og`/`Logger`/`Config` 保持轻量。目标 `import ww_engine` <0.5 s，
   且只借 `Logger` 的消费者不拉 Qt。
10. **去掉 engine 核心的 `FluentIcon`**：`util.config`/`util.GlobalConfig`/`task.task` 的默认 `icon=None`；
    `TaskExecutor` 的 `QCoreApplication.translate` 改懒 import 或普通字符串。
11. **`ww_engine/gui` 的定位**：`Communicate`/`Alert`/`StartController`/overlay 是“应用外壳”而不是
    “Windows 自动化内核”；第二阶段可以拆成独立包（如 `ww_app_shell`），engine 只留 capture/interaction/task。

### 不建议做
- 不要为了“消灭 `og`”重写任务/UI：`og` 是服务定位，不是 import 环；domain 已经不碰它。
- 不要重写 `ww_engine` 的截图/键鼠/overlay：引擎边界已经干净，真正的风险在 OCR/真机，不在语言/分层。
- 不要用 Rust 解决这些耦合：它们都是 Python 包 `__init__` 的导入副作用和少量函数放错层。

## 7. 附：本次体检的其它发现

- **3 个文件带 UTF-8 BOM**：`src/echo_panel.py`、`tests/test_echo_combos.py`、`tests/test_echo_panel.py`。
  Python 能跑，但 `ast.parse`/部分工具会报 `U+FEFF`；建议统一去掉（纯格式，不影响逻辑）。
- `ui` 层还有 10 条内部依赖（页面之间/widgets），属正常；`tools/tests` 跨层是正常。
- 没有发现 `src` 或 `ui` 被 engine 反向 import；`ww_engine` 的 19 模块 SCC 是根包 hub，不是业务环。

## 8. 验证命令

```powershell
python tools/analysis/import_coupling.py --check
python tools/analysis/import_coupling.py --timing --out logs/analysis/coupling.md
python -m unittest discover -s tests        # 182 项
python tools/echo_plan.py --list            # 纯 CLI 冒烟
```
