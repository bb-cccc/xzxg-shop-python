from __future__ import annotations

#核心基础设施模块：集中管理配置、日志、限流和运行时状态。

import logging


#configure_logging 
def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
