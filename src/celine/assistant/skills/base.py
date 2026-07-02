from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

ProgressCallback = Callable[[str], Awaitable[None]]


class Skill(ABC):

    name: str
    description: str = ""

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        ...

    def handles(self, tool_name: str) -> bool:
        return any(
            t["function"]["name"] == tool_name for t in self.get_tools()
        )

    def get_system_prompt_fragment(self) -> str | None:
        return None
