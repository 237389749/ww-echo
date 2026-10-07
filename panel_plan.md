# S1/S2 实施规格：角色面板模型 + 声骸主属性穷举

## S1 面板模型（先把"人"算准）

**输入表**（`search/wwdata37/BinData`，已拉取）：

| 用途 | 表 | 字段 |
|---|---|---|
| 角色入口 | `role/roleinfo.json` | `PropertyId`(→基础属性行) `ElementId` `MaxLevel` `BreachId` `SkillTreeGroupId` `WeaponType` `InitWeaponItemId` |
| 基础属性 | `property/baseproperty.json` | 按 `PropertyId` 取基础 生命/攻击/防御（探针见上，`Id` 命中即基础属性行） |
| 等级成长 | `property/rolepropertygrowth.json` | `Level` + `BreachLevel` → `LifeMaxRatio/AtkRatio/DefRatio`（10000=100%） |
| 武器 | `weapon/weaponconf.json` + `weaponlevel.json`（+`weaponbreach.json`） | 基础攻击 / 副属性 / 突破 |
| 天赋 | `skillTree/` | 暴击/元素加成等不进 baseproperty 的部分 |

**公式**：`面板值 = base(PropertyId) × ratio(Level, BreachLevel)/10000 + 武器 + 天赋 + 声骸主属性 + 声骸副词条 + 套装效果`

**验收（必须做，否则整条链不可信）**：拿**游戏内一只角色的满级面板**对数字（攻击/生命/防御/暴击/爆伤/共效/元素伤害）。
需要用户提供 1 个角色的面板截图或数值（程序无法自证）。

**产物**：`src/echo_panel.py`（`CharacterPanel(role_id, level, breach, weapon_id, ...)`）→ `dict[str, float]`，
以及 `tools/gen_echo_data.py` 增补 `roles`/`weapons` 段（只出面板需要的字段，控制体积）。

## S2 主属性穷举

**搜索空间**（可穷举的三维）：

1. **COST 型**：5 件、`Σcost ≤ 12`，主流 `43311`(4+3+3+1+1) 与 `44111`(4+4+1+1+1)；
2. **每槽主属性**：按 COST 取池（4C≈7、3C 5~8、1C 3）→ 43311 约 4 千组合、44111 约 1.3 千 → 毫秒级；
3. **套装分配**：`5+0` / `3+2` / `2+2+1`（用 `gamedata.sets[*].effects` 的 2/5 件效果，数值取 `EffectDescriptionParam`）。

**副词条不可能穷举**（单只 ≈4×10⁷、五只 ≈10³⁷），改用三种口径（可并存）：
- **期望口径**：官方概率下的"平均词条"贡献（确定值，横向可比）；
- **理想口径**：假定全理想满档（给上限）；
- **库存口径（最实用）**：用评估已读到的真实声骸（套装/COST/主属性/词条）枚举"现有能凑出的合法 5 件组合"。

**目标函数**（面板级期望，不引入动作值即可自洽）：
`E ∝ 攻击 × (1 + 暴击率×暴伤) × (1 + 属性伤害加成 + 增伤) × 套装效果叠乘`；需要防御面时另给 `EHP`。

**产物**：`tools/echo_plan.py`（CLI：`--role 1402 --set 轻云出月 --budget 12`）→ 排名表
（COST 型、每槽主属性、套装分配、面板数值、期望系数），并回答"43311 vs 44111 谁更强"。

**验收**：① 与 S1 的面板数值自洽（穷举出的最优组合代入面板模型 = 排序值）② 用"库存口径"能复现用户自己的某一套
③ 输出示例与手算一致（如 4C 暴击 22% + 3C 属性伤害 30% 的组合）。
