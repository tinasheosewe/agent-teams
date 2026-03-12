"""Orchestrator — top-level entry point for running projects.

Loads config, instantiates teams/forum, manages project lifecycle,
handles user interaction, and tracks costs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agentagent.config import CompanyConfig, load_config
from agentagent.core.events import Event, EventBus, EventType
from agentagent.core.forum import ProgramManager, WorkflowState
from agentagent.core.team import Team, TeamOutput
from agentagent.store.database import Database
from agentagent.store.repository import Repository
from agentagent.store.vector import VectorStore
from agentagent.tools.builtin import create_default_registry

logger = logging.getLogger(__name__)

# Rough pricing per 1M tokens (GPT-4o-mini as reference)
COST_PER_1M_INPUT = 0.15
COST_PER_1M_OUTPUT = 0.60


class ProjectStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class ProjectState:
    """Current state of a running project."""

    id: str
    prompt: str
    config_name: str
    config_path: str = ""
    status: ProjectStatus = ProjectStatus.CREATED
    workflow_state: WorkflowState | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost: float = 0.0
    user_messages: list[dict[str, str]] = field(default_factory=list)


class Orchestrator:
    """Top-level controller for the AgentAgent framework.

    Responsibilities:
    - Load config and instantiate teams
    - Route between single-team and multi-team modes
    - Handle user input (participation, veto, escape hatches)
    - Track cost and project state
    """

    def __init__(self, db_path: str = "data/agentagent.db", work_dir: str = "workspace") -> None:
        self._db = Database(Path(db_path))
        self._vector = VectorStore()
        self._repo = Repository(self._db, self._vector)
        self._work_dir = work_dir
        self._projects: dict[str, ProjectState] = {}
        self._event_bus = EventBus()
        self._pending_escalations: dict[str, list[dict[str, Any]]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._cancel_flags: dict[str, bool] = {}

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def initialize(self) -> None:
        """Initialize the database."""
        await self._db.initialize()

    async def shutdown(self) -> None:
        await self._db.close()

    async def create_project(
        self, prompt: str, config_path: str
    ) -> ProjectState:
        """Create a new project from a user prompt and config file.

        Returns the ProjectState with a unique ID.
        """
        config = load_config(config_path)
        project_id = uuid.uuid4().hex[:12]

        state = ProjectState(
            id=project_id,
            prompt=prompt,
            config_name=config.name,
            config_path=config_path,
        )
        self._projects[project_id] = state

        logger.info("Created project %s: %s", project_id, prompt[:100])
        return state

    async def run_project(self, project_id: str) -> ProjectState:
        """Run a project through the full workflow.

        For single-team configs: directly runs the team.
        For multi-team configs: instantiates the forum and Program Manager.
        """
        state = self._projects.get(project_id)
        if not state:
            raise ValueError(f"Project not found: {project_id}")

        state.status = ProjectStatus.RUNNING
        config = load_config(
            self._find_config_path(state.config_name)
        )

        # Create tool registry scoped to this project
        project_work_dir = f"{self._work_dir}/{project_id}"
        tool_registry = create_default_registry(work_dir=project_work_dir)

        # Create teams
        teams: dict[str, Team] = {}
        for team_cfg in config.teams:
            teams[team_cfg.name] = Team(
                config=team_cfg,
                repository=self._repo,
                tool_registry=tool_registry,
                project_id=project_id,
                event_bus=self._event_bus,
                historian_model=config.historian_model,
                stenographer_model=config.stenographer_model,
            )

        try:
            if len(config.teams) == 1:
                # Single-team mode — run directly
                state = await self._run_single_team(state, config, teams)
            else:
                # Multi-team mode — use forum + Program Manager
                state = await self._run_multi_team(state, config, teams)
        except Exception:
            state.status = ProjectStatus.FAILED
            logger.exception("Project %s failed", project_id)
            raise

        return state

    async def _run_single_team(
        self,
        state: ProjectState,
        config: CompanyConfig,
        teams: dict[str, Team],
    ) -> ProjectState:
        """Run a single-team project."""
        team = next(iter(teams.values()))
        workflow_step = config.workflow[0] if config.workflow else None

        output = await team.execute_task(
            task=state.prompt,
            output_artifact_types=workflow_step.output if workflow_step else None,
            gate_criteria=workflow_step.gate_criteria.model_dump() if workflow_step else None,
        )

        state.total_input_tokens = output.total_input_tokens
        state.total_output_tokens = output.total_output_tokens
        state.estimated_cost = self._estimate_cost(
            output.total_input_tokens, output.total_output_tokens
        )
        state.status = ProjectStatus.COMPLETED
        return state

    async def _run_multi_team(
        self,
        state: ProjectState,
        config: CompanyConfig,
        teams: dict[str, Team],
    ) -> ProjectState:
        """Run a multi-team project through the forum."""

        async def escalation_handler(message: str, data: dict[str, Any]) -> str:
            """Handle escalations from the Program Manager."""
            escalation = {"message": message, "data": data}
            self._pending_escalations.setdefault(state.id, []).append(escalation)

            if self._event_bus:
                await self._event_bus.emit(Event(
                    type=EventType.FORUM_ESCALATION,
                    data=escalation,
                    project_id=state.id,
                ))

            # For now, auto-approve escalations (user can intervene via API)
            return "acknowledged"

        pm = ProgramManager(
            config=config,
            teams=teams,
            repository=self._repo,
            event_bus=self._event_bus,
            project_id=state.id,
            escalation_handler=escalation_handler,
            pause_event=self._pause_events.get(state.id),
        )

        workflow_state = await pm.run_workflow(state.prompt)

        state.workflow_state = workflow_state
        state.total_input_tokens = workflow_state.total_input_tokens
        state.total_output_tokens = workflow_state.total_output_tokens
        state.estimated_cost = self._estimate_cost(
            workflow_state.total_input_tokens, workflow_state.total_output_tokens
        )
        state.status = ProjectStatus.COMPLETED if workflow_state.is_complete else ProjectStatus.FAILED

        if self._event_bus:
            await self._event_bus.emit(Event(
                type=EventType.COST_UPDATE,
                data={
                    "input_tokens": state.total_input_tokens,
                    "output_tokens": state.total_output_tokens,
                    "estimated_cost": state.estimated_cost,
                },
                project_id=state.id,
            ))

        return state

    async def send_user_message(
        self, project_id: str, message: str, action: str = "message"
    ) -> dict[str, Any]:
        """Handle user input during a running project.

        Actions:
        - message: participate in the current discussion
        - veto: override a decision
        - skip: skip the current step
        - constrain: add a constraint
        """
        state = self._projects.get(project_id)
        if not state:
            return {"error": "Project not found"}

        state.user_messages.append({"action": action, "message": message})

        return {"status": "received", "action": action}

    def get_project_state(self, project_id: str) -> ProjectState | None:
        return self._projects.get(project_id)

    def list_projects(self) -> list[ProjectState]:
        """Return all project states."""
        return list(self._projects.values())

    def get_escalations(self, project_id: str) -> list[dict[str, Any]]:
        return self._pending_escalations.get(project_id, [])

    def register_task(self, project_id: str, task: asyncio.Task[Any]) -> None:
        """Register a background task for a project so it can be controlled."""
        self._tasks[project_id] = task
        evt = asyncio.Event()
        evt.set()  # Start unpaused
        self._pause_events[project_id] = evt
        self._cancel_flags[project_id] = False

    async def pause_project(self, project_id: str) -> dict[str, str]:
        """Pause a running project."""
        state = self._projects.get(project_id)
        if not state:
            return {"error": "Project not found"}
        if state.status != ProjectStatus.RUNNING:
            return {"error": f"Project is {state.status.value}, not running"}
        evt = self._pause_events.get(project_id)
        if evt:
            evt.clear()  # Block next check_pause call
        state.status = ProjectStatus.PAUSED
        return {"status": "paused"}

    async def resume_project(self, project_id: str) -> dict[str, str]:
        """Resume a paused project."""
        state = self._projects.get(project_id)
        if not state:
            return {"error": "Project not found"}
        if state.status != ProjectStatus.PAUSED:
            return {"error": f"Project is {state.status.value}, not paused"}
        state.status = ProjectStatus.RUNNING
        evt = self._pause_events.get(project_id)
        if evt:
            evt.set()  # Unblock
        return {"status": "running"}

    async def kill_project(self, project_id: str) -> dict[str, str]:
        """Kill (cancel) a running or paused project."""
        state = self._projects.get(project_id)
        if not state:
            return {"error": "Project not found"}
        if state.status not in (ProjectStatus.RUNNING, ProjectStatus.PAUSED):
            return {"error": f"Project is {state.status.value}, cannot kill"}
        self._cancel_flags[project_id] = True
        # Unblock if paused so the task can see the cancel flag
        evt = self._pause_events.get(project_id)
        if evt:
            evt.set()
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()
        state.status = ProjectStatus.FAILED
        return {"status": "killed"}

    def list_configs(self) -> list[dict[str, str]]:
        """List available configuration files."""
        overlays_dir = Path("configs/overlays")
        configs: list[dict[str, str]] = []
        if not overlays_dir.exists():
            return configs
        for f in sorted(overlays_dir.glob("*.yaml")):
            try:
                import yaml
                with f.open() as fh:
                    raw = yaml.safe_load(fh)
                name = raw.get("company", {}).get("name", f.stem)
                desc = raw.get("company", {}).get("description", "")
                teams_list = raw.get("company", {}).get("teams", [])
                team_names = [t.get("name", "") for t in teams_list]
                configs.append({
                    "path": str(f),
                    "name": name,
                    "description": desc,
                    "teams": team_names,
                })
            except Exception:
                continue
        return configs

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * COST_PER_1M_INPUT
            + output_tokens / 1_000_000 * COST_PER_1M_OUTPUT
        )

    def _find_config_path(self, config_name: str) -> str:
        """Find the config file path. Searches configs/overlays/ directory."""
        overlays_dir = Path("configs/overlays")
        # Match by name in YAML content
        slug = config_name.lower().replace(' ', '_')
        candidate = overlays_dir / f"{slug}.yaml"
        if candidate.exists():
            return str(candidate)
        # Search through all configs for matching name
        for f in overlays_dir.glob("*.yaml"):
            try:
                import yaml
                with f.open() as fh:
                    raw = yaml.safe_load(fh)
                if raw.get("company", {}).get("name") == config_name:
                    return str(f)
            except Exception:
                continue
        # Fallback — return first available
        for f in overlays_dir.glob("*.yaml"):
            return str(f)
        return f"configs/overlays/{slug}.yaml"
