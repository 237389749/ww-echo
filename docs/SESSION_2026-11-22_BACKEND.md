# SESSION 2026-11-22（后端）— 一次 code review 换来三批修复：34 项、411 → 464

> 承接 `docs/SESSION_2026-11-20.md`（真机 report6 八项全绿）之后的那轮**界面**修复
> （[`docs/SESSION_2026-11-22.md`](SESSION_2026-11-22.md)，B1~B4）。用户这轮要求"用 code-review
> 审后端" → 审出 **🔴4 / 🟡13 / 🟢17** → 分三批全修。
>
> 提交：`24ea524` → **`dc59879`（A 批）/ `daa273b`（B 批）/ `5ad3c0a`（C 批）**，已推送
> `origin/engine/vendor`，本地与远端 **0/0**。
> 状态：**单测 411 → 464 全绿**、`ui_probe --strict` 5/5、离线重放 160 条**分数变化 0.000**、
> `verify_eval_run --check` `[ok]`、`echo_plan --list` 仍 160 只 / 49 名字。
>
> **未验证**：真机（截图/GDI 句柄/强化流转），见 §6。

---

## 0. 一页结论

| 现象（改前） | 根因 | 改动 |
|---|---|---|
| 报告里 160 张截图**全是碎图**，日志还说"画面已存" | 评估链用裸 `cv2.imwrite`，它对**非 ASCII 路径返回 False 且不抛**（中文用户名 → `%TEMP%` 在中文目录） | 6 处落盘改 `echo_panel_shot.imwrite_unicode`；`_save_fail_frame` **检查返回值** |
| 一次 BOM = 用户**全部角色预设被覆盖销毁** | `load_all` 把"解析失败"当成"没有预设"，而 `upsert` 是"读全量→改一条→写全量" | 写路径改严格读（坏文件**拒绝写**）+ `tmp + os.replace` 原子写 |
| CLI `--profile` 复现的是**另一套门槛** | 载入块只搬 bare/补正/专伤/配装，门槛一律读 argparse 默认；`to_request_kwargs` **零调用** | `char_profiles.apply_thresholds`（唯一翻译层 + 显式参数优先） |
| 关程序时**整条清理链被跳过**，评估临时目录残留 | `sleep()/frame` 的 `sys.exit(0)` 是 `BaseException`，`execute()` 的 `except Exception` 抓不到 | `execute()` 改 `try/finally: destroy()`；评估侧 `except BaseException` |
| 「主属性数值可疑」**永远不报警** | 验收工具读 `main_prop_check`/`status` —— 这两个字段**不存在**（真实是 `main_values_check` 的 `ok`） | 改读真字段；`effect > 0` 一律 WARN（不判失败） |
| GBK 守卫**看不见**两个入库文件 | 它们带 BOM → `ast.parse` 抛 SyntaxError → `except SyntaxError: continue` 静默跳过 | 剥 BOM + 守卫改读 `utf-8-sig` + 解析失败改成 fail |
| 点「开始强化」**立刻**打「结束」、按钮放开 | `start()` 只是 `handler.post(...)`，调用方当同步用 | `start(on_done=ok)` + `communicate.task_done`（三条结束路径都发） |
| `"True"` 存进配置 → 下次启动变 `False` 且覆写 | `verify_config` 类型不匹配就**静默回默认** | `_coerce`（`"True"`/`"3"`/`3.0` 都转，转不了才回默认并告警）；坏文件先存 `.bad` |

| 批次 | 级别 | 条数 | 单测 | 主题 |
|---|---|---|---|---|
| **A** | 🔴 必须修 | 4 | 411 → 423（+12） | 静默失败：写图 / 读预设 / 算门槛 / 清资源 |
| **B** | 🟡 应该修 | 13 | 423 → 455（+32） | **验收/契约在撒谎** |
| **C** | 🟢 可选 | 17 | 455 → 464（+9） | 卫生：副本 / JSON 合法性 / 行序配对 / 绝对路径… |

---

## 1. 最值得记的一条：这批问题的共同形状是「静默失败」

34 条里最有价值的一类，不是"算错了"，而是**看起来成功了**：

- `cv2.imwrite(中文路径)` → 返回 `False`，**不抛**；报告里的图是碎图，日志说"已存"。
- `load_all(坏文件)` → 返回 `{}`，不抛；下一次保存把其余角色全抹掉。
- `getattr(a, "energy_min", 120.0)` → 永远拿到 argparse 默认值；用户以为"复现了"。
- `except Exception` 漏掉 `SystemExit` → 清理链整段跳过，`%TEMP%` 里留几百 MB。
- `verify_eval_run` 读一个不存在的字段 → 那项检查**恒为 0**，永远绿灯。

**判据因此变成一句话**：*改了之后，失败时会不会有人喊？* 不会 = 还没修完。

但"静默"也要分级 —— 这两处刻意**没有**变成硬失败：

| 场景 | 处理 | 为什么 |
|---|---|---|
| 未知套装名（模板里没有） | 仍按 B=0 处理，但**告警一次** | 评估中途抛错会把整轮结果丢掉；喊一次足够定位 |
| `set_src=effect`（已停用的弱信号） | WARN 但**不判失败** | 旧报告兼容；回潮要能看见，但不该让历史报告复算变红 |

反过来说，**B7 那种"测试断言自己抄的公式"是最坏的静默**：它让"有守卫"变成一句空话。

---

## 2. 三批做了什么（细节见 CHANGELOG 补记 78/79/80）

### A 批 — 4 个 🔴（`dc59879`，411 → 423）
写图（6 处落盘 + 离线工具写/读 + 调试页）、预设读写（严格读 + 原子写）、CLI 门槛（`apply_thresholds`）、
退出清理（`try/finally` + `BaseException`）。**刻意没做**：不把 `sys.exit(0)` 换成 `FinishedException`
—— 它继承 `Exception`，沿途十几处 `except Exception` 会把它吞掉，反而不停。

### B 批 — 13 个 🟡（`daa273b`，423 → 455）
- 验收类 4 条：死字段、`effect` 无闸门、BOM 让守卫失明、`test_set_lines` 自证。
- 错误处理 2 条：模板校验不再崩程序（`{"暴击":"高"}` 只是过滤掉）；CLI 五种坏输入统一成一行 `SystemExit`
  （套装名带 difflib 建议）。
- 数据/渲染 2 条：报告 HTML 全面 `_esc()`；生成器不再把文本键当声骸名。
- 生命周期 2 条：**先存数据、再拷截图、最后 HTML**；`on_done` 回调 + `task_done`。
- 引擎 2 条：`Config` coerce + 原子写；`BitBltCaptureMethod.close()` + `prevent_sleeping` 的 `finally`。

### C 批 — 17 个 🟢（`5ad3c0a`，455 → 464）
只有三项动了行为：**C6** `_pair_props` 数量相等时**按行序**配对（原来最近邻贪心会被上一行抢走值）、
**C17** 预设记 `specialty_src: explicit|template`（模板推断的专伤换套装后不钉死）、
**C15** `run()` 有界（强化 ≤12 轮、连续满级跳过 ≤20 只）。
其余是副本/`Infinity`/缓存指纹/`open` 加 `with`/`--top`/备份顺序/`_source` 去绝对路径等。

---

## 3. 新增的"可量测"验收

| 命令 | 期望 | 能抓到什么 |
|---|---|---|
| `python -m unittest discover -s tests` | **464 项** OK (skipped=2) | 其中 A/B/C 新增 53 项（见 §5） |
| `python tools/ui_probe.py --strict` | 5/5 | 界面五缺陷（本轮只动了 debug_tab 的截图落盘） |
| `python tools/offline_eval_report.py --from-json eval_report6.json` | 160 条 / **分数变化 0.000** | 判定链没被这批改动带偏 |
| `python tools/analysis/verify_eval_run.py … --check --expect 160` | `[ok]` | 真机验收口径（含新读的 `main_values_check`） |
| `python tools/echo_plan.py --inventory eval_report6.json --list` | 160 只 / 49 名字 | 库存导入未被 C 批影响 |

**两条"变异检查"**（比"跑绿了"更有说服力）：

1. 把 `_legacy_threshold` 换成常数 `lambda n, t: 17.5` → `test_set_lines` **必须红**（B7 修好了才红）。
2. 在任意 `print` 里写 `⚠` → `test_gbk_output` **必须红**（B6 修好后它才看得见 BOM 文件里的字符）。

---

## 4. 踩过的坑（下次别再踩）

1. **守卫改严之后，第一件事是抓到了改它的人**：B6 把 `except SyntaxError: continue` 改成 fail，测试立刻报出
   我刚写的 `print('... 报告里有 ⚠ 数值可疑')` —— `⚠` 不在 GBK 里。守卫是有用的，只是以前它看不到那两份文件。
2. **PowerShell here-string 里反引号是转义符**：用 `@"..."@` 传 Python 脚本时，脚本里的 `` ` `` 被吃掉，
   `str.replace` 静默未命中 → BASELINE 的 B1 行停在 423 而第 20 行已经是 455（自相矛盾）。
   **写完后必须 grep 复核**；或改用 `@'...'@` + `[IO.File]::WriteAllText`（反引号原样保留）。
3. **`Set-Content -Encoding utf8` 会写 BOM**：提交标题前面多了 U+FEFF（`git log` 里看得见）。
   用 `git commit --amend -F <无 BOM 的文件>` 修掉；写提交消息统一用 `[IO.File]::WriteAllText`。
4. **"探针脚本自己也会错"**：`_coerce` 探针忘了 import `_MISSING`、`object.__new__(QObject 子类)` 直接 TypeError
   （StartController 测试要构造真 `Handler`，而且要传 `ExitEvent` 不是 `threading.Event`）。**别把探针输出当结论，先看探针对不对**。
5. **编辑工具改写文件会把 CRLF 变 LF**：`git diff` 仍是 25 行（`core.autocrlf=true` 归一化），但工作区行尾与新鲜
   checkout 不同；不影响功能，别为此折腾。
6. **测试断言自己抄的公式 = 没断言**：`test_set_lines` 原来断言 `_b_line(...)`（测试自己写的），把实现换成常数照样绿（B7 实测）。
   写"文档数字/口径"类断言时，**必须调实现本身**。

---

## 5. 文档落点

| 文档 | 本轮加了什么 |
|---|---|
| `docs/BACKEND_REVIEW_2026-11-22.md` | 审查全文（🔴4/🟡13/🟢17 + 每条的复现命令/修法/验收）+ §7.4/7.5/7.6 三批落地记录 + §8 未验证 |
| `CHANGELOG.md` | 补记 **78**（A 批）/ **79**（B 批）/ **80**（C 批）：每项现象→根因→改法→验收数字 |
| `CLAUDE.md` | 「后端 A 批修复」「后端 B 批修复」两节，全部标 **勿回退**；C 批一句摘要 + 指针 |
| `docs/BASELINE.md` | B1 = **464**；`test_backend_guards` / `test_char_profiles` 新增项的说明；`verify_eval_run` 行改成 text+icon 口径 |
| `handoff.md` | 顶部三批状态 + 后端审查文档入口 |
| `README.md` / `docs/UI_FIX_HANDOFF.md` | 项数同步（411 → 464 的连锁） |
| 新增测试 | `test_backend_guards`(7) / `test_char_profiles`(+6) / `test_plan_cli`(10) / `test_engine_config`(8) / `test_start_controller`(4) / `test_gen_echo_data`(4) / `test_verify_eval_run`(+3) / `test_echo_set_templates`(+3) / `test_report_layout`(+2) |

---

## 6. 未验证 / 下一棒

**只能真机验的（本环境没有游戏窗口，也没有管理员权限）**

1. **A1**：中文用户名下评估一轮 → `eval_screenshots/` 里是否真有 160 张图（本机只能用 `%TEMP%` 造中文目录模拟）。
2. **B2**：点「开始强化」→ 日志应显示"已交给执行器, 运行中…"，**不再**立刻打「结束」；
   正常结束/用户停止/异常中止三条路都要让按钮复位。
3. **B13 / C13 / C14**：切 capture（BitBlt↔WGC）前后看 GDI 句柄数；`_CreateMutex` 的单实例保护；`ctypes.wintypes` 显式导入。
4. **C6**：真实面板上配对是否仍对（数量相等时按行序）。

**engine-review 里要真机才能验的三条**（未做，理由写在审查文档 §7.6）

1. D3D `create_device()` 覆盖前不 Release（设备重置路径会泄 device + context）。
2. `overlay.ui_dict` 从未被写入 → 调试页"显示检测框"永远画不出框。
3. `handler.post(skip_if_running=True)` 会**丢弃**启动请求（设备刷新期间改设置 → "设置没生效"）。

**其他**

- `assets/gamedata/echo_data.json` 的 `_source` 还是旧格式（含 `C:\Users\root\...`）；生成器已改，
  **下次重新生成**才会变成 `BinData` / `zh-Hans`。
- 合并 `main` 的前提仍是**真机验收**（`engine/vendor` 现在领先 `main` 4 个提交）。

---

## 7. rep7 首次真机（2026-11-23 补记）

用户在 11-23 晚跑出 `eval_report7.json`（139 条 / 6 屏 / **8.2 分钟**），验收脚本一跑就报
**`[主属性数值] 2 条不在官方网格上`** —— 这是 B 批（B4）把字段名修对后**第一次真的报警**，
而它抓到的是我在 C 批（C6）里引入的**回归**。

**#136/#137 的取证链**：截图（`eval_screenshots/eval_136_pending_13.7.png`）→ 日志（`属性行7`）→ JSON。
截图真相是 `冷凝伤害加成 25.2% / 攻击 84 / 攻击 8.6% / 暴击 6.3% / 生命 8.6% / 普攻 9.4%`，
记录成了 `冷凝 3.0 / 攻击 25.2 / 暴击 8.6 / 生命 6.3` —— **整列右移一格**。
根因：+20/4 词条时**技能描述行被挤进 detail 区**（多一个名），`COST 3` 被拆成两个框、裸 `3` 当成值
（多一个值），名/值**凑巧数量相等** → C6 的 "zip" 分支把两列一起平移。

**修法**：`_pair_props` 回退贪心（噪声值落到尾部噪声行）+ `read_detail` 剔掉表头噪声值（y 在第一行属性名之上）
+ 一条**用 rep7 真实几何**的回归用例。单测 464 → 465。

**rep7 其余验收**：重复/回顶失败/缺 COST/假主属性/词条缺失 **全 0**；`effect` **0 条**（弱信号没回潮）；
text+icon **84%**（门槛 85%，差 1 点 → WARN）；判定 `达标 54 / 保留 60 / 不合格 20 / 建议重铸 1 / 建议强化 4`；
`prospect` 4 条 == 建议强化 4、`reforge` 1 条 == 建议重铸 1（内部一致）；截图 **139/139 全在**。

**唯一没人看过的**：13 条 `hue` 判定（列表见 CHANGELOG 补记 81），其中 #113/#114 是"同名不同套"，
符合既有认知，但环色是最后的弱信号，建议人工抽查。
