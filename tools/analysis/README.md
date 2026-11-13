# tools/analysis — 复现脚本（入库区）

> 这里放**支撑文档结论**的分析脚本：每个脚本必须能回答"文档里的某个数字是怎么来的"。
> 历史脚本原本散在工作区根 `.scratch/`（**不在版本库**，克隆后不存在），本目录是它们的正式归宿。

## 约定

1. **文件头三段**：`输入`（哪份数据/产物）→ `输出`（打印什么/写哪个文件）→ `支撑结论`（对应文档的哪一句）。
2. **路径只用相对仓库根**（`Path(__file__).resolve().parents[2]`），不要写死 `C:\Users\...`。
3. **只读**：分析脚本不改 `assets/`、不改评估产物；要落盘就写到 `logs/analysis/`（已 gitignore）。
4. 依赖：`src/echo_panel|combos|inventory|stats` 的脚本需要 `requirements.txt` 的环境（ww_engine）；
   纯算术/JSON 的脚本只需标准库。`calculator_reconcile.py` 另需参考工程目录（缺省
   `ww-echo-policy-calculator-main/`，不在本仓库，缺失时打印 skip）。
5. 结论写进文档时**同时**更新 `docs/BASELINE.md` 的「复现脚本索引」，并在 `tests/test_doc_claims.py` 里加断言（若可机检）。

## 已入库脚本

| 脚本 | 输入 → 输出 | 支撑哪条结论 |
|---|---|---|
| `b2_distribution.py` | `eval_report.html` → stdout 六档合计 + 逐套装六档表 | `eval_rules.md` §8 的两张表、`docs/BASELINE.md` B2 |
| `b2_replay_old_weights.py <提交>` | 用该提交的某个套装权重重跑 B2（覆盖 `eval_report.html`） | CHANGELOG 补记 21 证据①：`726db9c~1` 的听唤权重复现旧分布 `39/38/1/7/24` |
| `b2_replay_old_core_first.py` | 换回旧 `_core_first` 兜底（全部键）重跑 B2 | CHANGELOG 补记 21 证据②：这条修正对 109 只数据**零影响** |
| `calculator_reconcile.py` | 参考工程 `data/echo-data.json` + `apps/ocr/EchoOCRTask.py` + 本项目权重/档位 → Markdown（档位校验、满档权重比例、A/B 完成度、锁成本、强化盈亏平衡） | `docs/CALCULATOR_RECONCILIATION.md` 全部数字；CHANGELOG 补记 23 |
| `import_coupling.py` | 全仓 `.py` 的 import 图（stdlib，不导入项目）→ 分层矩阵 / 跨层违规 / UI 对 engine 内部模块 / Qt 依赖 / SCC / 可选 import 耗时 | `docs/COUPLING.md` 全部数字；CHANGELOG 补记 25 |
| `p1_equiv_check.py [--old 提交]` | `git show <提交>:src/task/EnhanceEchoTask.py`（默认 `3e698cf`）vs 当前 `src/echo_parse|echo_scoring` → 4 个纯函数逐例对比（152 例） | `docs/COUPLING.md` §0.2「纯函数抽取不改口径」；CHANGELOG 补记 27 |

> 后两个会覆盖 `eval_report.html`，跑完用当前代码重跑 `tools/offline_eval_report.py` 复原。

## 待迁移清单（来自 `.scratch/`，按价值排序）

| 脚本 | 回答什么 | 产物 | 文档出处 |
|---|---|---|---|
| `generic_weights.py` | 四角色 × 三套权重的 ρ（通用权重该不该改） | `generic_weights.txt` | `CLAUDE.md` 组合穷举·通用权重 |
| `weight_agreement.py` | 手调 vs 推导权重的秩相关（组合级 + 件级） | `weight_agreement.txt` | 同上·"权重不是瓶颈" |
| `score_agreement.py` | 评分和/有效分与伤害排序 ∪ Top-K 重合 | `score_agreement.txt` | 同上·"评分和不能当排序" |
| `margins.py` | 当前面板下每条词条 +1 点的边际伤害 | `margins.txt` | 同上·套装权重定法 |
| `derive_weights.py` | 按边际反推权重（已被否决，保留证据） | `derived_weights.txt` | 同上·"反推未改善" |
| `why_pass.py` | "只有 3 条有效词条为什么也能达标" | `why_pass.txt` | `eval_rules.md` §7 / 补记 13 |
| `measure_table2.py` | 结果表列宽实测 | — | `CLAUDE.md` 排名表列宽 |
| `plan_page_shot.py` / `sigelika_page.py` | "已导入 + 已排名"渲染走查 | `plan_page_*.png` | `CLAUDE.md` 改表后必跑 |

> 迁移时**保留原输出文件**（`.txt`）作为对照；脚本与 `.txt` 一起提交，文件头补上"生成命令 + 对应提交号"。

## 为什么不在 `.scratch/` 里继续写

`.scratch/` 在 `ww-echo` 的**父目录**，`git ls-files` 为 0 —— 它的脚本、`.txt` 记录、截断的 `wuwacalc.html`
都不会被克隆，导致 `CLAUDE.md` / `eval_rules.md` 里 20 多处 `.scratch/...` 引用在干净仓库上全是死链。
新脚本请写在这里；旧的按上表逐步迁移。
