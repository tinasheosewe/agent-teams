"""Tool plugin system — adapter-based, extensible.

To add a new tool:
1. Subclass BaseTool
2. Define name, description, and parameters_schema
3. Implement execute()
4. Register with the ToolRegistry
"""

from __future__ import annotations

import abc
from typing import Any


class BaseTool(abc.ABC):
    """Base class for all tool adapters."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique tool name used in config and function calling."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM."""

    @property
    @abc.abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's parameters (OpenAI function calling format)."""

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool with the given parameters. Returns a string result."""

    def to_function_spec(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible function specification."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolRegistry:
    """Registry for tool adapters. Tools are looked up by name."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_specs(self, names: list[str]) -> list[dict[str, Any]]:
        """Get function calling specs for the given tool names."""
        specs: list[dict[str, Any]] = []
        for name in names:
            tool = self._tools.get(name)
            if tool:
                specs.append(tool.to_function_spec())
        return specs

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
