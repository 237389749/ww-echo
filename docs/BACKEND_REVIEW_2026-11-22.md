# ww-echo 后端代码审查（2026-11-22）

> 范围：`src/`（domain 18 个模块 + task adapter）、`ww_engine/`（任务运行时/截图/输入/配置）、
> `ww_app_shell/`、`tools/`（CLI + 复现脚本 + 生成器）、`config.py` / `mainui.py`、`tests/`。
> **不含**界面观感与排版 —— 那部分见 [`docs/UI_REVIEW_2026-11-22.md`](UI_REVIEW_2026-11-22.md)（B1~B4 已全部落地）。
>
> 方法：全量精读（`EnhanceEchoTask` 2472 行 + `ww_engine/task/*` + `ui/run_tab` 的报告/保存路径）+ AST 静态扫描
> 168 个入库 `.py`（可变默认参数 / 裸 except / 无 `with` 的 `open` / 断言式校验）+ 20 余个**可复现探针**
> （每条 🔴🟡 都给了命令与输出）。引擎层与工具层各有一路并行审查，本文只收**主审复核过**的条目。
>
> 基线：审查时 `python -m unittest discover -s tests` → `Ran 411 tests / OK (skipped=2)`，退出码 0；
> **A 批落地后 423 项**（+12，见 §7.4）、**B 批落地后 455 项**（+32，见 §7.5）。审查期间**未改动仓库任何文件**（探针产物只写 `%TEMP%`）。
>
> **进度**：🔴 A1~A4 **已修**（补记 78）；🟡 B1~B13 **已修**（补记 79，单测 423 → **455**）；🟢 C1~C17 未动，按 §7 分批。
>
> **修复入口见 §7**：A 批（4 个 🔴）→ B 批（13 个 🟡）→ C 批（16 个 🟢）。改测试后记得同步文档里的项数。

---

## 0. 一页结论

**设计是对的，失败路径是哑的。** 分层（engine → shell → domain → task_adapter → ui）、判定口径的唯一收口、
docstring 里"为什么这么写 + 踩过什么坑"的记录，都明显高于同类个人项目；判定数学（`A ≥ B` 的集合论证、
暴击 100% 封顶、档位离散匹配、概率期望当分母）我逐条验过是自洽的。
问题集中在**四类没有出口的静默失败**：写图片、读预设、算门槛、清资源。

先修 4 个 🔴（都是"看起来成功了，其实没成"）：

| # | 现象 | 根因 | 证据 | 修法一句话 |
|---|---|---|---|---|
| A1 | 报告里 160 张截图**全是碎图**，日志还说"画面已存" | 评估链用裸 `cv2.imwrite`，而它对非 ASCII 路径**静默返回 False**；项目自己有 `imwrite_unicode` 却没用在这条链 | 本机实测 `cv2.imwrite(中文路径) -> False, exists=False` | 四处改 `echo_panel_shot.imwrite_unicode`；`_save_fail_frame` 检查返回值 |
| A2 | 一次 BOM/写坏 = 用户**全部角色预设被覆盖销毁** | `load_all` 把"解析失败"当成"没有预设"→ `upsert` 用 1 条覆盖全文件 | A/B/C 三个角色 + BOM → `upsert` 后只剩 `['新角色']` | 写路径用**严格读**（坏文件报错拒写）；落盘改 `tmp + os.replace` 原子替换 |
| A3 | `--profile` 复现出的**是另一套门槛**（静默算错） | 载入块只搬 bare/补正/专伤/配装，`energy/crit/max_level_only` 一律读 argparse 默认值；`to_request_kwargs`（自称"唯一翻译层"）**零生产调用** | `--help` 声称载入门槛；`src/char_profiles.py:81` 只被单测引用 | 把 profile→门槛的合并做成可测函数，`to_request_kwargs` 打底 + 显式参数覆盖 |
| A4 | 关程序时**整条清理链被跳过**，评估临时目录永久残留 | `sleep()/frame` 里的 `sys.exit(0)` 抛 `SystemExit`（`BaseException`），`execute()` 的 `except Exception` 抓不到 → `destroy()` 永不执行；评估侧 `except Exception` 也不跑 `rmtree` | `destroy()` 在 `execute()` 的 while **之外**；`except (SyntaxError...)` 同理 | `execute()` 改 `try/finally`；评估侧改 `except BaseException`（**保留** `sys.exit`，见 §7.3 的理由） |

统计：**🔴 4 / 🟡 13 / 🟢 16**，另有 §6 的 8 条文档与实现不符。

---

## 1. 评审范围与方法

| 对象 | 覆盖方式 |
|---|---|
| `src/` 全部 18 个模块 | 逐行精读；判定数学单独推了一遍；概率表↔档位表↔生成物↔图标三方一致性用脚本对账 |
| `src/task/EnhanceEchoTask.py`（2472 行） | 逐行精读；评估遍历的 4 个结束判据、3 个兜底分支、面板回顶判据单独画了状态机 |
| `ww_engine/task/*` + `ww_app_shell/*` | 逐行精读任务运行时/生命周期/配置持久化；4 处 vendored 补丁逐条验行为 |
| `tools/`（含 `analysis/`） | 实跑主链路（`echo_plan` / `offline_eval_report` / `verify_eval_run` / `replay_panel_scroll` / `import_coupling`）+ 读码找"复制线上判定" |
| `tests/` | 415 个用例做 AST 扫描找**零断言/自证**用例；抽查守卫是否真调实现 |
| 静态卫生 | AST 扫 168 个入库 `.py`：可变默认参数 0、`== None` 0、`assert` 式校验 0（`ww_engine/util/collection.py:53` 除外）、裸 `except:` 3 处（全在 vendored 引擎） |

**没覆盖**：真机（游戏窗口 + 管理员权限）、`logs/eval_debug/20260911_110817/`（未入库，B2/B3 基线跑不了）、
离屏渲染类工具（属界面审查范围）。

---

## 2. 🔴 必须修

### A1 评估截图在非 ASCII 路径下静默写不出（✅ 已修，补记 78）

**位置**：`src/task/EnhanceEchoTask.py:1653`（主路径）、`:392`（失败留证）、`:952`（读不干净的面板）、
`:706` / `:711` / `:714`（debug 数据集）

**证据**：这四处都是裸 `cv2.imwrite`。截图目录来自 `tempfile.mkdtemp()`（`:533`），默认落在
`%TEMP%` = `C:\Users\<用户名>\AppData\Local\Temp`。本机实测：

```
cv2.imwrite 非ASCII路径 -> False exists= False
cv2.imwrite ASCII路径   -> True  exists= True
```

项目**早就知道这个坑**并写了工具：`src/echo_panel_shot.py:25` `imwrite_unicode`
（docstring 原话："cv2.imwrite 在 Windows 上按 ANSI 码页处理路径 → 中文文件名会写成乱码名字"）、
`src/echo_inventory.py:110` `imread` 也有回退。**唯独出报告那条链没用**。

**影响**：只要 Windows 用户名是中文（或仓库/工作目录在中文路径下，`logs/` 是相对 CWD 的），
① 报告的缩略图与详情大图全是碎图，而 `total` / 判定 / 分数都正常 → 用户以为"报告本来就这样"；
② `_save_fail_frame` **不检查返回值**，仍把路径返给调用方，日志于是写
"当时抓到的画面已存: `...\logs\eval_fail_frame.png`" —— 文件根本不存在，下一次排查被这条假证据带偏
（这条 docstring 自己的用途就是"检测不到网格时自查"）。

**修法**：四处统一走 `echo_panel_shot.imwrite_unicode`（已在 `:13` import，无需新依赖）；
`_save_fail_frame` 改成写入失败返回 `''`。

**验收**：`python -m unittest discover -s tests` 里有新守卫；
手动 `<中文目录>\\python -c` 复现一次 `imwrite_unicode` 出图。

---

### A2 角色预设：读失败被当成"空文件"，下一次保存覆盖销毁全部预设（✅ 已修，补记 78）

**位置**：`src/char_profiles.py:40-49`（`load_all`）、`:52-58`（`save_all`）、`:61-68`（`upsert`）

**证据**：

```python
def load_all(path: str = "") -> dict[str, dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}                       # ← "文件坏了" 与 "文件不存在" 不加区分
```

实测（临时文件里先放 A/B/C 三个角色，加一个 UTF-8 BOM 模拟记事本保存）：

```
初始角色: ['A', 'B', 'C']
加 BOM 后 load_all = {}
upsert 之后文件里的角色: ['新角色']          ← A/B/C 全没了
```

`upsert` 的实现是"读全量 → 改一条 → 写全量"，而 `save_all` 先 `open(path,"w")` 截断再写（非原子）。
`assets/char_profiles.json` 里现在是爱弥斯 / 绯雪 / 西格莉卡 / 仇远 —— **用户手填的真实输入**
（含西格莉卡那条「共效 > 125 转增伤」天赋）。

**影响**：一次 BOM、一次写到一半的断电、一次手工改坏，下一次「保存为…」或 `--save-profile`
就把其余角色**永久抹掉**，且只打印"已保存 xxx"。

**修法**：`load_all` 保留宽松口径（UI 列表不能因为坏文件就崩），但**写路径**（`upsert`/`delete`）
改用严格读：文件存在却解析不了 → 抛 `ProfileFileError`，调用方明确报错并**拒绝写**；
`save_all` 改 `tempfile` + `os.replace` 原子替换（崩溃时旧文件完好）；
`os.makedirs(os.path.dirname(path))` 对"裸文件名"路径要有兜底。

**验收**：新单测覆盖 "坏文件 + upsert → 抛错且原文件字节不变"、"正常 upsert 后旧键仍在"。

---

### A3 CLI `--profile` 不载入门槛参数与满级开关 → 静默算另一套数（✅ 已修，补记 78）

**位置**：`tools/echo_plan.py:290-306`（载入块）vs `:94-103`（`build_request`）；
`src/char_profiles.py:81`（`to_request_kwargs`）

**证据**：`--help`（`:213`）写着"载入**角色预设**(裸面板/补正/专伤/**门槛**/配装)"，但载入块只搬了
bare / corrections / specialty / plan / scaling，门槛一律取 argparse 默认值：

```python
energy_min=getattr(a, "energy_min", 120.0),          # ← 永远是 argparse 默认
max_level_only=not getattr(a, "all_levels", False),
```

而**翻译层没被调用**：

```
src\char_profiles.py:81                      (定义, docstring: "预设与引擎之间唯一的翻译层")
tests\test_char_profiles.py:55,56,65,95       (只有单测)
```

保存侧却把门槛写进去了（`:309-317`）——**存门槛、不读门槛**，是不对称。
UI 侧 `ui/plan_tab.py::_load_profile` 是全的（energy/crit/plan 都读），所以只有 CLI 中招。

**影响**：`--energy-min 110 --crit-target 90 --save-profile X` 之后，`--profile X`
复现的是 120/100 的结果；排名、A/B 类判定全变，输出看起来完全正常。
现有 4 个预置恰好都是默认门槛，所以一次都没炸过 —— 这类"预置恰好没触发"的 bug 最难发现。

**修法**：新增可测的 `apply_profile_thresholds(a, profile)`（尊重 `_given(a, flag)` 的显式覆盖），
由 `to_request_kwargs` 提供字段值；`build_request` 之外不再手写第二份映射。
补一条守卫：`to_request_kwargs` 能吐出的**每一个键**，CLI 都必须消费到（防以后再加字段又漏）。

**验收**：新单测用 `Namespace` 直接调 `apply_profile_thresholds`，断言 7 个字段 + `all_levels` 都进来了；
再断言显式参数优先。

---

### A4 引擎 `sys.exit(0)` 打断整条清理链（✅ 已修，补记 78）

**位置**：`ww_engine/task/TaskExecutor.py:264`（`sleep`）、`:217`（`frame` 属性）；
`destroy()` 在 `:505`（`execute()` 的 while **之外**）；评估侧 `src/task/EnhanceEchoTask.py:1757`

**证据**：

```python
if self.exit_event.is_set():
    logger.info("sleep Exit event set. Exiting early.")
    sys.exit(0)          # SystemExit 是 BaseException, execute() 的 except Exception 抓不到
```

`threading` 对 `SystemExit` 完全静默（`_bootstrap_inner` 里 `except SystemExit: pass`）→
`execute()` 的循环被穿透 → **`self.destroy()` 永不执行**，而它是 `task.on_destroy()` /
`interaction.on_destroy()` 的唯一入口。`exit_event` 只在关程序时被置位
（`ww_app_shell/app.py:71`、`ww_engine/__init__.py:201`），所以这是"退出时"的泄漏。

同一条 `sys.exit(0)` 在 `frame` 属性里，而**评估链在 UI 线程上大量读 `self.frame`**；
`evaluate_only` 的清理只在 `except Exception`（`:1757`）里，`SystemExit` 穿过去 →
`shutil.rmtree(tmp_dir)` 不执行。

**影响**：评估进行中关窗 → `%TEMP%\okecho_eval_*` 永久留下（`SAVE_PANEL_DATASET` 默认开，
每只面板裁剪 100~400 KB，一轮可能几百 MB）；正常退出也会跳过交互层/任务的清理钩子
（`pynput` 的鼠标状态、`hwnd_window` 的线程）。

**修法**：`execute()` 改

```python
try:
    while not self.exit_event.is_set():
        ...
finally:
    self.destroy()
```

评估侧 `except Exception` → `except BaseException`（先 `rmtree` 再 `raise`）。
**不改** `sys.exit(0)` 本身：`FinishedException` 继承 `Exception`，沿途有十几处
`except Exception`（`_panel_scroll`、`read_set_by_effect` 的调用方等），改完会被吞掉反而不停 —— 见 §7.3。

**验收**：新单测用假 executor 跑一次"循环里 `sys.exit`"（`SystemExit` 或 `FinishedException`），
断言 `destroy()` 被调用；评估侧测 `BaseException` 路径下临时目录被清。

---

## 3. 🟡 应该修

| # | 位置 | 问题（一句话） | 证据/影响 |
|---|---|---|---|
| B1 | `ui/run_tab.py:664-693` | 保存报告**先拷截图/渲染 HTML、最后才写 JSON**，任何一步失败 → `finally` 删临时目录 → **12 分钟评估结果全丢** | 顺序：`copytree` → 读 json → `_build_eval_html` → 写 html → 写 json_dest |
| B2 | `ui/run_tab.py:633-639` + `ww_app_shell/start_controller.py:48` | 把**异步** `start()`（`handler.post`）当同步 → 点「开始」后日志立刻打「══ 结束 ══」、按钮复位、可再点一次 | `Handler.post`（`util/handler.py:86`）只入队 + notify |
| B3 | `src/echo_set_templates.py:114,150` + `:177-191` | 模板校验**抛异常**而不是过滤：`{"暴击":"高"}` → `ValueError` 冒到 `EnhanceEchoTask.__init__`，整个程序起不来 | 实测三种坏值全抛；`load_templates` 只接 `FileNotFoundError`/`JSONDecodeError` |
| B4 | `tools/analysis/verify_eval_run.py:372` | 读错字段名（`main_prop_check` vs 真实 `main_values_check`）→ 「主属性数值可疑」**验收永远不报警** | 全仓只有这一处写 `main_prop_check`；写侧在 `EnhanceEchoTask.py:2314` |
| B5 | `tools/analysis/verify_eval_run.py:16` vs `:342-362` | docstring 承诺 `effect = 0` 闸门，代码里**没有** | 硬门槛只有 `text+icon`；`n_effect` 只进展示 |
| B6 | `tests/test_set_fast_path.py`、`tools/analysis/panel_scroll_time.py`、`tests/test_gbk_output.py:61` | 2 个**入库**文件带 BOM → GBK 守卫 `except SyntaxError: continue` → 这两个文件**整份逃出守卫** | 去 BOM 后能看到 5 个 `print`；CLAUDE 的"全仓 BOM 已清"不成立 |
| B7 | `tests/test_doc_claims.py:40-45,102-109` | `test_set_lines` 断言的是**测试自己抄的一份公式** → 套装 B 线无保护 | 实现换成常数 → `test_general_line` FAIL，`test_set_lines` 仍 ok |
| B8 | `ui/run_tab.py:1176-1203`（另 `:1146-1148`） | 报告 HTML **未转义** OCR 文本：`data-name="{name}"`、`title="{set_src}"`、`<option value="{n}">` | 一个 `"`/`<` 就破坏属性或吃掉半行；筛选下拉与 JS `dataset` 随之失配 |
| B9 | `tools/analysis/icon_accuracy_report.py:102`、`replay_panel_scroll.py:88-95`、`calculator_reconcile.py:131-146` | 三处**复制线上判定**：图标 ZNCC（自称"同一套"却自己又写一遍）、面板找套装策略顺序、Top-5 分母 | 线上改 SHIFT/策略/分母，工具仍按旧数学给 99.3% / 87.9% |
| B10 | `tools/echo_plan.py:90` vs `:184`；`tools/offline_eval_report.py:195` | CLI 错误处理一半友好一半裸 traceback（`--set-b` 缺失、两套相同、`--derive` 非数字）；素材模式 `--out` **静默无效** | `--cost4` 缺失是友好 `SystemExit`；`--set-b` 缺失实测 `ValueError` 堆栈，exit 1 |
| B11 | `tools/gen_echo_data.py:184` vs `:19` | `_props()` 用 `tm.get(...)` 且 `if name:` → **静默丢属性名**，不记 `unresolved`；违背"解析不出退 2 不写文件" | 同文件 `_plan()` 是正确写法（记 `unresolved`）；属性缺失会让主属性网格缺项 |
| B12 | `ww_engine/util/config.py:152`、`ww_engine/util/file.py:25` | 类型不匹配**静默回退默认值**（磁盘上的 `'True'` 下次启动变 `False` 并覆写）；写文件是截断后写，崩溃 → 空文件 → 全量重置 | 影响 `config.py` / `devices.json` / 全部任务配置 |
| B13 | `ww_engine/device/capture_methods/bitblt.py`（无 `close`）、`ww_engine/task/TaskExecutor.py:450` | BitBlt 切 WGC 时 GDI 对象只增不减（`BaseCaptureMethod.close()` 是 `pass`）；`prevent_sleeping(True)` 无 `try/finally` → 任务异常后进程活着期间不自动睡眠 | 已在读码时确认；`bitblt_utils` 只在尺寸/hwnd 变化时清理 |

---

## 4. 🟢 可选

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| C1 | `src/echo_set_templates.py:572` | `get_set_weights` 返回**缓存里的同一个 dict**（实测改一下就全局生效） | 返回 `dict(...)` 副本 |
| C2 | `src/char_profiles.py:139` | `DerivedBonus.cap` 缺省 `inf` → 落盘写出 `"cap": Infinity`（**非法 JSON**） | 不写该键，或写 `null` |
| C3 | `src/echo_score_sim.py:47` | 分布只按套装名缓存，权重改了 `score_percentile` 不变（当前无调用点） | 缓存键加权重指纹 |
| C4 | `src/echo_combos.py:230` | 堆元素注解是 4 元组，实际压 8 元组 | 修注解 |
| C5 | `src/task/EnhanceEchoTask.py:124` | 未知套装名 → `_legacy_threshold` 静默返 0 → 全判达标（当前被 `_check_set_keys` 挡住） | 未知套装抛错 |
| C6 | `src/task/EnhanceEchoTask.py:216` | `_pair_props` 贪心最近配对，同 y 相邻时可能错配并级联 | 按 y 归并 + 最大距离闸 |
| C7 | `src/task/EnhanceEchoTask.py:1322` | docstring 说返回 5 项，实际 6 项（多了 `level_box`） | 补文档 |
| C8 | `src/echo_inventory.py:123` 等 10 处 | `open().read()` 不用 `with` | 统一 `with` |
| C9 | `src/wuwa_data.py:43` | zip 模式 `ZipFile` 永不关闭；`_index` 用 `setdefault` → 同名表静默遮蔽 | `close`/`__enter__`；重名告警 |
| C10 | `tools/echo_plan.py:279` | `--top 0` 实际出 1 行（`max(1, top_k)`）；`--list-all` 上限 99 | 校验 `--top >= 1` |
| C11 | `tools/icon_export/swap_icons.py:38-60` | **先覆盖、后备份** → 备份下来的是新官方图，`--apply` 无法回滚 | 备份块前移 |
| C12 | `tools/gen_echo_data.py:340` | 生成物 `_source` 写入**本机绝对路径**（已入库） | 只留 version/hash |
| C13 | `ww_engine/util/window.py:98` | 用 `ctypes.wintypes.RECT()` 但只 `import ctypes`，靠别的模块顺手挂上 | 顶部显式 `import ctypes.wintypes` |
| C14 | `ww_engine/util/process.py:57` | `_CreateMutex` 与 `_GetLastError` 之间插了一次写日志的文件 I/O | 先取值再打日志 |
| C15 | `src/task/EnhanceEchoTask.py:1764` | `run()` 两个 `while True` 无迭代上限，靠引擎调用抛 `TaskDisabledException` 兜底 | 加次数上限 |
| C16 | `src/task/EnhanceEchoTask.py:533` | `on_done=None`（离线/批处理）时成功路径不清理临时目录 | 无回调时自行清理 |
| C17 | `tools/echo_plan.py:309` | `--save-profile` 把 `req.allowed_bonus` 当"用户显式指定"存下来，而它多半是**模板推断值**；之后换套装仍钉着旧并集 | 存一个 `specialty_src`：`explicit` / `template`，载入时只对 `explicit` 生效 |

---

## 5. 已核查**未发现**问题（供判断覆盖面，不必重审）

- **判定数学**：`A ≥ B` 当 `k ≥ L` 的集合论证成立；`_tier_from_level` 只升不降；`reforge_plan`
  只在 `missing == 0` 时跑（孔位建模不会错位）；暴击 100% 封顶与 `crit_factor` 的 `min(100)` 一致。
- **概率表 vs 档位表**：13/13 词条逐档吻合，Σ = 99.9998~100，**没有一条静默回退算术平均**
  （特意去查了 `_expected_tier` 的 `len(p) != len(tiers)` 分支 —— 一旦命中，评分基准会悄悄变）。
- **套装名三方一致**：模板 37 / 图标 37 / 生成物 37，互相差集为空。
- **坐标映射**：`ratio=None` 线性映射；`clamp_to_grid` 的 inset、`click_relative` 的往返换算正确。
- **静态卫生**：168 个入库 `.py` 里 0 个可变默认参数、0 个 `== None`、0 处用 `assert` 做校验；
  裸 `except:` 只有 vendored 引擎 3 处。
- **CLI 主链路**：`--list` / `--list-profiles` / `--bare` 坏格式 / `--all-bonus` / 未知键进 `Panel.unknown`
  提示 —— 都正常，无静默吞。
- **基线复核**：`--list` 输出 `160 只 / 49 个名字 | COST {1:66, 3:77, 4:17} | 满级 131`，与 `BASELINE.md` 逐字一致。
- **`verify_eval_run --check`**：160 条 / 重复 0 / 回顶 0 / `text 139` / `effect 0` → `[ok]`，退出 0（口径见 B4/B5）。

---

## 6. 文档与实现对不上（只列可验证的）

| 文档 | 声称 | 实际 |
|---|---|---|
| `CLAUDE.md`（分层/C 面） | "2026-11-19 顺手清了全仓 BOM" | 仍有 **2 个入库文件**带 BOM，并因此逃出 GBK 守卫（B6） |
| `docs/BASELINE.md:96` §2 | `verify_eval_run` 验收 `set_src=text ≥85%` | 代码闸门是 **text+icon**（§1 已改，§2 没跟） |
| `docs/BASELINE.md:96` §2 | 同一行"`effect` 0" | **没有闸门**（B5） |
| `docs/BASELINE.md:135` §3 | `.scratch/` 在仓库**父目录**，`git ls-files` 为 0 | 本机在**仓库根内**（43 文件）→ `import_coupling.py --check` 被它打崩（实测 SyntaxError，exit 1） |
| `docs/BASELINE.md:133` §3 | B5 属"无法跑" | B5 **能跑**（`--list` 走 `eval_report6.json`） |
| `tools/offline_eval_report.py:20` | 产物 `eval_report.html` **或** `eval_report_<时间戳>.html`，`--out` 控前缀 | 素材模式写死 `eval_report.html` 且忽略 `--out`（B10） |
| `src/char_profiles.py:81` | `to_request_kwargs` 是"唯一翻译层" | **零生产调用**（A3） |
| `tools/gen_echo_data.py:19` | "任何文本键解析不出 → 退出码 2 且不写文件" | `_props` 静默丢（B11） |

---

## 7. 修复计划

### 7.1 分批与顺序

| 批次 | 内容 | 为什么这个顺序 | 预估改动 |
|---|---|---|---|
| **A（先做）** | A1~A4 | 都是"静默毁掉交付物/用户数据/静默错数/资源确定泄漏"，且改动面小、可离线验收 | 4 个文件 + 1 个新测试文件 |
| **B（第二批）** | B1~B12 | 验收类（B4/B5/B6/B7）与"错误处理一致性"（B3/B10）先做，因为它们决定"以后改判定还敢不敢信测试"；B1/B2 是生命周期收口；B8 是报告正确性 | 每个 5~30 行 |
| **C（顺带）** | C1~C16 | 卫生与潜在雷，不单独开批 | 多为 1~3 行 |

### 7.2 A 批的执行清单（本次落地）

| 步骤 | 文件 | 改动 | 验收 |
|---|---|---|---|
| A1-1 | `src/task/EnhanceEchoTask.py` | 4 处落盘（截图 / 失败帧 / 失败面板 / debug 三连）改 `imwrite_unicode`；`_save_fail_frame` 检查返回值 | 新守卫：模块内**不再有** `cv2.imwrite(`；`_save_fail_frame` 写入失败返回 `''` |
| A2-1 | `src/char_profiles.py` | 加 `ProfileFileError` + 严格读 `_read_strict`；`upsert`/`delete` 用它；`save_all` 改 `tmp + os.replace` | 新单测：坏文件 + `upsert` → 抛错且**原文件字节不变**；正常路径旧键仍在 |
| A3-1 | `tools/echo_plan.py` + `src/char_profiles.py` | 新增 `apply_profile_thresholds(a, profile)`（用 `to_request_kwargs` 的字段、尊重 `_given`）；`main()` 载入预设后调用 | 新单测：7 个门槛字段 + `all_levels` 全部生效；显式参数优先 |
| A4-1 | `ww_engine/task/TaskExecutor.py` | `execute()` 的 while 包 `try/finally: self.destroy()` | 新单测：循环里抛 `SystemExit` → `destroy()` 仍被调用 |
| A4-2 | `src/task/EnhanceEchoTask.py` | `evaluate_only` 的 `except Exception` → `except BaseException`（先 `rmtree` 再 `raise`） | 静态断言或行为测试 |
| A-验收 | — | `python -m unittest discover -s tests` / `python tools/echo_plan.py --profile ...` 前后对比 / 中文路径落盘手测 | 全绿 + 项数同步进 BASELINE/CLAUDE/handoff |

### 7.3 明确**不做**的事（以及为什么）

- **不把 `sys.exit(0)` 改成 `raise FinishedException()`**：`FinishedException` 继承 `Exception`，
  沿途 `except Exception` 有十几处（`_panel_scroll`、`read_detail` 的调用方、`evaluate_only` 等）。
  改完会被其中一处吞掉继续跑，比现在的"线程干脆退出"更难排查。清理链的问题用 `try/finally` 解决，
  语义不变。
- **不给 `load_all` 加 `.bak` 轮转**：`tmp + os.replace` 已经是原子的，崩溃时旧文件完好；
  多一层备份反而要处理"备份自己也坏了"的分支。
- **不动 `char_profiles.json` 的现有内容**（4 个预置是用户输入）。

---

### 7.4 A 批落地记录（2026-11-22，补记 78）

| 项 | 实际改动 | 守卫 / 验收 |
|---|---|---|
| A1 | `EnhanceEchoTask` 6 处落盘 + `offline_eval_report`（写截图 **与** 读整帧）+ `ui/debug_tab` 手动截图 → `imwrite_unicode` / `imread`；`_save_fail_frame` 检查返回值 | `test_backend_guards.TestImageWriteGuard` 3 项（产品面无裸 `cv2.imwrite`、中文目录真出图、写失败返回 `''`） |
| A2 | `ProfileFileError` + `_read_for_write`（写路径严格读）+ `save_all` 原子写；`load_all` 只留给展示 | `test_char_profiles` 3 项（坏文件拒绝覆盖且原文件字节不变 / 拒绝 delete / 原子写不留 `.tmp`） |
| A3 | `char_profiles.apply_thresholds`（经 `to_request_kwargs`）+ CLI 接线 + 摘要打印 | `test_char_profiles` 3 项（7 字段全载入 / 显式优先 / 新增字段必须有人消费） |
| A4 | `TaskExecutor.execute` = `try: _execute_loop() finally: destroy()`；`evaluate_only` 捕 `BaseException` | `test_backend_guards.TestLifecycleGuard` 3 项（AST + 假 self 真跑 `SystemExit` 路径 + AST 捕 `BaseException`） |

验收数字：单测 **423**（+12）、探针 5/5、离线重放 160 条**分数变化 0.000**、`verify_eval_run --check` 全过、
`echo_plan --list` 仍 160 只 / 49 名字。

**A 批顺带发现（记在这里，没改）**：`tools/analysis/probe_*.py` 3 个探针仍用裸 `cv2.imwrite`（一次性脚本，已进白名单）；
`ui/debug_tab` 的截图路径来自 `os.getcwd()`，与 `screenshots_folder` 配置没打通（原本如此，未动）。

### 7.5 B 批落地记录（2026-11-22，补记 79）

| 项 | 实际改动 | 守卫 |
|---|---|---|
| B4 | `verify_eval_run` 读真实字段 `main_values_check` 的 `ok is False`（旧名 `main_prop_check` 恒 0） | `test_verify_eval_run` +3 |
| B5 | `effect > 0` 一律打印并 WARN（不判失败，旧报告兼容）；docstring 与代码对齐 | 同上（含"text 多数 + 1 条 effect 也要说出来"） |
| B6 | 去掉 2 个入库文件的 BOM；守卫改读 `utf-8-sig`、BOM 直接报错、`except SyntaxError` 改成 fail；`SKIP_DIRS` 加 `.scratch`/`.venv` | `test_gbk_output`（**改完立刻抓到我自己新写的 `⚠`**） |
| B7 | `test_set_lines` 改成断言 `_legacy_threshold` 本身，`_b_line` 降级为交叉校验 | 把实现换成常数 → 测试必须红（已实测） |
| B3 | `_validate_and_filter` 对非数字权重/非列表 `_core_first` 告警跳过 | `test_echo_set_templates` +3 |
| B10 | `--set-b` 缺失/两套相同/套装名打错（带 difflib 建议）/`--derive` 非数字 → 友好 `SystemExit`；`plan()` 的 ValueError 转 SystemExit；素材模式认 `--out` | `test_plan_cli` +8 |
| B8 | 报告里名字/词条/主属性/套装/选项全部过 `_esc()`（`html.escape(quote=True)`） | `test_report_layout` +2 |
| B11 | `gen_echo_data` 的属性名/声骸名改走 `self.zh()`（解析不出 → `unresolved` → 退 2），不再回落成文本键 | `test_gen_echo_data` +3 |
| B1 | 评估保存改"先数据 → 再截图（失败只告警）→ 最后 HTML" | 代码审查（路径要真机弹框，未做 UI 自动化） |
| B2 | `StartController.start(on_done=ok)` + `communicate.task_done`（正常/停止/异常三条路都发）驱动运行页状态 | `test_start_controller` +4 |
| B12 | `Config.verify_config` 对 `"True"`/`"3"` 做 coerce（不再静默回默认），坏文件先存 `.bad`；`write_json_file` 原子写 | `test_engine_config` +8 |
| B13 | `BitBltCaptureMethod.close()` 真释放 GDI；`prevent_sleeping` 加 `finally` | `test_backend_guards` +1（句柄计数要真机） |

**刻意没做**：`_coerce` 只覆盖标量（`bool/int/float/str`），嵌套 dict 仍按"类型匹配就用"——深合并语义没有需求，
改它会把"用户删掉的子键"又补回来。B13 的 D3D `create_device()` 覆盖前不 Release、`overlay.ui_dict` 从没写入
（engine-review 的第 11/15 条）留给下一轮：它们要真机才能验证"修完真的不漏/真的画得出"。

## 8. 未验证 / 下一棒

1. **真机**：A1 的修复需要一次真机评估确认截图落在中文路径下也能出图（本环境只能在 `%TEMP%` 造中文目录模拟）。
2. **B2 的修法依赖界面改造**（连接 `communicate.task_done` 驱动状态），建议和界面下一轮一起做。
3. **B9 的收口**（把图标 ZNCC / 面板策略 / Top-5 分母提到 `src`）会改动判定链，必须先跑
   `python tools/offline_eval_report.py` 对比 160 条的判定分布，**分布不许变**。
4. B12/B13 在 vendored 引擎里，改动前先看 `docs/ENGINE_VENDOR_PLAN.md` 的"可改/不可改"边界。
