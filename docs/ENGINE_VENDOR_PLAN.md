# 引擎自持规划：从 ok-script 精简 vendor（阶段三十一）

> 状态：**P1/P2 已实施（2026-11-13，分支 `engine/vendor`）**；P4 真机验收待做。
> **接管审核（同日）**：修复 OCR 主链路回归（`TaskExecutor` 属性裁剪后仍被 `fix_texts` 引用），
> 补 `tests/test_engine_task.py` 守卫；P3 基线 → 182 项单测 / 7 页。
> 实际落地：`ww_engine/` **75 个 `.py` / 10,226 物理行（8,449 非空行）**；
> 对照规划为保留 61 文件/12,111 行（物理行口径）、删除 150 文件/35,267 行。
> 早期文档写的 8,540 是**非空行**计数，与 12,111/35,267 口径不同，已改正。
> 目标提交基线：`54c9ee6`（阶段三十）。关联：`CLAUDE.md`（项目手册）、`handoff.md`（交接）、`docs/BASELINE.md`（验收基线）。
> 本文回答两个问题：① 哪些 ok-script 代码要保留/删掉/重写；② 迁移后如何证明行为没变。

---

## 0. 一句话边界

**只保留“Windows 窗口截图 + 键鼠注入 + OCR + 模板匹配 + 任务运行时”这一层内核，约 61 个文件 / 12.1k 行；
删除 ok-ww 的 GUI、ADB/模拟器/浏览器/Genshin、更新/打包/分析、i18n 等 150 个文件 / 35.3k 行；
把 `OK`/`App`/`TaskManager` 这三个“应用外壳”重写成 ~500 行的薄运行时。**

不保留：ok-script 的原生 GUI、`ok_tasks` 自定义任务、脚本打包、定时任务、自动更新、Analytics、ADB、模拟器、浏览器 capture、Genshin 交互、i18n、剪贴板、模板标注工具。
保留：本地/云游戏两种窗口模式、WGC/BitBlt、PostMessage/Pynput、onnxocr/OpenVINO、模板匹配、任务启停/暂停、覆盖层（第一阶段）。

---

## 1. 现状统计（ok-script 1.0.160）

| 项 | 数值 |
|---|---:|
| 全部 Python 文件 | **211** |
| 全部 Python 行数 | **47,378** |
| 建议保留（含裁剪/重写） | **61 文件 / 12,111 行** |
| 建议删除 | **150 文件 / 35,267 行**（74.4%） |
| `ok/gui/resources.py` 单文件 | 13,965 行（Qt 资源，删除） |
| `ok/gui/` 整组 | 94 文件 / 25,489 行（只留 6 文件 / 1,333 行） |
| `ok/capture/adb/` | 11 文件 / 3,252 行（删除） |
| `ok/alas/`（模拟器） | 5 文件 / 1,043 行（删除） |
| `ok/device/` 中 ADB/浏览器/Nemu/桌面复制 | 16 文件 / 1,445 行（删除） |
| `ok/util/` 中 Analytics/blur/GPU 驱动/调度/打印 | 8 文件 / 2,935 行（删除） |
| `ok/third_party/paperclip.py` | 655 行（删除，`BaseTask.clipboard()` 一并删） |
| 当前 `import ok` 冷启动 | 约 **0.96 s**（会拉起 requests/MainWindow/DiagnosisTask） |
| 当前 site-packages 补丁 | 4 个文件 / 8 处标记，重装即丢 |

> 统计口径：`ok-script==1.0.160` 安装包内 `.py` 文件（不含 `__pycache__`），行数按物理行计。

### 保留组（61 文件 / 12,111 行）的分组

| 组 | 文件数 | 行数 | 内容 |
|---|---:|---:|---|
| `feature/` | 3 | 1,342 | `Box` / `Feature` / `FeatureSet`（模板匹配核心） |
| `task/` | 3 | 2,013 | `task.py`（BaseTask/FindFeature/OCR 封装）、`TaskExecutor`、`exceptions` |
| `device/` | 14 | 3,035 | `DeviceManager`、capture/interaction 注册表、BitBlt/WGC/Hwnd、PostMessage/Pynput/keys |
| `util/` | 10 | 2,161 | `config`/`GlobalConfig`/`logger`/`file`/`window`/`process`/`handler`/`collection`/`clazz`/`color` |
| `capture/windows/` | 1 | 74 | `d3d11.py`（WGC 用） |
| `rotypes/` | 23 | 1,353 | WGC 的 WinRT 绑定（保留整组，避免拆错） |
| `gui/` | 6 | 1,333 | `Communicate`、`Alert`、`StartController`、`TaskManger`、`OverlayWindow`、`OverlayWidget` |
| `__init__.py` | 1 | 800 | **重写**为最小 `OK/og/App`（目标 ~300 行） |

### 删除组（150 文件 / 35,267 行）的边界

| 组 | 文件数 | 行数 | 删除理由 |
|---|---:|---:|---|
| `gui/` 其余 | 94 | 25,489 | 原生 MainWindow/各 Tab/Widget/i18n/`resources.py`；我们已有自建 PySide6 UI |
| `capture/adb/` | 11 | 3,252 | ADB 截图/触控，本项目不用 |
| `alas/` | 5 | 1,043 | 模拟器管理，本项目不用 |
| `device/` 其余 | 16 | 1,445 | Browser/DesktopDuplication/Image/Nemu capture + ADB/Browser/Genshin/PyDirect/Foreground/Swipe 交互 |
| `util/` 其余 | 8 | 2,935 | `Analytics`、`blur`、`gpu_driver_settings`、`i18n`、`partial_sync_repo`、`print_hwnd`、`windows_schedule` |
| `third_party/` | 2 | 655 | `paperclip`（剪贴板）；`BaseTask.clipboard()` 一并删 |
| `update/` | 3 | 146 | 自更新/依赖内联，不保留 |
| `test/` | 4 | 137 | ok-script 自带测试，不保留 |
| `ocr/` | 2 | 13 | 模型下载脚本；OCR 走 `onnxocr` + OpenVINO |
| `task/DiagnosisTask.py` | 1 | 55 | 诊断任务，不保留 |
| `cli.py` / `__main__.py` | 2 | 97 | 无头 CLI 入口，不保留 |

---

## 2. 保留 / 裁剪 / 重写 的具体清单

### 2.1 直接保留（52 文件，只做 import 命名空间替换）

- `feature/Box.py`、`feature/Feature.py`、`feature/FeatureSet.py`
- `rotypes/**`（整组 23 文件；WGC 的 WinRT 绑定，拆开容易漏）
- `capture/windows/d3d11.py`
- `device/capture_methods/{base,bitblt,bitblt_utils,hwnd_window,windows_graphics,types,update}.py`
- `device/interaction_methods/{base,keys,post_message,pynput}.py`
- `util/{config,GlobalConfig,logger,file,window,process,handler,collection,clazz,color}.py`
- `gui/Communicate.py`、`gui/util/Alert.py`
- `gui/overlay/OverlayWindow.py`、`gui/debug/OverlayWidget.py`（第一阶段保留；第二阶段可删）
- `task/exceptions.py`

### 2.2 保留 + 裁剪（7 文件）

| 文件 | 原始行 | 裁剪内容 | 目标行 |
|---|---:|---|---:|
| `task/task.py` | 1,370 | 删 `clipboard()`/`paperclip`、`opencc`/i18n 分支、未用的快捷键/录制/颜色辅助；保留 `ocr/click/send_key/scroll/find_*/wait_*/box/frame/sleep/pause/info_*` | 1,163（实际） |
| `task/TaskExecutor.py` | 619 | 删 i18n/`download_models`/blur overlay/GPU 检测；OCR 只留 `onnxocr` 分支；保留帧/暂停/任务循环/`wait_condition` | ~450 |
| `device/DeviceManager.py` | 1,007 | 删 ADB/模拟器/Browser/Nemu 分支与方法；只保留 Windows `HwndWindow` + capture/interaction 选择 + 分辨率/窗口刷新 | ~450 |
| `device/capture.py` | 9 | 注册表只留 BitBlt/WGC/Hwnd | ~9 |
| `device/interaction.py` | 2 | 只留 PostMessage/Pynput | ~2 |
| `gui/StartController.py` | 346 | 删自动启动 exe/GPU 检查/ADB/Browser 分支；保留“点开始→刷新→等窗口就绪→拉前台→启用任务→executor.start” | ~180 |
| `gui/tasks/TaskManger.py` | 427 | 删自定义任务/导入任务/定时任务/文件监视；只留 onetime/trigger 任务实例化 + `after_init/post_init` | ~120 |

### 2.3 重写（2 文件）

| 文件 | 原始行 | 目标 |
|---|---:|---|
| `__init__.py` | 800 | 拆成 `ww_engine/__init__.py`（导出 + `og` 命名空间）+ `ww_engine/app.py`（最小 App：QApplication、`ok_config`、`start_controller`、overlay、quit）+ 最小 `OK.do_init`；目标 ~300 行 |
| `gui/debug/Screenshot.py` | 229 | **删除**，改为 `ww_engine/screenshot.py` 里一个只含 `screenshot_folder` 的轻量对象；`debug_tab` 改读 `og.config['screenshots_folder']` |

### 2.4 明确删除的“非核心能力”

- 原生 GUI：`MainWindow`、About/Start/Settings/Debug/Tasks 各 Tab、Widget、i18n、`resources.py`、qss。
- ADB / 模拟器 / 浏览器 capture / Nemu / DesktopDuplication / ImageCapture。
- Genshin / PyDirect / ForegroundPostMessage / Browser / ADB / Swipe 交互。
- 自定义任务加载（`ok_tasks`/`ok_import`）、脚本打包、定时任务、更新器、Analytics。
- `DiagnosisTask`、`MouseResetTask`（上一阶段已删）、`WWScene`（已删）。
- 剪贴板、模板标注/保存 GUI、录制脚本、GPU 驱动检查、自动启动游戏。
- i18n（本项目中文单语；`supported_languages` 用常量 `zh_CN` 过滤即可）。

---

## 3. 目标目录结构

```
ww_engine/                      # 顶层包；业务代码只 import 这里
├── __init__.py                 # OK / og / BaseTask / FindFeature / Logger / Box / Config...
├── app.py                      # 最小 App（QApplication / ok_config / start_controller / overlay / quit）
├── screenshot.py               # 只含 screenshot_folder 的轻量对象
├── task/
│   ├── task.py                 # BaseTask / FindFeature / OCR 封装（裁剪）
│   ├── TaskExecutor.py         # 帧/暂停/任务循环/OCR（裁剪）
│   └── exceptions.py
├── device/
│   ├── DeviceManager.py        # Windows-only（裁剪）
│   ├── capture.py              # BitBlt/WGC/Hwnd 注册
│   ├── interaction.py          # PostMessage/Pynput 注册
│   ├── capture_methods/...     # base/bitblt/bitblt_utils/hwnd_window/windows_graphics/types/update
│   └── interaction_methods/... # base/keys/post_message/pynput
├── feature/                    # Box / Feature / FeatureSet
├── capture/windows/d3d11.py
├── rotypes/                    # 整组保留（WGC）
├── util/                       # config/GlobalConfig/logger/file/window/process/handler/collection/clazz/color
└── gui/                        # 第一阶段保留最小 GUI 适配
    ├── Communicate.py          # Qt 信号（日志/设备/任务/通知/退出）
    ├── util/Alert.py
    ├── StartController.py      # 裁剪
    ├── tasks/TaskManger.py     # 裁剪
    ├── overlay/OverlayWindow.py
    └── debug/OverlayWidget.py
```

> 第一阶段**保持原目录层级**（`gui/StartController.py` 等）以降低迁移风险；第二阶段再做 `runtime/` 之类的重命名。
> 不建议把 vendored 代码放进 `src/`：`src/` 是领域层，`ww_engine/` 是运行时层，边界更清楚。

---

## 4. API 边界（必须保持的调用面）

### 4.1 入口

```python
from ww_engine import OK, og
ok_engine = OK(config)          # 初始化 device_manager / feature_set / executor / task_manager
og.app.start_controller.start() # 启动引擎（无任务）
```

### 4.2 UI 依赖（改造为 `og.*` 不变）

| 调用 | 用途 |
|---|---|
| `og.config.get('version')` | 关于/设备设置页版本 |
| `og.device_manager.refresh()` / `get_devices()` | 设备列表 |
| `og.device_manager.set_preferred_device(index=...)` | 选窗 |
| `og.device_manager.config` / `windows_capture_config` | 截图/交互下拉 |
| `og.device_manager.set_capture()` / `set_interaction()` | 切换后端 |
| `og.device_manager.capture_method` / `hwnd_window` | 截图预览 / 拉前台 |
| `og.executor.global_config` | 静音等基础选项 |
| `og.executor.get_task_by_class()` / `get_all_tasks()` / `paused` | 任务查询 / OCR 测试 |
| `og.app.ok_config` / `get_overlay_view()` | 覆盖层开关 |
| `og.app.start_controller.start(task)` | 开始任务 |
| `communicate.adb_devices` / `quit` / `log` / `notification` | 设备刷新 / 退出 / 日志 / 提示 |
| `og.ok.screenshot.screenshot_folder` | **改为** `og.config['screenshots_folder']`（删除 Screenshot 类） |

### 4.3 任务依赖（`BaseTask`/`FindFeature` 保留的 API）

`ocr / click / send_key / scroll_relative / find_one / find_boxes / find_best_match_in_box / get_box_by_name /
wait_ocr / wait_click_ocr / wait_until / box_of_screen / frame / sleep / pause / info_set / info_get / info_incr /
log_info / log_debug / log_warning / log_error / find_confirm / find_echo_enhance / trash_and_esc / lock_and_esc`

> 这些方法由 `task/task.py` 提供，裁剪时**只删内部未用分支**，不改签名/语义；否则 `EnhanceEchoTask` 需要跟着改。

### 4.4 `og` 命名空间

保留：`og.config`、`og.ok`、`og.app`、`og.executor`、`og.device_manager`、`og.global_config`、`og.handler`、`og.exit_event`。
不保留：`og.main_window`、`og.task_manager`（可留空引用以兼容旧代码）、`og.my_app` 的 GUI 回调。

---

## 5. 外部依赖边界

| 依赖 | 处理 | 说明 |
|---|---|---|
| `pywin32` | **保留** | win32gui/api/con/process/ui；截图/窗口/输入必需 |
| `PySide6` | **保留** | `Communicate`/overlay/UI 信号 |
| `PySide6-Fluent-Widgets` | **保留（UI 层）** | 自建 UI；引擎内只用到 `FluentIcon` 默认值，第一阶段可保留，第二阶段替换为 `icon=None` 解耦 |
| `numpy` / `opencv-python` | **保留** | 帧/模板/颜色/OCR 前处理 |
| `onnxocr-ppocrv5` / `openvino` | **保留** | OCR 唯一后端（`ocr.lib='onnxocr'`） |
| `pynput` | **保留** | 云游戏前台键鼠 |
| `psutil` | **保留** | 窗口/进程/睡眠 |
| `pycaw` | **可选保留** | 仅“后台静音”用；若第二阶段删静音开关，可去掉 |
| `Pillow` / `shapely` / `pyclipper` | **保留（传递）** | onnxocr 依赖；FeatureSet 用 Pillow 判压缩 |
| `ok-script` | **删除** | 由 `ww_engine` 取代 |
| `pyappify` | **删除** | 版本/启动器；改用 `config['version']` |
| `requests` | **删除** | 仅 Analytics/下载/更新用 |
| `pydirectinput` / `mouse` | **删除** | 仅 PyDirect/Genshin 交互用 |
| `adbutils` | **删除** | 仅 ADB 分支；本机原本也没装 |
| `paddleocr` / `rapidocr` / `dgocr` / `opencc` | **删除** | 仅其他 OCR/简繁转换分支；我们只用 onnxocr |
| `win32com` | **删除** | 仅快捷方式创建；裁剪 `process.create_shortcut` |
| `typing-extensions` | **删除（若无引用）** | 由 `typing` 标准库覆盖 |

> 目标 `requirements.txt`：`PySide6-Fluent-Widgets`、`pywin32`、`numpy`、`opencv-python`、`onnxocr-ppocrv5`、`openvino`、`pynput`、`psutil`（+ 可选 `pycaw`）。
> 不再需要 `ok-script==1.0.160`，也不再需要 `tools/patches/apply_patches.py`。

---

## 6. 迁移步骤与验收

### P0：冻结与快照（0.5 天）

- 从 `54c9ee6` 开分支 `engine/vendor`。
- 保留当前 site-packages 的 ok-script 作为 A/B 对照，**不立即卸载**。
- 记录当前启动时间、`import ok` 时间、评估 20 只的耗时/内存（真机）。

### P1：复制 + 命名空间（1~2 天）

- 按 2.1/2.2/2.3 复制 61 个文件到 `ww_engine/`，保持目录层级。
- 用脚本把所有 `from ok...` / `import ok...` 改为 `ww_engine...`（只改 import 语句，不改字符串/日志）。
- 新增 `ww_engine/app.py` 最小 App；重写 `__init__.py` 的 `OK/og`。
- 此时先**不删**旧 `ok` 依赖；`mainui.py` 仍走旧入口，确保可回退。

### P2：裁剪与切换（2~4 天）

- 按 2.2 逐文件裁剪；每裁一个文件跑一次 `python -m compileall` + 单测。
- 切换 `mainui.py` / `src/task/*` / `ui/*` / `tools/ui_shot.py` 到 `ww_engine`。
- 删除 `Screenshot`、`paperclip`、i18n、ADB/浏览器/模拟器分支。
- 从 `requirements.txt` 移除 `ok-script`，删除 `tools/patches/` 的安装步骤（保留历史说明或移到 CHANGELOG）。

### P3：离线验收（0.5 天）

| # | 命令 | 通过标准 |
|---|---|---|
| V1 | `python -m compileall ww_engine src ui tools` | 退出码 0 |
| V2 | `python -m unittest discover -s tests` | **182 项 / OK (skipped=2)** |
| V3 | `python tools/ui_shot.py` / `--dark` | **7 页**，无异常 |
| V4 | `python -c "import ww_engine; from ww_engine import OK, og, BaseTask, FindFeature, Logger, Box"` | 导入成功 |
| V5 | `grep -R "from ok\\|import ok" --include=*.py .` | **0 命中**（`helios/` 除外） |
| V6 | `python tools/echo_plan.py --list-profiles` | 4 个预设 |
| V7 | `python tools/offline_eval_report.py`（有素材时） | 109 只；判定分布与 B2 一致（或记录差异并解释） |
| V8 | 启动时间 / 内存 | 记录新旧对比；`import ww_engine` 目标 < 0.5 s（软目标） |

### P4：真机验收（1~2 天）

- **先点一次「调试工具」页的「OCR 测试」**（最短复现路径）：它直接走 `BaseTask.ocr()` → `onnx_ocr()`；
  本轮修的 P0（裁剪后 `fix_texts` 引用已删属性）就是在这条路径上必炸。要求：无 `AttributeError`，
  日志里 `ocr_zone ... found result` 有文字；同页截图预览、覆盖层开关正常。
- 本地模式：选窗 → 评估 20 只 → 强化 5 只 → 暂停/继续/停止。
- 云游戏模式：F11 全屏 → 自动锁窗 → 前台键鼠 → 评估 10 只。
- 设备设置：切换截图方式（WGC/BitBlt）、交互方式（PostMessage/Pynput）、重启生效。
- 覆盖层开关、日志、截图、OCR 测试、导出报告；跑完 grep 日志无 `AttributeError` / `NameError` / `UnboundLocalError`。
- 关键回归：窗口最小化/被遮挡/切走再切回；开始任务自动拉前台；停止后无残留线程。

### P5：清理与文档（0.5 天）

- 删除 `tools/patches/` 或改为“历史参考（已不适用）”。
- 更新 `README`/`CLAUDE`/`docs/BASELINE.md`/`handoff.md`/`CHANGELOG`：
  - 依赖不再有 ok-script；补丁章节删除；启动步骤去掉 `apply_patches.py`。
  - 目录结构加 `ww_engine/`；说明“引擎自持，MIT 来源与版权声明”。
- 新增 `THIRD_PARTY_NOTICES.md`：ok-script MIT 版权/许可原文 + 修改说明。
- 版本号从 `echo-dev` 提一个阶段号；提交 `阶段三十一：引擎自持（精简 vendor ok-script）`。

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| `DeviceManager`/`StartController` 裁剪破坏生命周期 | 启停/暂停/切窗失效 | 逐方法裁剪；保留原方法签名；真机走查；必要时先保留原文件只改 import |
| OCR 初始化分支裁剪 | 评估/强化直接不可用 | 只保留 `onnxocr` 分支；用现有 `config['ocr']` 跑离线 OCR 测试；保留异常日志 |
| QApplication 初始化顺序 | 自建 UI 启动崩 | `ww_engine.app` 先创建/复用 QApplication；`MainWindow` 之后构造；`ui_shot` 桩件验证 |
| 云/本地窗口定位回归 | 找不到窗口 | 保留 `find_hwnd` 空 exe 补丁、`hwnd_window.visible` 补丁、`pynput` 拉前补丁，直接写进 vendored 文件 |
| `supported_languages` 过滤 | 任务不加载 | 用常量 `zh_CN`；或保留 `TaskManager` 的简单过滤 |
| 覆盖层/静音依赖 | 调试页开关失效 | 第一阶段保留 overlay + pycaw；第二阶段再决定是否删 UI 开关 |
| 许可/归属 | 合规风险 | ok-script 为 MIT；保留版权声明与 `THIRD_PARTY_NOTICES.md` |
| 一次性改动过大 | 难定位回归 | 分支 + 分阶段提交；P1/P2 每步可回退；旧 `ok` 保留到 P4 通过 |

**回滚方案**：`ww_engine` 是新增包，`mainui.py` 的 import 切换是单点；回滚只需恢复 `from ok` 与 `requirements.txt`，旧 site-packages 仍在，不影响已发布版本。

---

## 8. 已定的取舍（不再讨论）

1. **不整体重写**：保留经过真机验证的 capture/interaction/feature/task 内核；只重写 `OK/App/TaskManager` 外壳。
2. **不保留 ok-ww GUI**：自建 PySide6 UI 是产品层，引擎不再带 MainWindow/各 Tab/resources.py。
3. **不支持 ADB/模拟器/浏览器 capture/Genshin**：本项目只服务 Windows 本地客户端 + 云游戏窗口。
4. **OCR 只留 onnxocr + OpenVINO**：不保留 paddle/rapid/dguang 分支。
5. **不保留自动更新/打包/Analytics/i18n/剪贴板**。
6. **第一阶段保留 overlay 与静音**，避免 UI 功能回退；第二阶段再评估删除。
7. **包名 `ww_engine`**，不继续叫 `ok`；业务层 import 边界清晰。
8. **Rust 不在本阶段引入**：先完成引擎自持与 profile；Rust 只在后续有实测瓶颈时作为接口后的可选实现。

---

## 9. 已确认的取舍（实施时采用）

- [x] 第一阶段保留 overlay + 静音（`pycaw` 写入 requirements）；调试页/设备页不改。
- [x] 删除 `tools/patches/` 与安装步骤；4 处补丁内联。
- [x] 包名 `ww_engine`。
- [ ] P4 真机验收由用户在素材机执行（本地/云游戏各一轮；清单见 §6）。
