# AgentAgent

**Multi-agent collaborative framework** — give it an idea, and teams of AI agents plan, design, build, and deliver it.

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

- **Teams**: Groups of domain expert agents + a moderator, historian, and stenographer
- **Interaction Modes**: Generative (brainstorm), Evaluative (review), Execution (build), Decision (choose)
- **Knowledge Store**: Versioned decisions, discussion summaries, artifacts, transcripts
- **Historian**: RAG agent that briefs teams with relevant context (push) and answers queries (pull)
- **Stenographer**: Compresses discussions, extracts decisions and open questions
- **Forum + Program Manager**: Multi-team orchestration with dependency-aware workflow pipeline, gates, and escalation
- **Tool Plugin System**: Extensible via `BaseTool` subclasses (code execution, file I/O, web search, document editing)

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- An LLM API key (OpenAI, Anthropic, etc. — via [LiteLLM](https://docs.litellm.ai/))

### Setup

```bash
# Clone and set up Python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set your LLM API key
export OPENAI_API_KEY="sk-..."
# Or for other providers: export ANTHROPIC_API_KEY="..."

# Install frontend
cd web && npm install && cd ..
```

### Run

```bash
# Terminal 1: Start the API server
source .venv/bin/activate
agentagent serve

# Terminal 2: Start the frontend dev server
cd web && npm run dev
```

Open http://localhost:5173 — enter a project idea and watch the agents work.

### Run Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Configuration

Domain behavior is defined in YAML overlay files. See [`configs/overlays/software_company.yaml`](configs/overlays/software_company.yaml) for the full software engineering company configuration.

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
          tools: [web_search]
  workflow:
    - step: research
      gate: research_approved
      output: [research_report]
```

## Project Structure

```
src/agentagent/
├── config.py             # Pydantic config models + YAML loader
├── cli.py                # CLI entry point (serve command)
├── api/
│   └── server.py         # FastAPI REST + WebSocket server
├── core/
│   ├── agent.py          # Stateless agent runtime with tool calling
│   ├── events.py         # Event bus for real-time streaming
│   ├── historian.py      # RAG context provider (read interface)
│   ├── stenographer.py   # Discussion compressor (write interface)
│   ├── modes.py          # 4 interaction mode implementations
│   ├── moderator.py      # Mode selection + convergence management
│   ├── team.py           # Team container (intake → work → compress → output)
│   ├── forum.py          # Multi-team orchestration + Program Manager
│   └── orchestrator.py   # Top-level project lifecycle controller
├── store/
│   ├── models.py         # SQLAlchemy models (decisions, summaries, artifacts)
│   ├── database.py       # Async SQLite engine
│   ├── vector.py         # ChromaDB vector store
│   └── repository.py     # Unified read/write interface
└── tools/
    ├── base.py           # BaseTool ABC + ToolRegistry
    └── builtin.py        # Code execution, file system, web search, doc editor
```

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

Register it in `create_default_registry()` or via the registry at runtime.

## License

MIT
