"""
图像预处理工具 — 模板匹配前的特征图转换。
"""

import cv2
import numpy as np

lower_white = np.array([244, 244, 244], dtype=np.uint8)
lower_white_none_inclusive = np.array([240, 240, 240], dtype=np.uint8)
upper_white = np.array([255, 255, 255], dtype=np.uint8)
black = np.array([0, 0, 0], dtype=np.uint8)
lower_icon_white = np.array([210, 210, 210], dtype=np.uint8)
upper_icon_white = np.array([244, 244, 244], dtype=np.uint8)


def convert_bw(cv_image):
    """白色区域变白，其余变黑。"""
    match_mask = cv2.inRange(cv_image, lower_white, upper_white)
    return cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)


def binarize_for_matching(image, threshold=244):
    """灰度二值化: 亮度 > threshold 变白, 其余变黑。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    return binary


def convert_dialog_icon(cv_image):
    """对话框图标专用: 210-244 范围变白, 其余变黑。"""
    match_mask = cv2.inRange(cv_image, lower_icon_white, upper_icon_white)
    return cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)
