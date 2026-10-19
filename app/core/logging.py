from __future__ import annotations

import logging


def configure_logging() -> None:
    """设置全局日志格式；业务模块只需通过 logging.getLogger(__name__) 输出日志。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
