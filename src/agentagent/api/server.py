"""FastAPI application — REST + WebSocket server."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentagent.core.events import Event, EventBus
from agentagent.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# Global orchestrator instance
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    assert _orchestrator is not None, "Orchestrator not initialized"
    return _orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _orchestrator
    _orchestrator = Orchestrator()
    await _orchestrator.initialize()
    yield
    await _orchestrator.shutdown()


app = FastAPI(
    title="AgentAgent",
    description="Multi-agent collaborative framework",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Models ──────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    prompt: str
    config_path: str = "configs/overlays/software_company.yaml"


class UserMessageRequest(BaseModel):
    message: str
    action: str = "message"  # message | veto | skip | constrain


class ProjectResponse(BaseModel):
    id: str
    prompt: str
    config_name: str
    status: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost: float = 0.0


# ── REST Endpoints ───────────────────────────────────────────

@app.post("/api/projects", response_model=ProjectResponse)
async def create_project(req: CreateProjectRequest) -> ProjectResponse:
    """Create a new project from a user prompt."""
    orch = get_orchestrator()
    state = await orch.create_project(req.prompt, req.config_path)
    return ProjectResponse(
        id=state.id,
        prompt=state.prompt,
        config_name=state.config_name,
        status=state.status,
    )


@app.post("/api/projects/{project_id}/run", response_model=ProjectResponse)
async def run_project(project_id: str) -> ProjectResponse:
    """Start running a project (non-blocking — streams events via WebSocket)."""
    orch = get_orchestrator()
    state = orch.get_project_state(project_id)
    if not state:
        return ProjectResponse(
            id=project_id, prompt="", config_name="", status="not_found"
        )

    # Run in background so the REST call returns immediately
    asyncio.create_task(_run_project_background(orch, project_id))

    return ProjectResponse(
        id=state.id,
        prompt=state.prompt,
        config_name=state.config_name,
        status="running",
    )


async def _run_project_background(orch: Orchestrator, project_id: str) -> None:
    try:
        await orch.run_project(project_id)
    except Exception:
        logger.exception("Background project run failed: %s", project_id)


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get the current state of a project."""
    orch = get_orchestrator()
    state = orch.get_project_state(project_id)
    if not state:
        return ProjectResponse(
            id=project_id, prompt="", config_name="", status="not_found"
        )
    return ProjectResponse(
        id=state.id,
        prompt=state.prompt,
        config_name=state.config_name,
        status=state.status,
        total_input_tokens=state.total_input_tokens,
        total_output_tokens=state.total_output_tokens,
        estimated_cost=state.estimated_cost,
    )


@app.get("/api/projects/{project_id}/decisions")
async def get_decisions(project_id: str) -> list[dict]:
    """Get all decisions for a project."""
    orch = get_orchestrator()
    decisions = await orch._repo.get_active_decisions(project_id)
    return [
        {
            "id": d.id,
            "topic": d.topic,
            "decision": d.decision_text,
            "rationale": d.rationale,
            "team": d.team,
            "status": d.status.value,
            "confidence": d.confidence,
            "created_at": d.created_at.isoformat() if d.created_at else "",
        }
        for d in decisions
    ]


@app.get("/api/projects/{project_id}/artifacts")
async def get_artifacts(project_id: str) -> list[dict]:
    """Get all artifacts for a project."""
    orch = get_orchestrator()
    artifacts = await orch._repo.get_artifacts(project_id)
    return [
        {
            "id": a.id,
            "type": a.artifact_type,
            "name": a.name,
            "content": a.content[:5000],
            "version": a.version,
            "team": a.team,
            "status": a.status.value,
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        for a in artifacts
    ]


@app.get("/api/projects/{project_id}/escalations")
async def get_escalations(project_id: str) -> list[dict]:
    """Get pending escalations for a project."""
    orch = get_orchestrator()
    return orch.get_escalations(project_id)


@app.post("/api/projects/{project_id}/message")
async def send_message(project_id: str, req: UserMessageRequest) -> dict:
    """Send a user message (participate, veto, skip, constrain)."""
    orch = get_orchestrator()
    return await orch.send_user_message(project_id, req.message, req.action)


# ── WebSocket ────────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections per project."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, project_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(project_id, []).append(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(project_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, project_id: str, data: dict) -> None:
        conns = self._connections.get(project_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.remove(ws)


_ws_manager = ConnectionManager()


@app.websocket("/ws/projects/{project_id}")
async def project_websocket(websocket: WebSocket, project_id: str) -> None:
    """WebSocket endpoint for real-time project event streaming."""
    await _ws_manager.connect(project_id, websocket)

    # Register event handler to broadcast to this project's WebSocket connections
    orch = get_orchestrator()

    async def ws_event_handler(event: Event) -> None:
        if event.project_id == project_id:
            await _ws_manager.broadcast(project_id, event.to_dict())

    orch.event_bus.subscribe(ws_event_handler)

    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages from the user via WebSocket
            try:
                msg = json.loads(data)
                action = msg.get("action", "message")
                message = msg.get("message", "")
                await orch.send_user_message(project_id, message, action)
            except json.JSONDecodeError:
                await orch.send_user_message(project_id, data, "message")
    except WebSocketDisconnect:
        _ws_manager.disconnect(project_id, websocket)
