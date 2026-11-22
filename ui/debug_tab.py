"""
调试工具 — OCR 测试 / 截图 / 覆盖层 / 文件夹 + 共享运行日志(Fluent 分栏卡片)。

页内用 `SegmentedWidget` 分四个子页; 底部保留运行日志(与「运行」页同一日志流的第二份视图)。
按钮/开关全部 Fluent 化, 结果用 InfoBar 反馈(不再只靠 ww_engine 的弹窗)。
"""
import os
import subprocess
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (CaptionLabel, FluentIcon as FIF, HeaderCardWidget, ImageLabel, InfoBar,
                            InfoBarPosition, PushSettingCard, SegmentedWidget, SettingCardGroup,
                            SingleDirectionScrollArea, SwitchSettingCard)

from ww_engine import og, communicate

from ui.widgets import make_scroll_transparent


def _card_body(card: HeaderCardWidget) -> QVBoxLayout:
    """HeaderCardWidget 的 viewLayout 是横向的(库源码: QHBoxLayout(self.view)), 正文要自己套纵向。"""
    body = QWidget()
    vb = QVBoxLayout(body)
    vb.setContentsMargins(0, 0, 0, 0)
    vb.setSpacing(10)
    card.viewLayout.addWidget(body)
    card.vBoxLayout.setStretchFactor(card.view, 1)
    return vb


class DebugTab(QWidget):
    def __init__(self, log_area, parent=None):
        super().__init__(parent)
        self.log_area = log_area
        self._setup_ui()
        self._load()

    # ══════════════════ UI ══════════════════
    def _setup_ui(self):
        # **页面级滚动容器**(U-02): 620 高的最小窗口下, 分页头 + 子页 + 日志卡放不下 —— 日志卡会被压到
        # 60px 并被裁掉。套 `SingleDirectionScrollArea` 后整页可滚, 日志卡另有最小高度(见下)。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        self.segmented = SegmentedWidget()
        self.stack = QStackedWidget()
        pages = (("ocr", "OCR 测试", self._page_ocr()),
                 ("shot", "截图", self._page_shot()),
                 ("overlay", "覆盖层", self._page_overlay()),
                 ("folder", "文件夹", self._page_folder()))
        self._routes = [k for k, _, _ in pages]
        for key, text, page in pages:
            self.segmented.addItem(key, text)
            self.stack.addWidget(page)
        self.segmented.setCurrentItem(self._routes[0])
        self.segmented.currentItemChanged.connect(self._on_route_changed)
        layout.addWidget(self.segmented)
        layout.addWidget(self.stack)
        self._fit_stack()

        # ── 运行日志(与运行页同一日志流的第二份视图) ──
        log_card = HeaderCardWidget()
        log_card.setTitle("运行日志")
        self.log_card = log_card
        log_card.setMinimumHeight(260)      # 日志卡自己的滚动条管内容, 页面滚动管整页
        body = _card_body(log_card)
        body.addWidget(self.log_area, 1)
        layout.addWidget(log_card, 1)      # 多余高度给日志卡(子页已不抢空间)

        scroll = make_scroll_transparent(SingleDirectionScrollArea(orient=Qt.Vertical))
        scroll.setWidgetResizable(True)
        scroll.setWidget(view)
        outer.addWidget(scroll, 1)

    def _on_route_changed(self, key: str):
        self.stack.setCurrentIndex(self._routes.index(key))
        self._fit_stack()

    def _fit_stack(self):
        """子页高度跟着**当前页**走。

        `QStackedWidget` 的 sizeHint 取**所有**子页的最大值 —— 「截图」页的预览图有 min 200,
        会把只有一张卡的 OCR 页也撑到 419px, 于是中间空一大片、日志卡被顶到视口外面
        (U-02 实测 892×570)。这里按当前页的 sizeHint 固定高度, 切页时重算。
        """
        page = self.stack.currentWidget()
        if page is not None:
            self.stack.setFixedHeight(page.sizeHint().height())

    def _page_ocr(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        g = SettingCardGroup("OCR 测试", page)
        card = PushSettingCard("识别并截图", FIF.SEARCH, "跑一次 OCR",
                               "对当前帧做一次 OCR, 结果写入 screenshots/ocr_result.txt 并打开文件夹", page)
        card.clicked.connect(self._ocr_test)
        g.addSettingCard(card)
        v.addWidget(g)
        v.addStretch(1)
        return page

    def _page_shot(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        g = SettingCardGroup("截图", page)
        card = PushSettingCard("手动截图", FIF.CAMERA, "保存当前帧",
                               "存到 screenshots/ 并在资源管理器中定位该文件", page)
        card.clicked.connect(self._screenshot)
        g.addSettingCard(card)
        v.addWidget(g)

        preview_card = HeaderCardWidget()
        preview_card.setTitle("预览")
        body = _card_body(preview_card)
        self.preview = ImageLabel()
        self.preview.setText("尚未截图")
        self.preview.setMinimumHeight(200)
        self.preview.setAlignment(Qt.AlignCenter)
        body.addWidget(self.preview, 1)
        v.addWidget(preview_card, 1)
        return page

    def _page_overlay(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        g = SettingCardGroup("调试悬浮窗", page)
        self.overlay_boxes = SwitchSettingCard(FIF.VIEW, "显示识别框",
                                               "在悬浮窗里画出识别到的文本框/模板框(排查定位问题用)", None, page)
        self.overlay_boxes.checkedChanged.connect(self._on_overlay_boxes)
        self.overlay_log = SwitchSettingCard(FIF.MEGAPHONE, "悬浮窗显示日志",
                                             "把运行日志同步画到悬浮窗上(全屏游戏时用)", None, page)
        self.overlay_log.checkedChanged.connect(self._on_overlay_log)
        g.addSettingCards([self.overlay_boxes, self.overlay_log])
        v.addWidget(g)
        v.addStretch(1)
        return page

    def _page_folder(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        g = SettingCardGroup("打开文件夹", page)
        for icon, title, content, slot in (
                (FIF.PHOTO, "截图文件夹", "screenshots/", self._open_screenshots),
                (FIF.DOCUMENT, "日志文件夹", "logs/(含离线调试数据集)", self._open_logs)):
            card = PushSettingCard("打开", icon, title, content, page)
            card.clicked.connect(slot)
            g.addSettingCard(card)
        v.addWidget(g)
        v.addStretch(1)
        return page

    # ══════════════════ 行为(保持原有语义) ══════════════════
    def _load(self):
        try:
            self.overlay_boxes.setChecked(bool(og.app.ok_config.get('use_overlay', False)))
            self.overlay_log.setChecked(bool(og.app.ok_config.get('show_overlay_logs', True)))
        except Exception:
            pass

    def _on_overlay_boxes(self, checked: bool):
        try:
            og.app.ok_config['use_overlay'] = bool(checked)
            og.app.ok_config.save_file()
            if ov := og.app.get_overlay_view():
                ov.set_boxes_enabled(bool(checked))
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("设置失败", str(e), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _on_overlay_log(self, checked: bool):
        try:
            og.app.ok_config['show_overlay_logs'] = bool(checked)
            og.app.ok_config.save_file()
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("设置失败", str(e), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _ocr_test(self):
        def _run():
            try:
                if og.executor.paused:
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
            except Exception as e:                               # noqa: BLE001
                # 用公共 notification 信号，不再 import engine 的 gui.util.Alert
                communicate.notification.emit(f"OCR 测试失败: {e}", None, True, False, None, None)

        threading.Thread(target=_run, daemon=True).start()

    def _screenshot(self):
        try:
            m = og.device_manager.capture_method
            if m is None:
                InfoBar.warning("没有截图源", "先在「设备设置」里选好窗口", duration=3000,
                                position=InfoBarPosition.TOP_RIGHT, parent=self)
                return
            frame = m.get_frame()
            if frame is None:
                InfoBar.warning("截图为空", "窗口可能最小化, 或该截图方式不适用(WGC 抓浏览器常黑屏)",
                                duration=4000, position=InfoBarPosition.TOP_RIGHT, parent=self)
                return
            import time

            import cv2
            folder = os.path.join(os.getcwd(), "screenshots")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"screenshot_{int(time.time())}.png")
            cv2.imwrite(path, frame)
            try:
                self.preview.setImage(path)          # 顺手在页内预览
            except Exception:
                pass
            subprocess.Popen(f'explorer /select,"{path}"')
        except Exception as e:                                   # noqa: BLE001
            InfoBar.error("截图失败", str(e), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT, parent=self)

    def _open_screenshots(self):
        folder = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')

    def _open_logs(self):
        folder = os.path.join(os.getcwd(), "logs")
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(f'explorer "{folder}"')
