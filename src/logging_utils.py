"""Domain 侧日志 helper：复用 `ww_engine` 已配置的 handler，但不 import engine。

`ww_engine.util.logger` 把 stdout / 文件 / UI 信号 handler 都挂在名为 `ww_engine` 的
logger 上；stdlib logging 按名字层级传播，所以 `ww_engine.<domain module>` 会自动
走到这些 handler（包括 `logs/ok-echo.log` 和运行页日志）。

这样 domain 既不用 `from ww_engine import Logger`（那会拉起整个 Qt 栈），
也不会丢掉文件日志；如果 engine 没配置（纯 CLI/离线脚本），记录按 stdlib
默认规则落到 root（warning 以上由 lastResort 打印）。
"""

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ww_engine.{name}")
