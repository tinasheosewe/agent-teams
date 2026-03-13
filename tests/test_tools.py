"""Tests for the tool plugin system."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentagent.tools.base import BaseTool, ToolRegistry
from agentagent.tools.builtin import (
    AskHistorianTool,
    CodeExecutionTool,
    DocumentEditorTool,
    FileSystemTool,
    WebSearchTool,
    create_default_registry,
)


# ── ToolRegistry tests ──────────────────────────────────────


class DummyTool(BaseTool):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy tool"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}}

    async def execute(self, **kwargs) -> str:
        return json.dumps({"x": kwargs.get("x", "")})


def test_registry_register_and_get():
    reg = ToolRegistry()
    tool = DummyTool()
    reg.register(tool)
    assert reg.get("dummy") is tool
    assert reg.get("nonexistent") is None


def test_registry_list_tools():
    reg = ToolRegistry()
    reg.register(DummyTool())
    assert "dummy" in reg.list_tools()


def test_registry_get_specs():
    reg = ToolRegistry()
    reg.register(DummyTool())
    specs = reg.get_specs(["dummy", "nonexistent"])
    assert len(specs) == 1
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "dummy"


def test_tool_to_function_spec():
    tool = DummyTool()
    spec = tool.to_function_spec()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "dummy"
    assert spec["function"]["description"] == "A dummy tool"
    assert "properties" in spec["function"]["parameters"]


# ── FileSystem tool tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_filesystem_write_and_read(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))

    result = json.loads(await tool.execute(action="write", path="test.txt", content="hello"))
    assert result["status"] == "written"

    result = json.loads(await tool.execute(action="read", path="test.txt"))
    assert result["content"] == "hello"


@pytest.mark.asyncio
async def test_filesystem_list(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))
    await tool.execute(action="write", path="a.txt", content="a")
    await tool.execute(action="write", path="b.txt", content="b")

    result = json.loads(await tool.execute(action="list", path="."))
    assert "a.txt" in result["entries"]
    assert "b.txt" in result["entries"]


@pytest.mark.asyncio
async def test_filesystem_mkdir(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))
    result = json.loads(await tool.execute(action="mkdir", path="subdir"))
    assert result["status"] == "created"


@pytest.mark.asyncio
async def test_filesystem_path_traversal_blocked(tmp_path):
    tool = FileSystemTool(work_dir=str(tmp_path))
    result = json.loads(await tool.execute(action="read", path="../../etc/passwd"))
    assert "error" in result


# ── Document Editor tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_document_editor_create_and_read(tmp_path):
    tool = DocumentEditorTool(work_dir=str(tmp_path))

    result = json.loads(await tool.execute(action="create", filename="doc.md", content="# Title"))
    assert result["status"] == "created"

    result = json.loads(await tool.execute(action="read", filename="doc.md"))
    assert result["content"] == "# Title"


@pytest.mark.asyncio
async def test_document_editor_append(tmp_path):
    tool = DocumentEditorTool(work_dir=str(tmp_path))
    await tool.execute(action="create", filename="doc.md", content="# Title")
    await tool.execute(action="append", filename="doc.md", content="## Section")

    result = json.loads(await tool.execute(action="read", filename="doc.md"))
    assert "## Section" in result["content"]


@pytest.mark.asyncio
async def test_document_editor_path_traversal_blocked(tmp_path):
    tool = DocumentEditorTool(work_dir=str(tmp_path))
    result = json.loads(await tool.execute(action="read", filename="../../../etc/passwd"))
    assert "error" in result


# ── Code Execution tool tests ────────────────────────────────


@pytest.mark.asyncio
async def test_code_execution_python(tmp_path):
    tool = CodeExecutionTool(work_dir=str(tmp_path))
    result = json.loads(await tool.execute(language="python", code="print('hello')"))
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_code_execution_timeout(tmp_path):
    tool = CodeExecutionTool(work_dir=str(tmp_path), timeout=1)
    result = json.loads(await tool.execute(language="python", code="import time; time.sleep(10)"))
    assert "error" in result or result.get("exit_code") != 0


@pytest.mark.asyncio
async def test_code_execution_unsupported_language(tmp_path):
    tool = CodeExecutionTool(work_dir=str(tmp_path))
    result = json.loads(await tool.execute(language="cobol", code="DISPLAY 'HI'"))
    assert "error" in result


# ── Web Search tool tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_placeholder():
    tool = WebSearchTool()
    result = json.loads(await tool.execute(query="test query"))
    assert "note" in result
    assert result["query"] == "test query"


# ── Default Registry ─────────────────────────────────────────


def test_create_default_registry(tmp_path):
    reg = create_default_registry(work_dir=str(tmp_path))
    tools = reg.list_tools()
    assert "code_execution" in tools
    assert "file_system" in tools
    assert "web_search" in tools
    assert "document_editor" in tools


def test_create_default_registry_with_historian(tmp_path):
    """Registry includes ask_historian when historian is provided."""
    historian = MagicMock()
    reg = create_default_registry(work_dir=str(tmp_path), historian=historian)
    assert "ask_historian" in reg.list_tools()


def test_create_default_registry_without_historian(tmp_path):
    """Registry does not include ask_historian when historian is None."""
    reg = create_default_registry(work_dir=str(tmp_path))
    assert "ask_historian" not in reg.list_tools()


# ── AskHistorianTool tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_ask_historian_tool():
    """AskHistorianTool delegates to historian.query() and returns content."""
    mock_response = MagicMock()
    mock_response.content = "The team decided to use PostgreSQL because..."
    historian = MagicMock()
    historian.query = AsyncMock(return_value=mock_response)

    tool = AskHistorianTool(historian)
    result = json.loads(await tool.execute(question="Why did we choose PostgreSQL?"))

    assert result["answer"] == "The team decided to use PostgreSQL because..."
    historian.query.assert_called_once_with("Why did we choose PostgreSQL?")


def test_ask_historian_tool_spec():
    """AskHistorianTool has a valid function spec."""
    historian = MagicMock()
    tool = AskHistorianTool(historian)
    spec = tool.to_function_spec()

    assert spec["type"] == "function"
    assert spec["function"]["name"] == "ask_historian"
    assert "question" in spec["function"]["parameters"]["properties"]
