from ww_engine.device.capture_methods.base import BaseCaptureMethod, BaseWindowsCaptureMethod
from ww_engine.device.capture_methods.bitblt import BitBltCaptureMethod, ForegroundBitBltCaptureMethod
from ww_engine.device.capture_methods.bitblt_utils import (
    BGRA_CHANNEL_COUNT,
    PBYTE,
    PW_CLIENT_ONLY,
    PW_RENDERFULLCONTENT,
    BitBltCtxDummy,
    capture_by_bitblt,
    capture_desktop_by_bitblt,
    clean_up_bitblt,
    clean_up_desktop_bitblt,
    composite_hwnds,
    get_crop_point,
    parse_reg_flag,
    try_delete_dc,
)
from ww_engine.device.capture_methods.hwnd_window import (
    HwndWindow,
    check_pos,
    get_monitors_bounds,
    get_mute_state,
    is_window_in_screen_bounds,
    set_mute_state,
)
from ww_engine.device.capture_methods.types import ColorChannel, ImageShape, decimal, is_digit, is_valid_hwnd
from ww_engine.device.capture_methods.update import get_capture, get_win_graphics_capture, update_capture_method
from ww_engine.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
