"""ww_engine 任务层接线自检（不需要游戏/OCR 模型）。

两个守卫：
1. `task.py` 引用到的 `executor.<attr>` 必须真的存在于 `TaskExecutor` —— 阶段三十一裁剪
   把 `locale`/`text_fix`/`ocr_po_translation` 的初始化删了、引用却留着，OCR 一调用就
   AttributeError（离线单测没覆盖到，属于真机才炸的回归）。
2. `onnx_ocr` 的后处理：文字 strip、置信度阈值、负尺寸过滤、match 过滤，且不再依赖 i18n/opencc。
"""
import pathlib
import re
import unittest

from ww_engine.task.TaskExecutor import TaskExecutor
from ww_engine.task.task import OCR

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _FakeOcrLib:

    def __init__(self, result):
        self.result = result

    def ocr(self, image):
        return self.result, None


class _FakeExecutor:

    def __init__(self, result):
        self.config = {'ocr': {'default': {'lib': 'onnxocr'}}}
        self._lib = _FakeOcrLib(result)
        self.paused = False
        self.frame = None
        self.debug = False

    def ocr_lib(self, name='default'):
        return self._lib

    def sleep(self, timeout):
        pass


def _make_ocr(result):
    ocr = object.__new__(OCR)
    ocr._executor = _FakeExecutor(result)
    # 真实调用方是 BaseTask（log_debug 是方法）；这里按默认"不记日志"置位
    ocr.log_debug = False
    return ocr


POS = [[10, 10], [30, 10], [30, 20], [10, 20]]


class TestExecutorAttributes(unittest.TestCase):
    """task.py 里的 self.executor.X 都必须是 TaskExecutor 的真实成员。"""

    def test_all_referenced_executor_attrs_exist(self):
        src = (ROOT / 'ww_engine' / 'task' / 'task.py').read_text(encoding='utf-8')
        referenced = set(re.findall(r'self\.executor\.([A-Za-z_][A-Za-z0-9_]*)', src))
        available = set(dir(TaskExecutor)) | set(getattr(TaskExecutor, '__annotations__', {}))
        self.assertEqual(sorted(referenced - available), [],
                         msg='task.py 引用了 TaskExecutor 上不存在的属性（裁剪时删了初始化？）')


class TestOnnxOcrPostProcess(unittest.TestCase):

    def test_text_is_stripped_and_filtered(self):
        result = [
            [POS, (' 暴击伤害 ', 0.9)],
            [POS, ('攻击', 0.19)],                       # 低于阈值 0.2
            [[[10, 10], [10, 10], [10, 10], [10, 10]], ('生命', 0.8)],  # 负尺寸
        ]
        ocr = _make_ocr(result)
        matched, all_boxes = ocr.onnx_ocr(None, None, '暴击伤害', 1.0, 0.2, 'default')
        self.assertEqual([b.name for b in all_boxes], ['暴击伤害'])
        self.assertEqual([b.name for b in matched], ['暴击伤害'])
        self.assertEqual((matched[0].x, matched[0].y, matched[0].width, matched[0].height),
                         (10, 10, 20, 10))

    def test_match_filters_but_keeps_all_boxes(self):
        result = [[POS, ('暴击伤害', 0.9)], [POS, ('攻击', 0.9)]]
        ocr = _make_ocr(result)
        matched, all_boxes = ocr.onnx_ocr(None, None, '攻击', 1.0, 0.2, 'default')
        self.assertEqual([b.name for b in all_boxes], ['暴击伤害', '攻击'])
        self.assertEqual([b.name for b in matched], ['攻击'])

    def test_onnx_is_the_only_backend(self):
        ocr = _make_ocr([])
        self.assertEqual(ocr.ocr_fun('default'), ocr.onnx_ocr)

    def test_ocr_entry_point(self):
        """走完整 ocr() 入口（区域裁剪 + onnx_ocr + match），不碰真实模型。"""
        import numpy as np
        ocr = _make_ocr([[POS, (' 暴击伤害 ', 0.9)]])
        frame = np.zeros((100, 100, 3), np.uint8)
        boxes = ocr.ocr(x=0, y=0, to_x=0.5, to_y=0.5, threshold=0.2,
                        frame=frame, match='暴击伤害')
        self.assertEqual([b.name for b in boxes], ['暴击伤害'])
        self.assertEqual((boxes[0].x, boxes[0].y, boxes[0].width, boxes[0].height),
                         (10, 10, 20, 10))


if __name__ == '__main__':
    unittest.main()
