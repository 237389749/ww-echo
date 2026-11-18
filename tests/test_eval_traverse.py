"""评估遍历终止条件的静态守卫（不需要游戏）。

2026-11-14：改为**不识别「声骸N/3000」**，直接遍历，直到「连续两行 0 词条」或「网格为空」。
这里钉住两件事：①代码里不再有 count OCR / 步数上限；②存在 0 级尾部早停。
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


class TestEvalTraverseEnd(unittest.TestCase):

    def test_no_count_ocr(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        for token in ('read_count(', 'count_box', 'total_limit', 'anchor_ok'):
            self.assertNotIn(token, src, msg=f'评估不应再依赖声骸数量: 发现 {token}')

    def test_zero_tail_stop(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('ZERO_TAIL_STOP', src)
        self.assertIn('zero_run', src)
        self.assertIn('视为 0 级尾部', src)

    def test_empty_grid_error_has_no_anchor_hint(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('未在背包界面检测到声骸网格', src)
        self.assertNotIn('页面锚点也未识别到', src)

    def test_preflight_checks_input_permission(self):
        """开跑前必须先确认能把游戏拉到前台 —— 否则"没管理员"会伪装成"检测不到网格"。

        2026-11-18 实测: 非管理员 → bring_to_front 被 UIPI 拒 → cmd 盖在游戏上 →
        PrintWindow/BitBlt 抓到的是 cmd → 网格为空 + 所有输入被拒，错误信息完全指错方向。
        """
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('bring_to_front()', src)
        self.assertIn('以管理员身份运行', src)
        # 检测不到网格时要把当时的画面存下来（否则只能猜是"不在背包界面"还是"被遮挡"）
        self.assertIn('_save_fail_frame', src)
        self.assertIn('eval_fail_frame.png', src)

    def test_set_lookup_is_anchored_and_small_step(self):
        """找套装：小步滚 + 命中即停 + 套装名必须独占一行（或已见到「合鸣效果」标题）。

        套装分 2+5 件（名字出现两次）/ 单条目（一次），所以不能假设次数；
        但"独占一行"这个形态在两类里都成立，用它当锚点比靠标题更抗滚动位置。
        """
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('name_own_line', src)
        self.assertIn('has_heading', src)
        self.assertIn('seen_heading is not None or _name_own_line', src)
        self.assertIn('SET_PANEL_FIRST_STEP = 8', src)    # 第一步放大（主词条区没有套装名）
        self.assertIn('SET_PANEL_STEP = 4', src)          # 之后小步
        self.assertIn('_effect_box_px', src)              # 整块面板，不能只读上半截
        # 名字没认出来（候选为空）时也要读面板 —— 实测 格洛玛图→格洛犸图 就是这样;
        # 反过来: **只属于一套的件不读面板**(2026-11-19 用户口径)
        self.assertIn('elif len(cand_list) == 1:', src)
        # 滚过面板就必须回顶(滚动条是所有声骸共用的)，且回顶要闭环验(名字行可见 / 滚不动了)
        self.assertIn('restore_panel_top', src)
        self.assertIn('PANEL_UP_STEP', src)
        self.assertIn('_panel_top_ok', src)

    def test_ocr_boxes_are_normalized(self):
        """`self.ocr(...)` 收的是**归一化比例**，不是像素 —— 2026-11-19 真机踩过。

        `_effect_box_px()` 返回像素，直接 `self.ocr(*box)` 会让 `relative_box` 再乘一次帧宽高，
        裁出 (0,0) 的空图 → 面板 OCR 永远空 → 套装名文字链**从未生效**、面板滚到底还回不来。
        守卫: 找套装的 OCR 必须用归一化的 `EFFECT_BOX`，源码里不许再把像素框喂给 `ocr`。
        """
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('EFFECT_BOX = (0.66, 0.08, 0.995, 0.95)', src)
        self.assertIn('self.ocr(*EFFECT_BOX)', src)
        self.assertNotIn('texts = self.ocr(*box)', src)   # 像素框不能喂给 ocr
        # 像素框只给图像比较(frame_change_ratio), 它要的是像素
        self.assertIn('frame_change_ratio(prev, cur, box)', src)

    def test_failed_cells_are_counted_not_swallowed(self):
        """点了读不到属性 → 计入失败(可见) 且连续 N 格中止, 不能悄悄当"重复"混过去。"""
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('[失败]', src)
        self.assertIn('click_fail_stop', src)
        self.assertIn('点击后都读不到属性, 评估中止', src)
        self.assertIn('重复 {dups} 格, 失败 {miss} 格', src)

    def test_effect_box_geometry(self):
        """归一化的 EFFECT_BOX → 像素框要正好盖住右侧详情面板(不能是 0 尺寸/越界)。"""
        from ww_engine.feature.Box import relative_box
        b = relative_box(1254, 889, *(0.66, 0.08, 0.995, 0.95))
        self.assertGreater(b.width, 300)
        self.assertGreater(b.height, 600)
        self.assertLessEqual(b.x + b.width, 1254)
        self.assertLessEqual(b.y + b.height, 889)


class TestEvalTraverseNoGap(unittest.TestCase):
    """遍历"不漏行"的静态守卫（2026-11-14 二次：真机只收到 54/229）。

    教训：
    ① **不能"连续 8 格重复就提前滚屏"** —— 一次只滚 2~3 行时本屏前两行都是重复，
       提前滚 4 行会把本屏没扫到的行整段跳过（`empty_hits` 已删，改由"滚动受阻连续 2 次"兜底）；
    ② 滚动**一次只发一种输入**、发完**测到停稳**再判，不能三种连发（会叠到 6 行 > 可见 5 行）；
    ③ "动了但量不出位移"要用 `frame_change_ratio` 区分，不能当成"没动"再叠一次输入。
    """

    def test_no_early_break_on_duplicates(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertNotIn('empty_hits', src, msg='连续重复不得提前跳出本屏（会漏行，见 docstring）')

    def test_scroll_measures_before_next_method(self):
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('_measure_shift', src)
        self.assertIn('frame_change_ratio', src)
        # 旧的"行线有没有变"判断已废弃（行数抖动会误判）
        self.assertNotIn('rows_differ', src)

    def test_screen_geometry_is_logged(self):
        """每屏记一条几何 + 每屏小结（新增/重复）—— 漏行只能靠这两个数在真机日志里发现。"""
        src = _read(os.path.join('src', 'task', 'EnhanceEchoTask.py'))
        self.assertIn('本屏网格', src)
        self.assertIn('本屏完成', src)


class TestNestedHelperReceiver(unittest.TestCase):
    """`evaluate_only` 里的嵌套函数只能直接调用，**不能写成 `self.xxx()`**。

    2026-11-14 真机踩过：`_log_grid_geometry` 是 `evaluate_only` 内的闭包，却写成
    `self._log_grid_geometry(...)` → 点「开始」立刻 AttributeError 中止，而 UI 只弹了一条
    InfoBar、日志里连 traceback 都没有。这里用 AST 静态挡住同类错误。
    """

    def test_no_self_reference_to_nested_functions(self):
        import ast
        path = os.path.join(ROOT, 'src', 'task', 'EnhanceEchoTask.py')
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        nested = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for ch in ast.walk(node):
                    if isinstance(ch, ast.FunctionDef) and ch is not node:
                        nested.add(ch.name)
        bad = [(n.attr, n.lineno) for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
               and n.value.id == 'self' and n.attr in nested]
        self.assertEqual(bad, [], msg=f'嵌套函数被误写成 self.<name>: {bad}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
