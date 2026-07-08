"""
调试工具 — OCR 测试, 截图预览, 覆盖层开关。
"""
import os
import subprocess
import threading

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QFrame, QCheckBox)

from ok import og
from ok.gui.Communicate import communicate


class DebugTab(QWidget):
    def __init__(self, log_area, parent=None):
        super().__init__(parent)
        self.log_area = log_area
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ═══════ OCR 测试 ═══════
        layout.addWidget(QLabel("◆ OCR 测试"))
        ocr_row = QHBoxLayout()
        ocr_btn = QPushButton("OCR 识别并截图")
        ocr_btn.clicked.connect(self._ocr_test)
        ocr_row.addWidget(ocr_btn)
        ocr_row.addStretch()
        layout.addLayout(ocr_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)

        # ═══════ 截图 ═══════
        layout.addWidget(QLabel("◆ 截图"))
        ss_row = QHBoxLayout()
        ss_btn = QPushButton("手动截图")
        ss_btn.clicked.connect(self._screenshot)
        ss_row.addWidget(ss_btn)
        ss_row.addWidget(QLabel("保存到 screenshots/"))
        ss_row.addStretch()
        layout.addLayout(ss_row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); layout.addWidget(sep2)

        # ═══════ 覆盖层 ═══════
        layout.addWidget(QLabel("◆ 调试悬浮窗"))
        self.overlay_boxes = QCheckBox("显示识别框")
        self.overlay_boxes.stateChanged.connect(self._on_overlay_boxes)
        layout.addWidget(self.overlay_boxes)

        self.overlay_log = QCheckBox("悬浮窗显示日志")
        self.overlay_log.stateChanged.connect(self._on_overlay_log)
        layout.addWidget(self.overlay_log)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); layout.addWidget(sep3)

        # ═══════ 文件夹 ═══════
        layout.addWidget(QLabel("◆ 工具"))
        tools = QHBoxLayout()
        for text, slot in [
            ("截图文件夹", self._open_screenshots),
            ("日志文件夹", self._open_logs),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        tools.addStretch()
        layout.addLayout(tools)

        # ── 运行日志 (共享) ──
        layout.addWidget(QLabel("运行日志 (所有操作的输出)"))
        layout.addWidget(self.log_area, 1)

    def _load(self):
        try:
            self.overlay_boxes.setChecked(og.app.ok_config.get('use_overlay', False))
            self.overlay_log.setChecked(og.app.ok_config.get('show_overlay_logs', True))
        except Exception:
            pass

    def _on_overlay_boxes(self, state):
        og.app.ok_config['use_overlay'] = bool(state)
        og.app.ok_config.save_file()
        if ov := og.app.get_overlay_view():
            ov.set_boxes_enabled(bool(state))

    def _on_overlay_log(self, state):
        og.app.ok_config['show_overlay_logs'] = bool(state)
        og.app.ok_config.save_file()

    def _ocr_test(self):
        def _run():
            try:
                if og.executor.paused:
                    from ok.gui.util.Alert import alert_error
                    return
                result = og.executor.get_all_tasks()[0].ocr(log=True, screenshot=True)
                folder = os.path.abspath(og.ok.screenshot.screenshot_folder)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                    if result:
                        result_path = os.path.join(folder, 'ocr_result.txt')
                        with open(result_path, 'w', encoding='utf-8') as f:
                            for box in result:
                                f.write(f"{box.name}, {box}, {box.confidence}\n")
                    subprocess.Popen(f'explorer "{folder}"')
            except Exception as e:
                from ok.gui.util.Alert import alert_error
                alert_error(f"OCR 测试失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _screenshot(self):
        try:
            m = og.device_manager.capture_method
            if m is None:
                return
            frame = m.get_frame()
            if frame is not None:
                import cv2
                folder = os.path.join(os.getcwd(), "screenshots")
                os.makedirs(folder, exist_ok=True)
                import time
                name = f"screenshot_{int(time.time())}.png"
                path = os.path.join(folder, name)
                cv2.imwrite(path, frame)
                subprocess.Popen(f'explorer /select,"{path}"')
        except Exception:
            pass

    def _open_screenshots(self):
        folder = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')

    def _open_logs(self):
        folder = os.path.join(os.getcwd(), "logs")
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')
