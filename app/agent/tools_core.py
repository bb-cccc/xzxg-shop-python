from __future__ import annotations

 

from app.agent.tools_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class ToolRegistryCoreMixin:
    def __init__(self, repository: SQLRepository, settings=None) -> None:
        self.repository = repository
        self.settings = settings
