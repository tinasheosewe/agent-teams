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
    action: str = "message"  # message | veto | skip | constrain | converse | end_conversation
    target: str | None = None  # For converse: "pm" | "team:{name}" | "agent:{team}:{role}"


class ProjectResponse(BaseModel):
    id: str
    prompt: str
    config_name: str
    status: str
    mode: str = "interactive"
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
        mode=state.mode,
    )


@app.get("/api/projects", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    """List all projects."""
    orch = get_orchestrator()
    return [
        ProjectResponse(
            id=s.id,
            prompt=s.prompt,
            config_name=s.config_name,
            status=s.status,
            mode=s.mode,
            total_input_tokens=s.total_input_tokens,
            total_output_tokens=s.total_output_tokens,
            estimated_cost=s.estimated_cost,
        )
        for s in orch.list_projects()
    ]


class RunProjectRequest(BaseModel):
    selected_steps: list[str] | None = None


@app.post("/api/projects/{project_id}/run", response_model=ProjectResponse)
async def run_project(project_id: str, req: RunProjectRequest | None = None) -> ProjectResponse:
    """Start running a project (non-blocking — streams events via WebSocket)."""
    orch = get_orchestrator()
    state = orch.get_project_state(project_id)
    if not state:
        return ProjectResponse(
            id=project_id, prompt="", config_name="", status="not_found"
        )

    steps = set(req.selected_steps) if req and req.selected_steps else None
    # Run in background so the REST call returns immediately
    task = asyncio.create_task(_run_project_background(orch, project_id, steps))
    orch.register_task(project_id, task)

    return ProjectResponse(
        id=state.id,
        prompt=state.prompt,
        config_name=state.config_name,
        status="running",
        mode=state.mode,
    )


async def _run_project_background(orch: Orchestrator, project_id: str, selected_steps: set[str] | None = None) -> None:
    try:
        await orch.run_project(project_id, selected_steps=selected_steps)
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
        mode=state.mode,
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
    """Send a user message (participate, veto, skip, constrain, converse)."""
    orch = get_orchestrator()
    return await orch.send_user_message(
        project_id, req.message, req.action, target=req.target,
    )


@app.post("/api/projects/{project_id}/converse")
async def converse(project_id: str, req: UserMessageRequest) -> dict:
    """Start or continue a targeted conversation during a run."""
    orch = get_orchestrator()
    return await orch.send_user_message(
        project_id, req.message, "converse", target=req.target,
    )


@app.post("/api/projects/{project_id}/pause")
async def pause_project(project_id: str) -> dict:
    """Pause a running project."""
    orch = get_orchestrator()
    return await orch.pause_project(project_id)


@app.post("/api/projects/{project_id}/resume")
async def resume_project(project_id: str) -> dict:
    """Resume a paused project."""
    orch = get_orchestrator()
    return await orch.resume_project(project_id)


@app.post("/api/projects/{project_id}/kill")
async def kill_project(project_id: str) -> dict:
    """Kill (cancel) a running or paused project."""
    orch = get_orchestrator()
    return await orch.kill_project(project_id)


class SetModeRequest(BaseModel):
    mode: str  # "interactive" or "autonomous"


@app.put("/api/projects/{project_id}/mode")
async def set_project_mode(project_id: str, req: SetModeRequest) -> dict:
    """Set interactivity mode for a project."""
    orch = get_orchestrator()
    return await orch.set_project_mode(project_id, req.mode)


@app.get("/api/projects/{project_id}/files")
async def list_project_files(project_id: str) -> list[dict]:
    """List files generated by a project."""
    from pathlib import Path

    work_dir = Path(f"workspace/{project_id}")
    if not work_dir.exists():
        return []
    files: list[dict] = []
    for p in sorted(work_dir.rglob("*")):
        if p.is_file():
            files.append({
                "path": str(p.relative_to(work_dir)),
                "size": p.stat().st_size,
            })
    return files


@app.get("/api/configs")
async def list_configs() -> list[dict]:
    """List available configuration files."""
    orch = get_orchestrator()
    return orch.list_configs()


@app.get("/api/configs/{config_name}")
async def get_config_detail(config_name: str) -> dict:
    """Return full config detail for a named config."""
    import yaml
    from pathlib import Path as _Path

    overlays_dir = _Path("configs/overlays")
    for f in overlays_dir.glob("*.yaml"):
        try:
            with f.open() as fh:
                raw = yaml.safe_load(fh)
            name = raw.get("company", {}).get("name", f.stem)
            if name == config_name:
                return raw
        except Exception:
            continue
    return {"error": "Config not found"}


@app.get("/api/projects/{project_id}/summaries")
async def get_summaries(
    project_id: str, team: str | None = None, round: int | None = None
) -> list[dict]:
    """Get discussion summaries, optionally filtered by team/round."""
    orch = get_orchestrator()
    summaries = await orch._repo.get_summaries(project_id, team=team)
    result = []
    for s in summaries:
        if round is not None and s.round_number != round:
            continue
        # key_points / conclusions / unresolved_items are stored as plain text
        # Split by newline into lists for the frontend
        def _split(text: str) -> list[str]:
            return [line.strip() for line in text.split("\n") if line.strip()] if text else []

        result.append(
            {
                "id": s.id,
                "project_id": s.project_id,
                "team": s.team,
                "round_number": s.round_number,
                "topic": s.topic,
                "key_points": _split(s.key_points),
                "conclusions": _split(s.conclusions),
                "unresolved_items": _split(s.unresolved_items),
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
        )
    return result


@app.get("/api/projects/{project_id}/transcripts/{team}/{round_number}")
async def get_transcript(project_id: str, team: str, round_number: int) -> dict | None:
    """Get the transcript for a specific team round."""
    orch = get_orchestrator()
    t = await orch._repo.get_transcript(project_id, team, round_number)
    if not t:
        return {"error": "Transcript not found"}
    return {
        "id": t.id,
        "project_id": t.project_id,
        "team": t.team,
        "round_number": t.round_number,
        "content": t.content,
        "created_at": t.created_at.isoformat() if t.created_at else "",
    }


@app.get("/api/projects/{project_id}/teams")
async def get_teams(project_id: str) -> list[dict]:
    """Get team information for a project based on its config."""
    orch = get_orchestrator()
    state = orch.get_project_state(project_id)
    if not state:
        return []

    import yaml
    from pathlib import Path as _Path

    config_path = _Path(state.config_path) if state.config_path else None
    if not config_path or not config_path.exists():
        return []

    try:
        with config_path.open() as fh:
            raw = yaml.safe_load(fh)
        teams_raw = raw.get("company", {}).get("teams", [])
        return [
            {
                "name": t.get("name", ""),
                "purpose": t.get("purpose", ""),
                "experts": [e.get("name", "") for e in t.get("experts", [])],
                "max_rounds": t.get("max_rounds", 3),
            }
            for t in teams_raw
        ]
    except Exception:
        return []


@app.get("/api/projects/{project_id}/questions")
async def get_questions(project_id: str) -> list[dict]:
    """Get open questions for a project."""
    orch = get_orchestrator()
    questions = await orch._repo.get_open_questions(project_id)
    return [
        {
            "id": q.id,
            "project_id": q.project_id,
            "question": q.question,
            "raised_by": q.raised_by,
            "assigned_to": q.assigned_to,
            "priority": q.priority.value if hasattr(q.priority, "value") else str(q.priority),
            "status": q.status.value if hasattr(q.status, "value") else str(q.status),
            "answer": q.answer,
            "created_at": q.created_at.isoformat() if q.created_at else "",
        }
        for q in questions
    ]


@app.get("/api/projects/{project_id}/events")
async def get_events(
    project_id: str, type: str | None = None, limit: int | None = None
) -> list[dict]:
    """Get event history for a project from the in-memory event bus."""
    orch = get_orchestrator()
    history = orch.event_bus.get_project_history(project_id)
    if type:
        history = [e for e in history if e.get("type") == type]
    if limit:
        history = history[-limit:]
    return history


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

    # Replay any events that fired before the WebSocket connected
    for past_event in orch.event_bus.get_project_history(project_id):
        try:
            await websocket.send_json(past_event)
        except Exception:
            break

    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages from the user via WebSocket
            try:
                msg = json.loads(data)
                action = msg.get("action", "message")
                message = msg.get("message", "")
                target = msg.get("target")
                await orch.send_user_message(
                    project_id, message, action, target=target,
                )
            except json.JSONDecodeError:
                await orch.send_user_message(project_id, data, "message")
    except WebSocketDisconnect:
        _ws_manager.disconnect(project_id, websocket)
        orch.event_bus.unsubscribe(ws_event_handler)
