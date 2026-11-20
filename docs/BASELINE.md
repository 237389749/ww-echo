# BASELINE.md — 基线清单（改东西后按这里复跑）

> 目的：让"文档里的数字"能在**指定环境 + 指定提交**上重跑出来。
> 2026-10-29 的文档审核发现：基线数字散落在 README/CLAUDE/handoff/eval_rules 且各自漂移（122/130/135/156），
> 复现脚本又在仓库外（`.scratch/`）—— 这份清单把口径固定在一处。
> 数字与其守卫：`tests/test_doc_claims.py`（文档数字写错 → 测试红）。

## 0. 环境

| 项 | 值 | 说明 |
|---|---|---|
| OS | Windows 10/11 | 抓屏/键鼠依赖 Win32 |
| Python | **3.10+**（推荐 3.12；**3.13 / 3.14 已实测**） | **下界来自依赖，不是项目锁的**：`openvino 2026.0.0` 要 ≥3.10、`PySide6 6.12` 要 3.10~3.15；代码语法更宽松（145 个 `.py` 用 `ast.parse(feature_version=(3,8))` 全部可解析，无 tomllib/Self/StrEnum/ExceptionGroup）。曾经写的 "3.11+" 是误记：那是 **numpy 2.4**（opencv/openvino 的传递依赖）的 Requires-Python，3.10 上 pip 会选 numpy 2.2.x。3.14 实测口径：Python **3.14.4** + numpy 2.4.6 + opencv 4.14.0.94（venv `..\.venv314`）；3.13 于 2026-11-13 用全新 venv 复验（Python 3.13.16 + 同一套 requirements） |
| 依赖 | `pip install -r requirements.txt` | `opencv-python==4.14.0.94` / `onnxocr-ppocrv5==0.0.18` / `openvino==2026.0.0` / `pynput==1.8.2` / `pywin32==312` / `psutil==7.2.2` / `pycaw==20240210` / `PySide6-Fluent-Widgets==1.11.3`（**直接依赖全 `==`**，2026-11-18 按 3.13.16 锁定）；**传递依赖未锁**（numpy/onnxruntime/shiboken 由 pip 解析） |
| 3.10 可用性 | **静态核对通过（未跑运行）** | 2026-11-18 查 PyPI: 所有 `==` 的包在 Windows 上都有 cp310 或 abi3 的 win_amd64 wheel（pywin32 312 有 cp310、psutil 7.2.2 是 abi3、opencv 是 cp37-abi3、openvino 2026 声明 >=3.10）；真正的运行验证仍只在 3.13.16 做过 |
| 引擎 | `ww_engine/`（in-tree） | 不再有 site-packages 补丁；4 处 `[ww-echo patch]` 已合并进 vendored 代码 |
| 显示器/分辨率 | **任意窗口比例**（1024x768 起；`supported_resolution.ratio=None` 时按帧宽高线性映射） | 真机评估需要游戏在"背包声骸列表"界面；只有"全屏+黑边"才需显式设 `ratio='16:9'` |

> **本机当前状态（2026-11-20 复核）**：`requirements.txt` 已按钉死版本装进**系统 Python 3.13.16**
> （`python -m pip install -r requirements.txt`，**360** 项单测在该解释器上全绿、`import mainui` 通过），
> 因此 `python mainui.py` / `run.cmd`（无 `.venv` 时回落到 PATH 的 `python`）可直接跑。
> `%TEMP%\ww-echo-venv313` 是 2026-11-13 旧会话遗留的临时环境（约 1.1GB），**已不被引用，可删**。

自检：

```powershell
python -c "import ww_engine, cv2, numpy; print('ok')"   # 任一失败 = 环境不对，下面的基线都不用看
```

## 1. 基线（每次改动后复跑）

| # | 命令 | 期望输出 | 依赖 |
|---|---|---|---|
| B1 | `python -m unittest discover -s tests` | **360 项**（`Ran 360 tests` / `OK (skipped=2)`；无素材时个别用例 `skipTest`，总数不变） | 仅代码 |
| B2 | `python tools/offline_eval_report.py` | 入报告 **109 只**（满级 90 / 未满级 19）；判定分布 `达标 38 / 保留 35 / 建议重铸 0 / 建议强化 7 / 不建议强化 12 / 不合格 17`（粗分桶 `pass 38 / hold 35 / keep 0 / pending 7 / fail 29`）；**主属性数值可疑 0 条**；套装来源 `{icon:108, name:1}`。⚠ 旧的 `39/38/1/7/12/12` 是**听唤语义之愿权重调整前**的产物；**2026-11 的 Lv5/Lv10 首条判定改动后「建议强化/不建议强化」可能变化，需在素材机上重跑本表** | `logs/eval_debug/20260911_110817/`（**未入库**，见 §3） |
| B3 | `python tools/eval_icon_match.py` | **217/219**（99.1%）；s1 中位 ≈0.894；名字候选一致 196/211 | 同上 |
| B4 | `python tools/ui_shot.py`（可加 `--dark` / `--size 940x620` / `--eval`） | 离屏渲染 **7 页** PNG，无异常；940x620 下**无横向滚动**（组合穷举内容最小宽 493 / 套装配置 227，`hmax=0`）；`--eval` 把运行页切到评估态（可看到「精确模式（评估）」卡片） | 仅代码 |
| B5 | `python tools/echo_plan.py --list` | 默认取**最新评估产物 JSON**（本机 = `eval_report6.json`）→ **160 只 / 49 个名字**；COST `{1:66, 3:77, 4:17}`（满级 131）。旧的 109 只基线要显式给 `--dir logs/eval_debug/20260911_110817`（109 / 47 / `{1:55,3:35,4:19}`） | 本机评估产物（未入库），见 B7 |
| B6 | `python tools/echo_plan.py --list-profiles` | **4 个**预设：爱弥斯 / 绯雪 / 西格莉卡 / 仇远 | 仅 `assets/char_profiles.json` |
| B7 | `python tools/analysis/verify_eval_run.py eval_report6.json --log logs/ok-echo.log --check --expect 160` | 条数 **160** / 重复 0 / 回顶 0 / 缺 COST 0 / 假主属性 0 / 词条缺失 0 / `text=139(87%)` / `effect=0` / 失败 0；`结束原因: 到达0级尾部` | 本机 `eval_report6.json`（**未入库**，`.gitignore` 的 `eval_report*`） |

> **2026-11-20 晚起评估默认「图标优先」**（CHANGELOG 补记 72）：新报告的 `set_src` 以 `icon` 为主，
> 验收闸是 **`text+icon ≥85%`**（`--min-panel-pct`，旧名 `--min-text-pct` 仍可用）。
> B7 的 report6 是旧口径（text 139/87%），命令原样仍通过。

> **2026-11-13 通用共效 0.6→0.5**：只影响"通用/套装未映射"件的评分与判定；B2 的 109 只里
> 套装来源有 1 只 `default`（通用），其分数/判定可能变化，需在素材机重跑 B2 核对。
> 套装模板权重未动，B3/B5 不受影响。

参照提交：**「文档审核修正 + 去掉 Python 3.12 限制」那次提交**（2026-10-29；下表 B1~B6 的实测就在它上面，
`git log --oneline --grep "去掉 Python 3.12 限制"` 可取到哈希 —— 不在本文件内写死，避免 amend 后失效）。
历史锚点：`01ddb89`（2026-10-11，文档审核时的 HEAD —— 当时的 `39/38/1/7/12/12` 是听唤权重调整前的产物）。
**改了权重/判定/数据后，这些数字会变**：变了就同步改本表 + 相关文档（`eval_rules.md` §8、`CLAUDE.md`、`handoff.md`），并跑 B1 的文档守卫。

> **实测记录**：2026-10-29 晚在 Python 3.14.4（`..\.venv314`）上 **B1~B6 六条全跑过**：
> B1 `Ran 172 / OK (skipped=1)`、B2 见上表、B3 `217/219 (99.1%)`、B4 8 页、B5 `109 只 / 47 名 / {1:55,3:35,4:19}`、B6 4 个预设。
> 这些数字在此之前只有 3.12 的旧记录（"3.14 已实测"当时只做了静态核对 + `py_compile`）。
> **2026-11-13 补充（本机 Python 3.13.16 新 venv）**：`pip install -r requirements.txt` 一次成功
> （opencv 4.14.0.94 / numpy 2.4.6 / openvino 2026.0.0 / onnxocr 0.0.18 / PySide6 6.12 / qfluentwidgets 1.11.3），
> B1 `Ran 177 / OK (skipped=2)`（无素材，`TestRealDataset` 整类跳过）、B4 7 页、`ww_engine` 全模块导入 0 错误。
> 说明：引擎自持后不再依赖 ok-script 的 `Requires-Python`，Python 3.13 直接可跑。
> **同日接管审核**：新增 `tests/test_engine_task.py` 5 项（引擎任务层接线守卫，B1 → **182**）；
> 另用真实 onnxocr + 合成帧跑通 `task.ocr()`（两行中文 0.99 / 0.97），确认 OCR 主链路可用。
> **同日耦合 P2**：新增 `tests/test_engine_lazy.py` 2 项（根包惰性导入守卫，B1 → **184**）；
> `import ww_engine` 基线 **0.209 s**（5 次中位；其中 ≈131 ms 是 QtCore）—— 见 `docs/COUPLING.md` §0.3/§5。
> **同日第三阶段（外壳拆分）**：再 +2 项（engine 只有组合根可 import `ww_app_shell` / shell 不许 import engine 根包，
> B1 → **186**）；`import_coupling.py` 的 SCC 修掉假边后只剩 `rotypes` 4 模块 —— 见 `docs/COUPLING.md` §0.4。
> ⚠ 本机 `PySide6.QtCore` 单次 import 在 0.13~0.50 s 波动（`import sys` 恒 0），import 耗时请按“相对增量 + 成分”比较。

离线快速重放（不需要素材，只看当前权重下的判定）：

```powershell
python tools/offline_eval_report.py --from-json eval_report_20261011203423.json
```

## 2. 复现脚本索引

**已入库（`tools/analysis/`）**：

| 脚本 | 回答什么问题 | 产物 | 文档出处 |
|---|---|---|---|
| `b2_distribution.py` | B2 那份报告的六档分布 + 逐套装分解 | stdout | `eval_rules.md` §8、本表 B2 |
| `b2_replay_old_weights.py <提交>` | 文档里那版旧分布是哪套权重跑出来的 | stdout（覆盖 `eval_report.html`） | CHANGELOG 补记 21 证据① |
| `b2_replay_old_core_first.py` | `_core_first` 修正对这份数据到底有没有影响 | stdout（同上） | CHANGELOG 补记 21 证据② |
| `calculator_reconcile.py` | 与外部「声骸策略工坊」对账：档位/权重比例/A/B 完成度/锁成本/强化盈亏平衡 | stdout 或 `logs/analysis/*.md` | `docs/CALCULATOR_RECONCILIATION.md`、CHANGELOG 补记 23 |
| `import_coupling.py` | 底层耦合体检：分层矩阵/跨层违规/Qt 依赖/import 循环/耗时 | stdout 或 `logs/analysis/*.md` | `docs/COUPLING.md`、CHANGELOG 补记 25 |
| `p1_equiv_check.py` | 耦合 P1 的纯函数搬移有没有改口径：与 P1 前提交（默认 `3e698cf`）逐例对比 4 个函数 | stdout（不一致时退出码 1） | `docs/COUPLING.md` §0.2、CHANGELOG 补记 27 |
| `probe_scroll.py` | 只读几何报告（`--capture`）/ 实测滚轮位移曲线（`--scroll`，需管理员） | stdout + `%TEMP%/probe_scroll/*.png` | `docs/SESSION_2026-11-14.md` §2.8 |
| `probe_scroll_capture.py` | 连续抓帧 + 模板匹配真值：滚动动画多久停、px/格 到底多少 | stdout + `%TEMP%/scroll_seq/*.png` | `docs/SESSION_2026-11-18.md` §2.1 |
| `audit_sets.py <评估json>` | 一条命令核对：条数/重复/`set_src` 分布/多义但没定下来的清单 | stdout | `docs/SESSION_2026-11-18.md` §3 |
| `energy_weight_impact.py [评估json]` | **共效口径影响面**：`DEFAULT_WEIGHTS` 0.5 / 模板 0.6 / 听唤 0.5 / 隐世 1.2 各改一边会动哪些判定与 B 线（每个场景重跑 `evaluate_one`） | stdout + `logs/analysis/energy_weight_impact.md` | `docs/SESSION_2026-11-20.md` §11-2、CHANGELOG 补记 69 |
| `icon_accuracy_report.py [评估json] [--panels 目录]` | **面板图标回归**：139 张 `_top.png` 的 top-1 / 置信闸覆盖与精度 / 名字候选约束 / 环色 / 二值形状 / 按等级 / 面板下滑时间账（真值 = 报告里的 `text` 套装） | stdout + `logs/analysis/icon_accuracy_report6.md` | `docs/SESSION_2026-11-20.md` §3、CHANGELOG 补记 71 |
| `panel_scroll_time.py [--log] [--panels]` | **面板下滑的时间账**：用日志 `[评估#N]` 时间差拟合"每条固定开销 + 每步耗时"，算出下滑占整轮多少 | stdout + `logs/analysis/panel_scroll_time.md` | 同上 |
| `verify_eval_run.py <评估json> [--log]` | **真机验收一条命令**（2026-11-20 口径）：条数 **160±2**（`--expect` 必须显式给，缺省不判条数）/ 完全重复 0 / `set_src=text` **≥85%** / `effect` 0 / **面板回顶失败 0** / **缺 COST 0** / **词条缺失 0** / **无 `持有数量` 假主属性**，外加每屏重叠与滚动健康（无重叠守卫、受阻、过滚）；`--check` 有问题退出码 1（旧报告没有 `cost` 字段时该项降级 SKIP） | stdout | `docs/SESSION_2026-11-20.md` §0、`docs/BASELINE.md` §2 |
| `replay_panel_scroll.py [目录]` | 评估时存的 `logs/panel_debug/<ts>/` → 逐只重放「找套装」：线上结论 vs 离线（第几步命中）、回顶是否成功、长图尺寸；`--stitch` 补长图、`--steps` 每步 OCR、`--check` 有漏读/回顶失败退出码 1 | stdout（`logs/panel_debug/` 是输入，只读） | CHANGELOG 补记 48；`CLAUDE.md` 评估遍历·面板数据集 |
| `check_set_panel.py <面板截图…>` | **不玩游戏**，拿截图跑真 OCR，验证 `match_set_text`/`match_set_effect` | stdout | `docs/SESSION_2026-11-18.md` §3 |

历史脚本原本都在工作区根 `.scratch/`（**不在版本库**，见 §3），它们支撑了文档里的这些结论：

| 脚本 | 回答什么问题 | 产物 | 文档出处 |
|---|---|---|---|
| `margins.py` | 当前面板下每条词条 +1 点的边际伤害（用于定套装权重） | `margins.txt` | `CLAUDE.md` 组合穷举·套装权重 |
| `derive_weights.py` | 按边际反推权重（后被否决） | `derived_weights.txt` | 同上·"权重不是瓶颈" |
| `weight_agreement.py` | 组合级 + 件级秩相关（手调 vs 推导） | `weight_agreement.txt` | 同上（0.380 vs 0.373、0.559 vs 0.523） |
| `generic_weights.py` | 四角色 × 三套权重的 ρ（通用权重该不该改） | `generic_weights.txt` | `CLAUDE.md:95-98`（含仇远 −0.13） |
| `score_agreement.py` | 评分和/有效分与伤害排序的秩相关、Top-K 重合、第 540 名 | `score_agreement.txt` | `CLAUDE.md:151-156` |
| `score_vs_damage.py` | 同上另一版（指定专伤后的口径） | `score_vs_damage.txt` | 同上（注意：第 1122 名是这一版） |
| `why_pass.py` | "只有 3 条有效词条为什么也能达标" | `why_pass.txt` | `eval_rules.md` §7 / CHANGELOG 补记 13 |
| `margins`/`measure_table2.py` | 结果表列宽实测 | — | `CLAUDE.md` 排名表列宽 |
| `plan_page_shot.py` / `sigelika_page.py` | "已导入+已排名"的页面走查图 | `plan_page_*.png` | `CLAUDE.md` 改表后必跑 |
| `scan_icons.py` / `extract_icons.py` / `swap_icons.py` | 从客户端 pak 抽套装图标（C# 程序已入库到 `tools/icon_export/`） | `assets/echo_icons/` | `CLAUDE.md` 官方静态数据层 |

> 迁移约定：**新写的复现脚本放 `tools/analysis/`**（入库），文件头写"输入 → 输出 → 支撑哪条结论"。
> 老脚本暂留 `.scratch/`，需要重跑时从这里复制并改成相对路径。

## 3. 已知不可复现项（干净克隆上会缺的东西）

| 缺什么 | 为什么 | 影响 |
|---|---|---|
| `logs/eval_debug/20260911_110817/`（1097 个文件） | `.gitignore: logs/` | B2/B3/B5 无法跑；相关用例会 `skipTest` |
| `eval_report_*.json` / `eval_report.html` | `.gitignore`（评估产物） | 无法复核 §8 的判定分布；`--from-json` 没输入 |
| `.scratch/` 整个目录 | 在仓库**父目录**，`git ls-files` 为 0 | §2 的脚本全部缺失，文档里的 `.scratch/...` 路径悬空 |
| `ww_engine/` 引擎源码 | 已入库，不再是 site-packages | 干净克隆直接可跑；不再需要重打补丁 |

> 环境坑（本机写明的那个受限沙箱）：`tempfile.gettempdir()` 会落到**仓库根**（`%TEMP%` 探测不通过），
> 于是每次跑 B1 都会在根目录留一个 `tmpXXXX/`（`tests/test_echo_inventory.py` 的 `mkdtemp`）—— **无害，别提交**；
> 正常机器上它落在 `%TEMP%`。同理 `tools/ui_shot.py` 的默认输出是仓库内的 `.scratch/ui_shots/`（也不入库）。

**想让它们可复现**：① 提交一份小型 fixture（如 20 只的评估 JSON + 2 张图标），把 B2/B5 的冒烟测试改成用它；
② 把 `.scratch` 的脚本搬进 `tools/analysis/`；③ 补丁已随引擎 vendored 进 `ww_engine/`（阶段三十一，已完成）。
