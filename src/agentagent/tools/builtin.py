"""Built-in tool adapters."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentagent.tools.base import BaseTool

if TYPE_CHECKING:
    from agentagent.core.events import RunContext
    from agentagent.core.historian import Historian
    from agentagent.tools.base import ToolRegistry


# ── File safety constants ────────────────────────────────────
MAX_FILE_SIZE_BYTES = 1_048_576  # 1 MB per file
MAX_FILE_COUNT = 200
MAX_WORKSPACE_BYTES = 52_428_800  # 50 MB total


class CodeExecutionTool(BaseTool):
    """Execute code in a subprocess. Supports Python, Node, shell.

    This is not a sandbox: the code runs with the server's privileges. Its
    working directory is the project workspace and the timeout is the only limit.
    """

    def __init__(self, work_dir: str | None = None, timeout: int = 30) -> None:
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="agentagent_")
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return (
            "Execute code in a subprocess whose working directory is the project "
            "workspace. Supports Python, JavaScript/Node, and shell commands. "
            "Returns stdout, stderr, and exit code."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "shell"],
                    "description": "The language to execute.",
                },
                "code": {
                    "type": "string",
                    "description": "The code to execute.",
                },
            },
            "required": ["language", "code"],
        }

    async def execute(self, **kwargs: Any) -> str:
        language = kwargs["language"]
        code = kwargs["code"]

        cmd_map = {
            "python": ["python3", "-c", code],
            "javascript": ["node", "-e", code],
            "shell": ["sh", "-c", code],
        }
        cmd = cmd_map.get(language)
        if not cmd:
            return json.dumps({"error": f"Unsupported language: {language}"})

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._work_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            return json.dumps({
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace")[:5000],
                "stderr": stderr.decode(errors="replace")[:2000],
            })
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return json.dumps({"error": "Execution timed out", "timeout": self._timeout})
        except Exception as e:
            return json.dumps({"error": str(e)})


class FileSystemTool(BaseTool):
    """Read, write, and list files within a scoped project directory."""

    def __init__(
        self,
        work_dir: str | None = None,
        run_context: "RunContext | None" = None,
    ) -> None:
        self._work_dir = Path(work_dir or tempfile.mkdtemp(prefix="agentagent_"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._run_context = run_context

    @property
    def name(self) -> str:
        return "file_system"

    @property
    def description(self) -> str:
        return (
            "Read, write, and list files within the project directory. "
            "Use this to create source code files, read existing code, or list directory contents."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "mkdir"],
                    "description": "The file system action to perform.",
                },
                "path": {
                    "type": "string",
                    "description": "Relative path within the project directory.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for 'write' action).",
                },
            },
            "required": ["action", "path"],
        }

    def _count_workspace(self) -> tuple[int, int]:
        """Return (file_count, total_bytes) under the workspace root."""
        count = 0
        total = 0
        for p in self._work_dir.rglob("*"):
            if p.is_file():
                count += 1
                total += p.stat().st_size
        return count, total

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        rel_path = kwargs["path"]

        # Prevent path traversal
        resolved = (self._work_dir / rel_path).resolve()
        if not str(resolved).startswith(str(self._work_dir.resolve())):
            return json.dumps({"error": "Path traversal not allowed"})

        if action == "read":
            if not resolved.exists():
                return json.dumps({"error": f"File not found: {rel_path}"})
            content = resolved.read_text(errors="replace")
            return json.dumps({"content": content[:10000]})

        elif action == "write":
            content = kwargs.get("content", "")
            content_bytes = len(content.encode())

            # Safety: per-file size limit
            if content_bytes > MAX_FILE_SIZE_BYTES:
                return json.dumps({
                    "error": f"File too large ({content_bytes} bytes). Maximum is {MAX_FILE_SIZE_BYTES} bytes."
                })

            # Safety: workspace limits
            file_count, total_bytes = self._count_workspace()
            if not resolved.exists() and file_count >= MAX_FILE_COUNT:
                return json.dumps({
                    "error": f"File limit reached ({MAX_FILE_COUNT} files). Delete unused files first."
                })
            if total_bytes + content_bytes > MAX_WORKSPACE_BYTES:
                return json.dumps({
                    "error": f"Workspace size limit reached ({MAX_WORKSPACE_BYTES // 1_048_576} MB)."
                })

            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)

            # Emit FILE_WRITTEN event
            if self._run_context:
                from agentagent.core.events import Event, EventType
                await self._run_context.event_bus.emit(Event(
                    type=EventType.FILE_WRITTEN,
                    data={"path": rel_path, "size": content_bytes},
                    project_id=self._run_context.project_id,
                ))

            return json.dumps({"status": "written", "path": rel_path})

        elif action == "list":
            if not resolved.exists():
                return json.dumps({"error": f"Directory not found: {rel_path}"})
            entries = [
                f"{e.name}/" if e.is_dir() else e.name
                for e in sorted(resolved.iterdir())
            ]
            return json.dumps({"entries": entries})

        elif action == "mkdir":
            resolved.mkdir(parents=True, exist_ok=True)
            return json.dumps({"status": "created", "path": rel_path})

        return json.dumps({"error": f"Unknown action: {action}"})


class WebSearchTool(BaseTool):
    """Simulated web search — placeholder for real search API integration."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information. Useful for market research, "
            "competitive analysis, and technical documentation lookup."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        return json.dumps({
            "note": "Web search is a placeholder. Integrate a real search API (SerpAPI, Tavily, etc.) for production.",
            "query": query,
            "results": [],
        })


class DocumentEditorTool(BaseTool):
    """Create and edit structured documents (PRDs, specs, etc.)."""

    def __init__(self, work_dir: str | None = None) -> None:
        self._work_dir = Path(work_dir or tempfile.mkdtemp(prefix="agentagent_docs_"))
        self._work_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "document_editor"

    @property
    def description(self) -> str:
        return (
            "Create and edit structured documents like PRDs, vision documents, "
            "design specs, and technical specs. Documents are stored as markdown files."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "append", "replace_section"],
                    "description": "The document action to perform.",
                },
                "filename": {
                    "type": "string",
                    "description": "Document filename (e.g. 'prd.md').",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write/append.",
                },
                "section": {
                    "type": "string",
                    "description": "Section heading for replace_section action.",
                },
            },
            "required": ["action", "filename"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        filename = kwargs["filename"]

        resolved = (self._work_dir / filename).resolve()
        if not str(resolved).startswith(str(self._work_dir.resolve())):
            return json.dumps({"error": "Path traversal not allowed"})

        if action == "create":
            content = kwargs.get("content", "")
            resolved.write_text(content)
            return json.dumps({"status": "created", "filename": filename})

        elif action == "read":
            if not resolved.exists():
                return json.dumps({"error": f"Document not found: {filename}"})
            return json.dumps({"content": resolved.read_text()[:10000]})

        elif action == "append":
            content = kwargs.get("content", "")
            with resolved.open("a") as f:
                f.write("\n" + content)
            return json.dumps({"status": "appended", "filename": filename})

        elif action == "replace_section":
            section = kwargs.get("section", "")
            content = kwargs.get("content", "")
            if not resolved.exists():
                return json.dumps({"error": f"Document not found: {filename}"})
            doc_text = resolved.read_text()
            # Find section by heading
            import re
            pattern = rf"(^#{1,3}\s+{re.escape(section)}\s*$)(.*?)(?=^#{1,3}\s|\Z)"
            match = re.search(pattern, doc_text, re.MULTILINE | re.DOTALL)
            if match:
                new_doc = doc_text[: match.start(2)] + "\n" + content + "\n" + doc_text[match.end(2):]
                resolved.write_text(new_doc)
                return json.dumps({"status": "section_replaced", "section": section})
            return json.dumps({"error": f"Section not found: {section}"})

        return json.dumps({"error": f"Unknown action: {action}"})


def create_default_registry(
    work_dir: str | None = None,
    run_context: "RunContext | None" = None,
    historian: "Historian | None" = None,
) -> "ToolRegistry":
    """Create a ToolRegistry populated with all built-in tools.

    If *run_context* is provided and its mode is ``"interactive"``, the
    ``request_clarification`` tool is registered.  The ``signal_leader``
    tool is always registered when a context is present.
    """
    from agentagent.tools.base import ToolRegistry

    registry = ToolRegistry()
    registry.register(CodeExecutionTool(work_dir=work_dir))
    registry.register(FileSystemTool(work_dir=work_dir, run_context=run_context))
    registry.register(WebSearchTool())
    registry.register(DocumentEditorTool(work_dir=work_dir))

    if historian:
        registry.register(AskHistorianTool(historian))

    if run_context:
        registry.register(SignalLeaderTool(run_context))
        if run_context.mode == "interactive":
            registry.register(RequestClarificationTool(run_context))

    return registry


# ── Coordination tools ───────────────────────────────────────


class AskHistorianTool(BaseTool):
    """Let any agent query the project historian for prior decisions, context, and rationale."""

    def __init__(self, historian: "Historian") -> None:
        from agentagent.core.historian import Historian  # noqa: F811

        self._historian = historian

    @property
    def name(self) -> str:
        return "ask_historian"

    @property
    def description(self) -> str:
        return (
            "Ask the project historian a question about prior decisions, discussion "
            "summaries, open questions, or related context. Use this when you need "
            "to understand why a decision was made, what was discussed previously, "
            "or whether a topic has already been addressed."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the historian.",
                },
            },
            "required": ["question"],
        }

    async def execute(self, **kwargs: Any) -> str:
        question = kwargs["question"]
        response = await self._historian.query(question)
        return json.dumps({"answer": response.content})


class SignalLeaderTool(BaseTool):
    """Allow an agent to flag an issue to the team leader during parallel work."""

    def __init__(self, run_context: "RunContext") -> None:
        self._ctx = run_context

    @property
    def name(self) -> str:
        return "signal_leader"

    @property
    def description(self) -> str:
        return (
            "Signal an issue, conflict, or important observation to the team "
            "leader.  Use this when you discover something during execution that "
            "other team members or the leader should know about (e.g. conflicting "
            "requirements, a shared dependency, a blocking question)."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Description of the issue or observation.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "How urgent this signal is.",
                },
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> str:
        message = kwargs["message"]
        severity = kwargs.get("severity", "info")
        await self._ctx.agent_channel.put({
            "message": message,
            "severity": severity,
        })
        return json.dumps({"status": "signal_sent"})


class RequestClarificationTool(BaseTool):
    """Ask the user a clarifying question and wait for a response."""

    TIMEOUT_SECONDS = 120

    def __init__(self, run_context: "RunContext") -> None:
        self._ctx = run_context

    @property
    def name(self) -> str:
        return "request_clarification"

    @property
    def description(self) -> str:
        return (
            "Ask the user a clarifying question when you genuinely cannot "
            "proceed without more information.  Batch multiple questions into "
            "a single call.  Prefer making a reasonable assumption over asking. "
            "Only use this when the ambiguity would lead to fundamentally "
            "different implementations."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question(s) to ask the user.",
                },
            },
            "required": ["question"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from agentagent.core.events import Event, EventType

        question = kwargs["question"]

        # Emit event so the UI shows the question
        await self._ctx.event_bus.emit(Event(
            type=EventType.USER_INPUT_REQUESTED,
            data={"question": question},
            project_id=self._ctx.project_id,
        ))

        # Wait for the user to respond (or timeout)
        try:
            response = await asyncio.wait_for(
                self._ctx.message_queue.get(), timeout=self.TIMEOUT_SECONDS
            )
            answer = response.get("message", "")

            await self._ctx.event_bus.emit(Event(
                type=EventType.USER_INPUT_RECEIVED,
                data={"question": question, "answer": answer},
                project_id=self._ctx.project_id,
            ))

            return json.dumps({"answer": answer})
        except asyncio.TimeoutError:
            return json.dumps({
                "answer": "No user response received within the timeout. "
                "Proceed with your best judgment."
            })
