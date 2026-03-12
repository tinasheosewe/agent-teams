"""Tests for the Agent runtime with mocked LLM."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.core.agent import Agent, AgentResponse, Message
from agentagent.tools.base import BaseTool, ToolRegistry


class EchoTool(BaseTool):
    """A simple test tool that echoes input."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the input"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> str:
        return json.dumps({"echo": kwargs.get("text", "")})


def _make_completion_response(content: str, tool_calls=None):
    """Create a mock litellm completion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_agent_simple_response(mock_litellm):
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("Hello world")
    )

    agent = Agent(role="tester", persona="You are a test agent.", model="gpt-4o")
    messages = [Message(role="user", content="Say hello")]
    result = await agent.run(messages)

    assert isinstance(result, AgentResponse)
    assert result.content == "Hello world"
    assert result.input_tokens == 100
    assert result.output_tokens == 50


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_agent_with_tool_calls(mock_litellm):
    # Create a tool call mock
    tc = MagicMock()
    tc.id = "call_123"
    tc.function.name = "echo"
    tc.function.arguments = '{"text": "hi"}'

    # First call returns tool call, second returns text
    mock_litellm.acompletion = AsyncMock(
        side_effect=[
            _make_completion_response("", tool_calls=[tc]),
            _make_completion_response("I echoed: hi"),
        ]
    )

    registry = ToolRegistry()
    registry.register(EchoTool())

    agent = Agent(
        role="tester",
        persona="Test agent",
        model="gpt-4o",
        tool_names=["echo"],
        tool_registry=registry,
    )
    result = await agent.run([Message(role="user", content="Echo 'hi'")])

    assert result.content == "I echoed: hi"
    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0]["name"] == "echo"


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_agent_system_prompt(mock_litellm):
    mock_litellm.acompletion = AsyncMock(
        return_value=_make_completion_response("response")
    )

    agent = Agent(role="analyst", persona="You analyze data.", model="gpt-4o")
    await agent.run([Message(role="user", content="test")])

    call_args = mock_litellm.acompletion.call_args
    messages = call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "analyst" in messages[0]["content"]
    assert "analyze data" in messages[0]["content"]


@pytest.mark.asyncio
@patch("agentagent.core.agent.litellm")
async def test_agent_max_tool_rounds(mock_litellm):
    """Agent should stop calling tools after max_tool_rounds."""
    tc = MagicMock()
    tc.id = "call_loop"
    tc.function.name = "echo"
    tc.function.arguments = '{"text": "loop"}'

    # Return tool calls every time, then final text response
    tool_response = _make_completion_response("", tool_calls=[tc])
    final_response = _make_completion_response("done")

    # max_tool_rounds=2 means we allow 2 tool rounds, then force a text response
    mock_litellm.acompletion = AsyncMock(
        side_effect=[tool_response, tool_response, tool_response, final_response]
    )

    registry = ToolRegistry()
    registry.register(EchoTool())

    agent = Agent(
        role="tester",
        persona="Test",
        model="gpt-4o",
        tool_names=["echo"],
        tool_registry=registry,
        max_tool_rounds=2,
    )
    result = await agent.run([Message(role="user", content="loop")])
    assert result.content == "done"
