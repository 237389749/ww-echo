# Compatibility shim for the old capture module path.
from ww_engine.device.capture_methods import *
from ww_engine.device.capture_methods import bitblt as _bitblt


def __getattr__(name):
    if name == "render_full":
        return _bitblt.render_full
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
