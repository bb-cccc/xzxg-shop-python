from __future__ import annotations

# 项目脚本模块：提供可重复执行的运维入口。

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    revision = sys.argv[1] if len(sys.argv) > 1 else "head"
    command.upgrade(config, revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
