from __future__ import annotations

 

from app.agent.tools_commerce import ToolRegistryCommerceMixin
from app.agent.tools_core import ToolRegistryCoreMixin
from app.agent.tools_search import ToolRegistrySearchMixin
from app.agent.tools_support import *  # noqa: F401,F403


class ToolRegistry(ToolRegistryCoreMixin, ToolRegistrySearchMixin, ToolRegistryCommerceMixin):
    """Facade composed from retrieval and commerce tool contexts."""

    pass
