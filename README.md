# AgentAgent

**Multi-agent collaborative framework** — give it an idea, and teams of AI agents plan, design, build, and review it.

The repository is named `agent-teams`. The Python package, the CLI and the web UI are all called AgentAgent (`agentagent`).

A project runs through a pipeline of teams: management, product, design, architecture, engineering and QA in the shipped configuration. A team is a few expert agents plus a moderator, a historian and a stenographer. The experts debate on a shared board until they converge, do the work in one of four interaction modes, then reflect on the result. A Program Manager agent checks each team's output against a gate before the next team starts. Every event is streamed to a React dashboard, from which a run can be paused, resumed or stopped.

This is a prototype. Read [Limitations](#limitations) before running it: agents execute code on the machine that hosts the server.

## Architecture

```
User Prompt
    ↓
Orchestrator
    ↓
┌─────────────────────────────────────────┐
│ Forum (multi-team) or Direct (single)   │
│                                         │
│  ┌─────────┐  ┌─────────┐  ┌────────┐  │
│  │  Team 1  │  │  Team 2  │  │ Team N │  │
│  │ Mod+Exp  │  │ Mod+Exp  │  │ Mod+Ex │  │
│  └─────────┘  └─────────┘  └────────┘  │
│         ↑↓           ↑↓                 │
│    ┌──────────┐ ┌──────────┐            │
│    │ Historian │ │Steno     │            │
│    │  (read)  │ │ (write)  │            │
│    └──────────┘ └──────────┘            │
│         ↓           ↓                   │
│    ┌──────────────────────┐             │
│    │   Knowledge Store     │             │
│    │  SQLite + ChromaDB    │             │
│    └──────────────────────┘             │
└─────────────────────────────────────────┘
    ↓
REST API + WebSocket Events → React Dashboard
```

### Core Concepts

- **Board deliberation** (`core/deliberation.py`): agents take turns in round-robin. A turn is a structured response, constrained by a JSON schema, that raises new points, reacts to existing ones (agree, disagree, question), amends a point or passes. Points are versioned: an amendment creates a new version and discards the reactions to the old one. A point is in consensus once every other agent has reacted without disagreeing, contested if anyone disagrees, and open otherwise. The discussion ends when every agent has passed with nothing to add, or at the turn limit. The moderator then synthesises the board, and contested points are carried forward as open items.
- **Think, execute, reflect** (`core/moderator.py`): with `enable_deliberation` on, the moderator runs one deliberation before work starts, which also selects the interaction mode, then alternates execution and a reflecting deliberation until the team accepts the output, a second revision is requested, or the round limit is reached.
- **Interaction Modes** (`core/modes.py`): Generative (independent proposals, peer scoring, the winner folds in the others' ideas), Evaluative (independent structured reviews pooled by severity), Execution (a leader decomposes the task, sub-tasks run in dependency layers ordered with Kahn's algorithm, the leader integrates), Decision (options with pros, cons and risks, then a vote).
- **Forum + Program Manager** (`core/forum.py`): multi-team orchestration over the workflow defined in the configuration. A step waits for the gates it depends on, steps marked as parallel run concurrently, and the Program Manager agent judges each output as approved, approved with notes, or returned. A returned step is retried with the gate's feedback, three attempts at most, and can send work back to an earlier step. Unless the run request names the steps to execute, the Program Manager first classifies the request; for a simple one only the `engineering` and `qa` steps run.
- **Knowledge Store** (`store/`): decisions, discussion summaries, artifacts, transcripts and open questions in SQLite, indexed in ChromaDB for semantic search.
- **Historian** (`core/historian.py`): RAG agent that briefs each team with relevant context before it starts (push) and answers queries from any expert through the `ask_historian` tool (pull).
- **Stenographer** (`core/stenographer.py`): compresses a team's transcript into a summary, decisions and open questions and writes them to the store. Agents themselves are stateless.
- **Structured output** (`core/schemas.py`): responses the code acts on are parsed into Pydantic models. Most call sites fall back to a conservative default when a response does not validate.
- **Run control** (`core/events.py`): a `RunContext` carries pause, cancel, the user message queue and an agent-to-leader signal channel through the whole call chain (Forum → Team → Moderator → Mode → Agent).
- **Tool Plugin System** (`tools/`): extensible via `BaseTool` subclasses. Built in: file I/O confined to the project workspace with size and count limits, a document editor, code execution, `ask_historian`, `signal_leader`, `request_clarification`, and a web search placeholder that returns no results.
- **Dashboard** (`web/`): React, Zustand and Tailwind over the REST API and one WebSocket per project. It shows the pipeline as a DAG, a timeline of events, the deliberation board as Consensus / Open / Contested columns, and a side panel with rounds, decisions, artifacts, transcripts and gate results.

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- An OpenAI API key. The shipped configuration uses `gpt-4o-mini` for every agent, through [LiteLLM](https://docs.litellm.ai/).

### Setup

```bash
# Clone and set up Python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set your LLM API key
export OPENAI_API_KEY="sk-..."

# Install frontend
cd web && npm install && cd ..
```

### Run

Run both commands from the repository root: the server resolves `configs/`, `data/` and `workspace/` relative to the working directory.

```bash
# Terminal 1: Start the API server (http://127.0.0.1:8000)
source .venv/bin/activate
agentagent serve

# Terminal 2: Start the frontend dev server
cd web && npm run dev
```

Open http://localhost:5173, create a project (pick the configuration, describe what you want built), then press **Run** in the project view. The Vite dev server proxies `/api` and `/ws` to port 8000.

`./start.sh` does the same in one step: it creates the virtualenv and installs dependencies if they are missing, reads `OPENAI_API_KEY` from the environment or from `.env`, and starts both servers. It first kills whatever is listening on ports 8000 and 5173.

`agentagent serve` accepts `--host`, `--port` and `--reload`. It binds to `127.0.0.1` by default because the API has no authentication.

### What a run costs

A run is many LLM calls: every board turn, mode step, gate check, historian briefing and stenographer summary is one. A request that the Program Manager classifies as simple goes to the engineering and QA teams only; anything else runs all six teams. When a run ends, the dashboard shows its token totals and an estimated cost. The estimate uses fixed rates taken from `gpt-4o-mini` ($0.15 and $0.60 per million input and output tokens, in `core/orchestrator.py`) and leaves out the historian, stenographer and gate calls and the sub-task calls of execution mode, so read it as a lower bound. There is no spending cap; use **Stop** to end a run.

On first use ChromaDB downloads its default embedding model (about 80 MB) to `~/.cache/chroma`.

### Run Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

Run them from the repository root. The tests mock LiteLLM, so no API key is needed. The store tests use a real ChromaDB collection in a temporary directory, which triggers the embedding model download mentioned above the first time. The suite covers the board protocol, the moderator loop, the four modes, the historian and stenographer, the schemas, the store, the tools and the event bus. The Program Manager workflow and the web UI have no automated tests, and of the API server only the file-listing endpoint is tested.

`cd web && npm run build` type-checks and builds the frontend.

The GitHub Actions workflow in `.github/workflows/ci.yml` runs both on pushes to `main` and on pull requests: `pip install -e ".[dev]"` and `pytest tests/ -q` on Python 3.12, and `npm ci` and `npm run build` in `web/` on Node 20.

## Configuration

Domain behavior is defined in YAML files under `configs/overlays/`, one file per "company". See [`configs/overlays/software_company.yaml`](configs/overlays/software_company.yaml) for the full software engineering company configuration. The server lists every file in that directory, and the dashboard offers them when a project is created.

To create a custom domain:

```yaml
company:
  name: "My Agency"
  teams:
    - name: research
      purpose: "Research the problem space"
      experts:
        - role: researcher
          persona: "You are a domain researcher..."
          model: "gpt-4o-mini"
          tools: [web_search]
  workflow:
    - step: research
      gate: research_approved
      output: [research_report]
```

Notes on the schema (`src/agentagent/config.py`):

- A workflow `step` must have the same name as the team that performs it. `depends_on` lists gate names, `parallel_with` lists step names, and `on_fail` names the step to return to when the gate rejects the output.
- Models are LiteLLM model strings and are set per agent: `model` on an expert, `moderator_model` on a team, and `default_model` (used by the Program Manager), `historian_model` and `stenographer_model` on the company. Anything left out defaults to `gpt-4o`, except the stenographer, which defaults to `gpt-4o-mini`.
- Another provider is a matter of changing those strings and exporting that provider's key. The code relies on tool calling and on JSON-mode and JSON-schema `response_format`, so the model has to support them. Only the OpenAI configuration is shipped, and `start.sh` checks for `OPENAI_API_KEY`.
- `enable_deliberation` turns the board protocol on for a team. Without it the team runs its first preferred mode once.
- A configuration with a single team skips the forum and runs that team directly.
- The fast track for simple requests keeps only steps named `engineering` and `qa`.

## Project Structure

```
src/agentagent/
├── config.py             # Pydantic config models + YAML loader
├── cli.py                # CLI entry point (serve command)
├── api/
│   └── server.py         # FastAPI REST + WebSocket server
├── core/
│   ├── agent.py          # Stateless agent runtime with tool calling
│   ├── events.py         # Event bus for real-time streaming, RunContext
│   ├── schemas.py        # Pydantic models for structured LLM output
│   ├── deliberation.py   # Board-based deliberation protocol
│   ├── moderator.py      # Think → execute → reflect loop
│   ├── modes.py          # 4 interaction mode implementations
│   ├── historian.py      # RAG context provider (read interface)
│   ├── stenographer.py   # Discussion compressor (write interface)
│   ├── team.py           # Team container (intake → work → compress → output)
│   ├── forum.py          # Multi-team orchestration + Program Manager
│   └── orchestrator.py   # Top-level project lifecycle controller
├── store/
│   ├── models.py         # SQLAlchemy models (projects, decisions, summaries, artifacts, ...)
│   ├── database.py       # Async SQLite engine
│   ├── vector.py         # ChromaDB vector store
│   └── repository.py     # Unified read/write interface
└── tools/
    ├── base.py           # BaseTool ABC + ToolRegistry
    └── builtin.py        # Code execution, file system, web search, doc editor, coordination tools

configs/overlays/         # Company configurations (YAML)
tests/                    # pytest suite, LLM mocked
web/                      # React dashboard (Vite, TypeScript)
start.sh                  # Starts the API server and the dashboard together
```

At runtime the server creates `data/` (SQLite database and ChromaDB index) and `workspace/<project id>/` (files written by the agents). Both are ignored by git.

## Adding Tools

```python
from agentagent.tools.base import BaseTool

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"input": {"type": "string"}},
            "required": ["input"],
        }

    async def execute(self, **kwargs) -> str:
        return f"Result: {kwargs['input']}"
```

Register it in `create_default_registry()` or via the registry at runtime, then list its name under an expert's `tools` in the configuration.

## Limitations

- **Code execution is not sandboxed.** The `code_execution` tool runs model-written Python, Node or shell as a subprocess of the server, with the server's privileges, a 30-second timeout and the project workspace as working directory. In the shipped configuration the architecture, engineering and QA experts have it. Run the server in a container or a virtual machine.
- **No authentication.** Anyone who can reach the API can start runs, which spend the configured API key and execute code. Keep it on `127.0.0.1`.
- **Gates are judgments, not checks.** Gate criteria, including the `automated_checks` named in the configuration, are assessed by the Program Manager model from the team's text output. Nothing is compiled or tested by the gate. When a gate rejects a step three times the step is marked failed and an escalation event is emitted; the run does not wait for the user.
- **Steering is partly wired.** Pause, resume and stop work through the `RunContext`. The API also accepts messages during a run (`message`, `veto`, `skip`, `constrain`, `converse`), but the Program Manager reads them only between workflow steps and their handling is incomplete.
- **Web search is a placeholder** that returns an empty result list.
- **State.** Projects and the knowledge store survive a restart; the event history shown in the timeline is kept in memory only, and a project that was running when the server stopped is marked failed.
- **A run that crashes is quiet.** When a run stops on an exception, a missing API key for instance, the project is marked failed and the error is written to the server log, but no event is sent. An open dashboard keeps showing the run as running until the page is reloaded.
- **Cost figures are approximate**, as described above.

## License

MIT. See [LICENSE](LICENSE).
