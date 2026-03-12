"""Built-in tool adapters."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


from agentagent.tools.base import BaseTool


class CodeExecutionTool(BaseTool):
    """Execute code in a sandboxed subprocess. Supports Python, Node, shell."""

    def __init__(self, work_dir: str | None = None, timeout: int = 30) -> None:
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="agentagent_")
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return (
            "Execute code in a sandboxed environment. Supports Python, JavaScript/Node, "
            "and shell commands. Returns stdout, stderr, and exit code."
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

    def __init__(self, work_dir: str | None = None) -> None:
        self._work_dir = Path(work_dir or tempfile.mkdtemp(prefix="agentagent_"))
        self._work_dir.mkdir(parents=True, exist_ok=True)

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
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
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


def create_default_registry(work_dir: str | None = None) -> "ToolRegistry":
    """Create a ToolRegistry populated with all built-in tools."""
    from agentagent.tools.base import ToolRegistry

    registry = ToolRegistry()
    registry.register(CodeExecutionTool(work_dir=work_dir))
    registry.register(FileSystemTool(work_dir=work_dir))
    registry.register(WebSearchTool())
    registry.register(DocumentEditorTool(work_dir=work_dir))
    return registry
