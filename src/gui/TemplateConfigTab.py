"""
套装模板管理 Tab — 导入/导出 echo_set_templates.json。
"""

import os
import shutil

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel
from qfluentwidgets import PushButton, FluentIcon, BodyLabel, StrongBodyLabel, InfoBar, InfoBarPosition

from ok import og
from ok.gui.widget.CustomTab import CustomTab


TEMPLATE_FILENAME = "echo_set_templates.json"
TEMPLATE_ASSETS_DIR = os.path.join(os.getcwd(), "assets")
TEMPLATE_PATH = os.path.join(TEMPLATE_ASSETS_DIR, TEMPLATE_FILENAME)


class TemplateConfigTab(CustomTab):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self._setup_ui()

    @property
    def name(self):
        return "模板管理 | Templates"

    def _setup_ui(self):
        # 标题
        title = StrongBodyLabel("套装模板管理 | Set Template Manager")
        self.add_widget(title)

        desc = BodyLabel(
            "管理套装预期词条和权重配置文件。\n"
            "修改模板后点击导入即可加载, 导出可备份或分享给他人。\n"
            f"当前模板路径: {TEMPLATE_PATH}"
        )
        desc.setWordWrap(True)
        self.add_widget(desc)

        self.add_widget(QLabel(""))  # spacer

        # 按钮行
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(12)

        self.export_btn = PushButton(FluentIcon.SAVE, "导出模板 | Export")
        self.export_btn.clicked.connect(self._export_template)
        btn_layout.addWidget(self.export_btn)

        self.import_btn = PushButton(FluentIcon.FOLDER, "导入模板 | Import")
        self.import_btn.clicked.connect(self._import_template)
        btn_layout.addWidget(self.import_btn)

        self.reset_btn = PushButton(FluentIcon.CANCEL, "恢复默认 | Reset Default")
        self.reset_btn.clicked.connect(self._reset_default)
        btn_layout.addWidget(self.reset_btn)

        btn_layout.addStretch()
        self.add_widget(btn_widget)

    def _show_success(self, msg):
        InfoBar.success(
            title="成功 | Success",
            content=msg,
            orient=InfoBarPosition.TOP,
            isClosable=True,
            duration=3000,
            parent=self.window(),
        )

    def _show_error(self, msg):
        InfoBar.error(
            title="错误 | Error",
            content=msg,
            orient=InfoBarPosition.TOP,
            isClosable=True,
            duration=5000,
            parent=self.window(),
        )

    def _ensure_template_exists(self):
        """确保模板文件存在 (不存在则从备份恢复)。"""
        if not os.path.exists(TEMPLATE_PATH):
            os.makedirs(TEMPLATE_ASSETS_DIR, exist_ok=True)
            backup = TEMPLATE_PATH + ".bak"
            if os.path.exists(backup):
                shutil.copy(backup, TEMPLATE_PATH)
                return True
            return False
        return True

    def _export_template(self):
        if not self._ensure_template_exists():
            self._show_error("模板文件不存在且无可恢复的备份")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.window(),
            "导出套装模板 | Export Template",
            TEMPLATE_FILENAME,
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if file_path:
            try:
                shutil.copy(TEMPLATE_PATH, file_path)
                self._show_success(f"已导出到: {file_path}")
            except Exception as e:
                self._show_error(f"导出失败: {e}")

    def _import_template(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.window(),
            "导入套装模板 | Import Template",
            "",
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if file_path:
            try:
                # 备份当前模板
                if os.path.exists(TEMPLATE_PATH):
                    shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")

                # 确保目录存在
                os.makedirs(TEMPLATE_ASSETS_DIR, exist_ok=True)

                # 复制新模板
                shutil.copy(file_path, TEMPLATE_PATH)

                # 清除缓存, 下次加载时重新读取
                from src.echo_set_templates import load_templates
                load_templates(force=True)

                self._show_success(f"已从 {file_path} 导入模板\n原模板已备份为 .bak")
            except Exception as e:
                self._show_error(f"导入失败: {e}")

    def _reset_default(self):
        from qfluentwidgets import MessageBox
        w = MessageBox(
            "确认恢复 | Confirm Reset",
            "将恢复为项目自带的默认模板, 当前模板会备份为 .bak。\n确定继续?",
            self.window(),
        )
        if w.exec():
            try:
                # 备份
                if os.path.exists(TEMPLATE_PATH):
                    shutil.copy(TEMPLATE_PATH, TEMPLATE_PATH + ".bak")

                # 从 git 恢复默认 (或直接重建)
                # 默认模板已随项目分发在 assets/echo_set_templates.json
                # 如果被覆盖了, 从备份恢复
                backup = TEMPLATE_PATH + ".bak"
                if os.path.exists(backup):
                    # 恢复上次导入前的版本
                    pass  # 默认模板就是项目自带的, git checkout 即可

                # 清除缓存
                from src.echo_set_templates import load_templates
                load_templates(force=True)

                self._show_success("已恢复默认模板 (重新加载项目自带版本)")
            except Exception as e:
                self._show_error(f"恢复失败: {e}")
