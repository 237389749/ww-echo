"""一次性: 打印面板数据集的 OCR 文本 + 把 s00/s03 并排存一张对照图。用完即删。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '.')
import cv2
import numpy as np

d = Path('logs/panel_debug/20261119_163020')
for line in (d / 'panel_ocr.jsonl').read_text(encoding='utf-8').splitlines():
    r = json.loads(line)
    if r.get('kind') == 'summary':
        print('SUMMARY', json.dumps({k: r.get(k) for k in
                                     ('tag', 'name', 'cands', 'steps', 'notches',
                                      'found', 'src', 'restore_ok', 'long_h')},
                                    ensure_ascii=False))
    else:
        print(f"STEP{r['step']} notches={r['notches']}: "
              + ' | '.join(t['name'] for t in r['texts'])[:300])


def im(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


a = im(d / '006_鸣钟之龟_s00.png')
b = im(d / '006_鸣钟之龟_s03.png')
sep = np.full((a.shape[0], 12, 3), (0, 0, 255), np.uint8)
cv2.putText(a, 's00', (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
cv2.putText(b, 's03', (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
cv2.imwrite('logs/_panel_cmp.png', np.hstack([a, sep, b]))
print('saved logs/_panel_cmp.png')
