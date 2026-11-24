"""
把「队伍面板」9 个方案的裸面板 + 补正同步进角色预设（assets/char_profiles.json）。

输入:
  - tools/analysis/team_plan.py 的 PLANS（白值/裸面板/补正/条件补正/专伤/配装）—— **唯一事实源**
  - 现有的 assets/char_profiles.json（只沿用 生命/防御 这类本次没用到的裸面板键）
输出:
  - assets/char_profiles.json 的 chars：9 条，名字带方案后缀（"仇远 3+2" 这种）
支撑:
  - docs/TEAM_PANEL_SUMMARY_2026-11-24.md §2（角色基础）/ §3（面板冻结值）/ §4（补正来源）
  - 验收：载入每条预设 → aggregate(bare, corrections, []) → 必须等于 §3 的 9 行面板

为什么从 team_plan.PLANS 导入而不是抄一遍数字: 面板口径改一次就要同步一次，抄两份必然漂移
（上次交接文档的 4 个 33311 数就是这么过期的）。

注意:
  - team_plan.py 会连带 import src.echo_inventory → cv2，请用装过 requirements.txt 的 Python 跑。
  - 预设里显式写 `crit: {"target": 0}`：本次口径关了暴击稳定性系数，
    不写的话载入预设会退回默认 100/0.40/0.80，E 与文档对不上。

用法:
  python tools/analysis/sync_char_profiles.py --check     # 只核对现有预设（不写文件）
  python tools/analysis/sync_char_profiles.py             # 写入
  python tools/analysis/sync_char_profiles.py --dry-run   # 打印将要写入的内容，不落盘
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import char_profiles                                     # noqa: E402
from src.echo_panel import aggregate                              # noqa: E402
from tools.analysis.team_plan import PLANS                        # noqa: E402  (会拉起 cv2)

# 方案 key → 预设名（单个方案的角色用本名，多方案带后缀）
PRESET_NAME = {
    "sanhua": "散华",
    "luhesis": "陆赫斯",
    "dania": "达妮娅",
    "aemis": "爱弥斯",
    "qiuyuan32": "仇远 3+2",
    "qiuyuan5": "仇远 5",
    "sigrika32": "西格莉卡 3+2",
    "sigrika5": "西格莉卡 5",
    "feixue": "绯雪",
}

# 旧的过期预设（裸面板还是"带武器总值"、西格还是 300 增伤版），同步时清掉
STALE = ("仇远", "西格莉卡")

# 本次没用到的裸面板键（scaling=攻击 不需要），从旧预设沿用，避免丢数据
KEEP_BARE_KEYS = ("生命", "防御")

# §3 冻结值：(攻击总值, 共效, 暴击, 暴伤, 增伤)
EXPECTED = {
    "sanhua": (1654.6, 126, 29.3, 150, 32),
    "luhesis": (2480.1, 100, 37.3, 150, 112),
    "dania": (1839.8, 110, 41, 166, 66),
    "aemis": (2059.0, 100, 57.3, 210, 84),
    "qiuyuan32": (1721.1, 110, 57.3, 180, 206),
    "qiuyuan5": (1721.1, 110, 57.3, 180, 160),
    "sigrika32": (1729.8, 100, 33, 228.6, 187),
    "sigrika5": (1960.2, 100, 33, 228.6, 183),
    "feixue": (2217.9, 100, 62.3, 190, 32),
}


def build_profiles(old: dict[str, dict]) -> dict[str, dict]:
    """9 个方案 → 预设 dict（键=预设名）。"""
    out: dict[str, dict] = {}
    for spec in PLANS:
        name = PRESET_NAME[spec.key]
        bare = dict(spec.bare)
        prev = old.get(name) or {}
        for k in KEEP_BARE_KEYS:                      # 生命/防御：本次不用，沿用旧的
            if k in (prev.get("bare") or {}) and k not in bare:
                bare[k] = prev["bare"][k]
        prof = char_profiles.build_profile(
            scaling="攻击",
            bare=bare,
            corrections=spec.corrections,              # 含「固定攻击 103/251/...」那条
            derived=spec.derived,
            specialty=spec.allowed_bonus or (),
            # 门槛：共效用默认 120/0.30/0.85；暴击稳定性系数本次关 → target 0
            crit={"target": 0},
            plan={"mode": spec.mode, "set_a": spec.set_a, "set_b": spec.set_b,
                  "cost4_owner": spec.cost4_owner},
            max_level_only=True,
        )
        out[name] = prof
    return out


def verify(profiles: dict[str, dict]) -> list[str]:
    """载入预设 → 重算不带声骸的面板 → 与 §3 逐项比。返回问题列表（空 = 全对）。"""
    bad = []
    for spec in PLANS:
        name = PRESET_NAME[spec.key]
        prof = profiles.get(name)
        if not prof:
            bad.append(f"{name}: 预设缺失")
            continue
        kw = char_profiles.to_request_kwargs(prof)
        allowed = tuple(kw.get("allowed_bonus") or ())
        p = aggregate(prof["bare"], char_profiles.corrections_of(prof), [],
                      allowed_bonus=allowed, derived=())
        # p.bonus 是 {词条: 数值} 的分项，面板上的「增伤」是它的和（与 team_plan 同口径）
        got = (p.scaling_total("攻击"), p.energy, p.crit_rate, p.crit_dmg,
               sum(p.bonus.values()))
        exp = EXPECTED[spec.key]
        diffs = [round(g - e, 3) for g, e in zip(got, exp)]
        if max(abs(d) for d in diffs) > 0.051:
            bad.append(f"{name}: {got} != {exp}  diff={diffs}")
        else:
            print(f"  {name:<12s} 攻击 {got[0]:9.2f} 共效 {got[1]:6.1f} 暴击 {got[2]:6.1f} "
                  f"暴伤 {got[3]:6.1f} 增伤 {got[4]:6.1f}  OK")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description="把队伍面板方案同步进角色预设")
    ap.add_argument("--check", action="store_true", help="只核对现有预设，不写文件")
    ap.add_argument("--dry-run", action="store_true", help="打印 JSON，不落盘")
    a = ap.parse_args()

    old = char_profiles.load_all()
    print(f"现有预设: {len(old)} 条 {sorted(old)}")
    profiles = build_profiles(old)

    if a.check:
        print("\n核对现有文件：")
        bad = verify(char_profiles.load_all())
        if bad:
            for b in bad:
                print("  [不一致]", b)
            raise SystemExit("预设与 §3 冻结值不一致")
        print("\n--check 通过：现有预设全部可复现 §3 面板。")
        return

    print("\n核对将要写入的内容：")
    bad = verify(profiles)
    if bad:
        for b in bad:
            print("  [不一致]", b)
        raise SystemExit("构造出的预设与 §3 不一致，拒绝写文件")

    if a.dry_run:
        print("\n--- dry-run（不落盘）---")
        print(json.dumps({"version": 1, "chars": profiles}, ensure_ascii=False, indent=1)[:2000])
        return

    for name in STALE:
        if name in old and name not in profiles:
            char_profiles.delete(name)
            print(f"  删除过期预设: {name}")
    for name, prof in profiles.items():
        char_profiles.upsert(name, prof)
    now = char_profiles.load_all()
    print(f"\n写入完成，现有预设 {len(now)} 条: {sorted(now)}")
    print(f"文件: {Path(char_profiles.PATH).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
