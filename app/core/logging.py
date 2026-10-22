from __future__ import annotations

#   核心基础设施模块：集中管理配置、日志、限流和运行时状态。

import logging


#     configure_logging：完成本模块的一步处理，并把结果返回给调用方。
def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
