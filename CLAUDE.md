# CLAUDE.md — ww-echo 开发手册

鸣潮(云游戏/本地)声骸强化 + 评估工具。基于 ok-script(截图/OCR/模板匹配/键鼠后端) + 自建 PySide6 UI。
**本手册面向后续开发(含 AI 协作者)。演进历史与改动原因见 CHANGELOG.md, 使用说明见 README.md。**

## 工作准则(项目级)

- 动手前陈述假设与取舍; 有歧义先问, 不静默选
- 最小改动解决当前问题; 只改与请求相关的行; 不超前抽象
- 改出孤儿引用(import/变量/函数)须清理, 但不动预存在的死代码
- 本机 ok-script 在 site-packages 有 `[ww-echo patch]` 补丁, **改动/升级前先 grep 定位**, 详见下
- 坐标、OCR 区、滚动量等常量集中在 `EnhanceEchoTask.evaluate_only` 顶部注释, 调参先看那里
- 目标驱动: 把请求转成可验证目标(如"修 bug"→"写复现测试再让它过"), 多步任务列出"步骤→验证"清单, 完成前以最相关测试/命令验证

## 项目结构

```
mainui.py                 唯一入口(PySide6); 启动先按 QSettings run_mode 调 apply_run_mode 再 OK(config)
config.py                 全套 ok-script 配置 + MODE_LOCAL/MODE_CLOUD + apply_run_mode()
ui/                       7 tab; settings_tab 含"运行模式"(本地/云游戏)开关, 重启生效
src/echo_stats.py         词条档位表 _TIERS + snap_to_tier/get_mean/is_stat_match
src/echo_set_templates.py 31 套装 JSON 模板(词条/权重)
src/task/EnhanceEchoTask.py  强化(run) + 评估(evaluate_only v2 遍历, 核心)
src/task/BaseEchoTask.py  轻量基类(click 覆写/语言检测)
assets/echo_set_templates.json 套装配置存档
```

## 运行模式(local / cloud)

- 切换写 QSettings("OK-Echo","OK-Echo") 的 `run_mode`, **重启生效**(mainui 在 OK() 初始化前 apply)
- **local**: `exe=Client-Win64-Shipping.exe`+`hwnd_class=UnrealWindow` 自动匹配本地客户端; PostMessage 可后台运行
- **cloud**(云游戏 = 浏览器/云客户端窗口, 如 Firefox):
  - `windows.title=re.compile('鸣潮')` → ok-script `find_hwnd` 按正则自动锁定标题含"鸣潮"的窗口, **无需手动选窗**
  - interaction=Pynput(前台真实键鼠), capture 锁定 `BitBlt_RenderFull`, `supported_resolution.ratio=None` 跳过 16:9 校验
  - 云游戏本地无 UnrealWindow 可后台投递 → **必须前台**, 任务运行中不要最小化游戏

## ok-script 补丁 — 升级 ok-script 会丢失, 需重打

ok-script(site-packages) 4 处(4 个文件), 本项目内另 1 处。全部标注 `[ww-echo ... patch]`:

| 文件 | 改动 | 为什么 |
|------|------|--------|
| `ok/gui/StartController.py` | `_auto_bring_to_front`(init=False; do_start 且 task 非 None 时置 True); `_wait_until_device_ready` 每轮按标志 `bring_to_front()`(含最小化恢复) | 点"开始"后自动把游戏窗口切前台启动任务; 纯启动不抢前台 |
| `ok/device/capture_methods/hwnd_window.py` | `visible = not win32gui.IsIconic(hwnd)` 替代 `is_foreground()` | 后台/被遮挡窗口(BitBlt_RenderFull 可抓)不再判不可用; visible=False 只在真最小化出现 |
| `ok/device/interaction_methods/pynput.py` | `should_capture()→True`; `clickable()` 保持纯 is_foreground; 新增 `_ensure_clickable()` | 任务主循环不再被前台门控(切走不再卡死); 真正 click/send_key/scroll 动作前自动拉前窗口 |
| `ok/util/window.py` | `find_hwnd` 开头过滤空 exe 项: `exe_names = [e for e in (exe_names or []) if e]` | 云模式 `selected_exe=''` 时, 空 exe 会让**所有**窗口在 exe 匹配处被判不匹配 → 找不到"鸣潮"窗口 |
| `ui/run_tab.py`(本项目, 非 site-packages) | 评估分支起线程前也 `bring_to_front()` | 评估模式与强化一致地切前台 |

## 屏幕坐标基线(1920x1200 帧; 归一化 = px/1920, px/1200)

| 元素 | 归一化区 | 备注 |
|------|---------|------|
| 声骸网格 | (0.10,0.15)-(0.72,0.92) | 每行 6 格; 列距≈176px, 行距≈212px(1920x1200 参考); `+xx` 角标在格右下 |
| 右侧详情面板 | (0.66,0.10)-(0.995,0.635) | 归一化 y 参考: 名字≈0.10/COST≈0.21/主属性≈0.37,0.42/词条≈0.45..0.61(第5条); "声骸技能"行(≈0.62)由 read_detail 按行过滤; **"前 2 行=主属性"是相对行序判断, 不依赖帧高**; 截图同区 (0.665,0.07)-(0.995,0.65) |
| 左上声骸计数 | (0.02,0.02)-(0.25,0.09) | `声骸145/3000` → 上限做步数限制 |
| 滚动热区 | (0.52,0.5) 常用 | 鸣潮列表滚动有热区(光标需网格中右部); 1920x1200 参考 ≈8px/notch |

## 词条过滤规则(关键, 勿回退成区间判断)

详情 OCR 出的属性行 = 主属性区 + 真词条, 按 y 序排列, **前 2 行固定为主属性**, 直接排除(即使固定值恰好命中档位, 如 主属性 生命=510 / 防御=50)。
判定词条: 排除前 2 行后, `echo_stats.is_stat_match(name, value)` = 归一化名在 `_TIERS` 且数值 **≈ 档位集合中某档**(容差 0.8)。
区间判断会误收主属性; 必须离散匹配。词条最多 5 条。

## 评估遍历 v2 现状与约束

- 前置: 游戏已在**背包声骸列表界面**(无需预选)
- 流程: 网格 OCR `+xx` 角标 → 聚行 → 6 列基准(跨屏记忆 `col_centers`)补全缺列防漏 → 逐格点选 → 右侧详情 OCR → 档位过滤词条 → 评分/截图/记录
- **评估按声骸名自动映射套装**: 套装模板含 `_echoes: {4c:[...], 3c:[...], 1c:[...]}`(声骸清单, 数据来自 wuther.in 页面图标→套装对照, 见下); 评估时 `get_set_by_echo(声骸名)` → 用该套装的权重/键/首核, **未录入回退"通用"**(如无图标的 冰盈舞者/共鸣回响类)。一个声骸可属多套装 → 反向索引取声明顺序首个
- 套装语境(权重/键/首核/声骸清单)供评估自动映射 + 强化模式使用; run_tab 评估仍隐藏套装下拉(靠映射), 未映射时用通用
- **多套装声骸归属**: `get_sets_by_echo(名)` 返回候选套装列表(119 个声骸属多套); `get_set_by_echo(名, prefer=config套装)` — prefer 在候选内则尊重它, 否则取模板顺序首个; 尚未做"按图标识别"的游戏侧读取(需游戏 UI 提供套装图标); 套装模板含 `_icon`(如 Cloud/Ice)供核对与将来扩展
- **数据来源/工具备注**: 声骸清单由 wuther.in 页面(用户浏览器保存)解析——条目左上角 `IconElementAttri*.webp` ↔ 筛选按钮"图标+套装名"; 解析脚本 `tools/parse_wutherin_echoes.py <页面.html>`(只覆盖解析到数据的套装, **保留手补值**, 自动补 `_icon`/新增套, 生成 `echoes_check.md`); **kurobbs/wuther.in 均不可脚本爬取**(前者要令牌, 后者 robots.txt Disallow AI 爬虫); 当前 34 套(31 原 + 3 新), 清单以 `1.txt`(用户手工整理) 为准——已移除错误前缀「异相」(正确为「梦魇」)、剔除误录角色/多余声骸, `剪心辑梦之影` 等已补全
- 空格/未切换格**跳过继续**(不提前滚屏防漏真实格); 本屏无新内容才滚动 15 notches; 连续 3 次滚动无新格兜底
- **步数限定(read_count)**: 左上 `声骸N/3000` 取 **N**(总数或滚动位置, 非 3000 容量) 作上限, `handled >= N` 终止; **每屏动态重读并 max 跟随**(N 若为滚动位置会随滚动增大, 不误截断; 防 OCR 抖动回退)
- **0级声骸(0词条)跳过不记录、不终止**: 无评估价值, 不入报告; 置 processed_any 继续滚动推进; 0 级角标是 `+0` 也能被网格识别; 列表真到底 = 滚动后网格区**连续 2 次扫描为空**(empty_scan); 首屏即空且零记录才 raise 防呆
- 去重: `seen_sigs`(set[str]) 保存**声骸名 + 全部属性行档位值**(`dedup_key`, 档位值离散不受 OCR 抖动影响)的签名, 命中即跳过——防滚动重叠(15 notches≈120px < 行距 213px, 每屏与上屏重叠~1行)导致的重复记录; `last_sig`(全量文本)只判"点选未切换", **每次滚屏后重置**; 同名同属性两只会被合并, 属可接受近似
- **词条名容错(`_normalize_stat`)**: 三级处理①**逐字白名单**(`_STAT_CHARS`=标准词条名+主属性名单字并集, 图标/杂字直接剥离; 清洗后 <2 字返回原文不猜)②**精确子串链**(清洗后即子串匹配, 前缀污染 `艾攻击`→攻击%)③**最长公共子串回退**(删字后仍缺字如 `共鸣技伤害加成`→"伤害加成"4字归位; ≥3字直接归位平手按优先级, =2字仅唯一候选, 多候选不猜)
- 截图 = 右侧详情面板完整区(0.665,0.07)-(0.995,0.65), 非网格左上角
- **debug 数据集**(`evaluate_only` 内 `if True:` 开关): 每格存 全屏PNG + ROI框叠图(红=detail/绿=grid/蓝=count) + 三个区域裁剪图, 每次 OCR 的文本/坐标/置信度记入 `ocr_text.txt`; 输出 `logs/eval_debug/<时间戳>/`, 独立于报告临时目录不随报告删除(200声骸约数百MB~1GB); 供离线核对坐标常量与 OCR 输入, 无需重开云游戏
- **评分公式**(`DEFAULT_WEIGHTS` + `compute_weighted_score`): 条分 = 档位值÷均值 ×10×权重(每条上限自然 12.5, 无效=0); 通用权重: 暴击1.0 爆伤0.9 **百分比三系(攻/生/防)0.85** 共效0.7 专伤(普攻/重击/共技/共解)0.6 **固定三系(攻/生/防)0.5**; 套装模板权重已折算同尺度(词条按新表取值, 词条选择保留套装差异)
- 评估/渐进判定(`judge_echo` 公共): **Lv5/Lv10 = 结构判定——存在"首条核心词条"(`_core_first`, 缺省=全部有效词条; 通用 weight>0)即过, 不限分**; Lv15/20/25 = 总分 ≥ 锚线 `_tier_threshold` = 有效词条"平均档加权分"(10×权重)中最低 (tier-1) 条之和(通用 6 种适配集: Lv15=11 / Lv20=18 / Lv25=26.5); **keep(满级不达标且有效条数≥2且score≥18) → 评估报告标"建议保留重铸", 强化不豁免**
- **套装模板校验**: `_core_first`(可选, 首条核心词条) + **键数<5 → 评估/强化启动硬拒**(强化后必有 5 词条)
- 报告(`_build_eval_html`): 名称独立列 + 得分区间/判定多选/名称包含筛选(原生 JS) + 词条按档位 ratio 着色(roll-4~0)
- **已知缺陷(原版 ok-ww 同款)**: 强化 `run()` 无"切下一只"推进, 依赖丢弃后游戏自动前移; 评估遍历在网格布局/字体变化时坐标常量需复核

## 待办(与 README TODO 同步)

- 满级保留/重铸机制: **已实现(评估侧)**——`judge_echo` 返回 keep(满级不达标 且 有效条数≥2 且 score≥18); 评估报告第四档"建议保留重铸"(html keep 蓝档); 强化流程不豁免(keep 仍丢弃)。**按用户决定不做重铸动作**(游戏内重铸流程不实现), "保留"即建议锁定, 由用户手动处理
- 首条核心 + 键数硬拒: **已实现**——套装模板 `_core_first`(缺省=全部有效词条, 评估/强化通用); 套装键数<5 评估/强化启动硬拒(辅助/奶套待用户逐个固化模板, 当前默认跑通用)
- 副C/奶双逻辑评价: **已解决**——由套装模板"有效词条+权重"方案覆盖(奶套预设共效/生命/固定攻权重、双暴降权)

## 已知坑

- `pynput` 是必需依赖(点击层运行时才 import, 缺库表现为"点击无反应")— 勿从 requirements 移除
- WGC 抓云游戏/浏览器窗口常黑屏 → cloud 锁定 BitBlt_RenderFull
- 200% 高 DPI 下固定 860x640 逻辑窗口会物理化超屏 → 初始 700x520 + 工作区 clamp/居中(`ui/main_window.py`)
- 云游戏 16:10 画面已跳过 16:9 校验; 若云平台带黑边渲染, UI 归一化位置会偏移(黑边校准未做)
