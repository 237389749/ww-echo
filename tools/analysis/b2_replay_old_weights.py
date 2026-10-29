"""用**某个历史提交**的套装权重重跑 B2, 用来还原"文档里那版判定分布"是在哪套权重下产生的。

输入: `logs/eval_debug/20260911_110817/`（B2 素材, 未入库）+ `git show <提交>:assets/echo_set_templates.json`
输出: stdout 判定分布（会覆盖 `eval_report.html`; 跑完请用当前代码重跑 `tools/offline_eval_report.py` 复原）
支撑: CHANGELOG 补记 21 的证据 ①——用 `726db9c~1` 的听唤语义之愿权重（共效 0.4 / 重击 0.4）重跑,
      判定分布逐项复现文档旧值 `pass 39 / hold 38 / keep 1 / pending 7 / fail 24`。

用法（仓库根）:
    python tools/analysis/b2_replay_old_weights.py 726db9c~1 [套装名]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import src.echo_set_templates as S                         # noqa: E402

rev = sys.argv[1]
set_name = sys.argv[2] if len(sys.argv) > 2 else "听唤语义之愿"

raw = subprocess.run(["git", "show", f"{rev}:assets/echo_set_templates.json"],
                     capture_output=True, check=True).stdout.decode("utf-8")
old = json.loads(raw)["sets"]

entry = S.load_templates()[set_name]["weights"]
old_entry = {k: v for k, v in old[set_name].items() if not k.startswith("_")}
print(f"当前  {set_name}: {entry}")
print(f"{rev} {set_name}: {old_entry}")
entry.update(old_entry)

import tools.offline_eval_report as R                       # noqa: E402

sys.argv = ["offline_eval_report.py"]
raise SystemExit(R.main())
