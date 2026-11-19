import os, sys
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from config import config, apply_run_mode, MODE_LOCAL
apply_run_mode(MODE_LOCAL)
from ww_engine import OK, og
config['check_mutex'] = False
OK(config)
executor, dm = og.executor, og.device_manager
from src.task.EnhanceEchoTask import EnhanceEchoTask, property_pattern, number_pattern
task = executor.get_task_by_class(EnhanceEchoTask)
task.config['当前套装'] = '通用'

import cv2, numpy as np
img = cv2.imdecode(np.fromfile(os.path.abspath('logs/eval_fail_panel.png'), dtype=np.uint8), cv2.IMREAD_COLOR)
print('frame', img.shape)
boxes = list(task.ocr(0, 0, 1, 1, frame=img))
print('OCR', len(boxes), 'boxes')
for b in boxes:
    print(f'  {b.name!r:<26} y={b.y:>4} w={b.width:>4} conf={getattr(b,"confidence",0):.3f}')
props = [b for b in task.find_boxes(boxes, match=property_pattern) if b.name.strip() not in ('声骸技能','COST','Z','C')]
props.sort(key=lambda b: b.y)
vals = task.find_boxes(boxes, match=number_pattern)
paired = EnhanceEchoTask._pair_props(props, vals)
print('paired:', [(n, v) for n, v in paired])
print('main_props_like:', EnhanceEchoTask._main_props_like(paired))
from src.echo_parse import normalize_stat, parse_number
from src.echo_stats import is_stat_match
for n, v in paired[2:]:
    norm = task._normalize_stat(n, v)
    print('  row', (n, v), '->', norm, parse_number(v), is_stat_match(norm or '', parse_number(v)))
