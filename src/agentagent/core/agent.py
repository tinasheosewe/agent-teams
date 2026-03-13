"""Agent runtime — stateless single-agent execution with tool support."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import litellm

from agentagent.tools.base import ToolRegistry

if TYPE_CHECKING:
    from agentagent.core.events import RunContext

logger = logging.getLogger(__name__)

# Suppress litellm noise
litellm.suppress_debug_info = True


@dataclass
class Message:
    """A single message in a conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class AgentResponse:
    """Result from a single agent turn."""

    content: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class Agent:
    """Stateless agent — takes a conversation, returns a response.

    Handles tool calling loops internally: if the LLM requests tool calls,
    the agent executes them and continues until the LLM produces a text response.
    """

    def __init__(
        self,
        role: str,
        persona: str,
        model: str = "gpt-4o",
        tool_names: list[str] | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_rounds: int = 5,
    ) -> None:
        self.role = role
        self.persona = persona
        self.model = model
        self._tool_names = tool_names or []
        self._registry = tool_registry
        self._max_tool_rounds = max_tool_rounds

    @property
    def system_prompt(self) -> str:
        return f"You are: {self.role}.\n\n{self.persona}"

    def _get_tools(self) -> list[dict[str, Any]]:
        if not self._registry or not self._tool_names:
            return []
        return self._registry.get_specs(self._tool_names)

    async def run(
        self,
        messages: list[Message],
        response_format: dict[str, Any] | None = None,
        run_context: "RunContext | None" = None,
        temperature: float | None = None,
    ) -> AgentResponse:
        """Execute a single agent turn, handling tool calls.

        Args:
            messages: The conversation history (excluding the system prompt).
            response_format: Optional litellm response_format (e.g. {"type": "json_object"}).
                When set, tool calling is disabled to avoid provider conflicts.
            run_context: Optional shared context for pause/cancel/event support.
            temperature: Optional sampling temperature override for this call.

        Returns:
            AgentResponse with the assistant's text reply and metadata.
        """
        conversation = [{"role": "system", "content": self.system_prompt}]
        conversation.extend(m.to_dict() for m in messages)

        tools = self._get_tools() if not response_format else []
        total_input_tokens = 0
        total_output_tokens = 0
        all_tool_calls: list[dict[str, Any]] = []

        for _ in range(self._max_tool_rounds + 1):
            # Interrupt check between tool rounds
            if run_context:
                await run_context.check_pause()

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": conversation,
            }
            if tools:
                kwargs["tools"] = tools
            if response_format:
                kwargs["response_format"] = response_format
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = await litellm.acompletion(**kwargs)
            choice = response.choices[0]  # type: ignore[union-attr]
            usage = response.usage  # type: ignore[union-attr]
            if usage:
                total_input_tokens += usage.prompt_tokens
                total_output_tokens += usage.completion_tokens

            msg = choice.message

            # No tool calls — we have a text response
            if not msg.tool_calls:
                return AgentResponse(
                    content=msg.content or "",
                    tool_calls_made=all_tool_calls,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Process tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
            conversation.append(assistant_msg)

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                tool_record = {"name": fn_name, "args": fn_args}
                all_tool_calls.append(tool_record)

                # Emit AGENT_TOOL_CALL event
                if run_context:
                    from agentagent.core.events import Event, EventType
                    await run_context.event_bus.emit(Event(
                        type=EventType.AGENT_TOOL_CALL,
                        data={"agent": self.role, "tool": fn_name, "args": fn_args},
                        project_id=run_context.project_id,
                    ))

                if self._registry:
                    tool = self._registry.get(fn_name)
                    if tool:
                        result = await tool.execute(**fn_args)
                    else:
                        result = json.dumps({"error": f"Unknown tool: {fn_name}"})
                else:
                    result = json.dumps({"error": "No tool registry available"})

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Fell through max tool rounds — force a final response without tools
        conversation.append({
            "role": "user",
            "content": "Please provide your final response now. Tool calling limit reached.",
        })
        response = await litellm.acompletion(model=self.model, messages=conversation)
        choice = response.choices[0]  # type: ignore[union-attr]
        usage = response.usage  # type: ignore[union-attr]
        if usage:
            total_input_tokens += usage.prompt_tokens
            total_output_tokens += usage.completion_tokens

        return AgentResponse(
            content=choice.message.content or "",
            tool_calls_made=all_tool_calls,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
