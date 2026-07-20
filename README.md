# 🚨 SRE Incident-Triage Agent

An autonomous incident-triage agent: feed it a stack trace / log dump from a broken
service, it plans an investigation, dispatches parallel hypothesis-testing subagents,
reproduces the real root cause in an isolated sandbox, writes and verifies a patch,
pauses for human approval, and remembers the incident for next time.

## Architecture

```
Incident in (stack trace + logs)
  │
  ▼
Orchestrator (deepagents: create_deep_agent)
  │  - plans via built-in todo tool
  │  - checks memory: seen this pattern before?
  │
  ├─ memory hit ──► jump to verify-known-fix
  │
  └─ memory miss:
        Fan out PARALLEL subagents:
        ┌───────────────┬───────────────┬───────────────┐
        │ log-analyzer  │ deploy-diff   │ db-inspector  │
        └───────┬───────┴───────┬───────┴───────┬───────┘
                └───────────────┴───────────────┘
                          │
                          ▼
              Hypothesis scoring → repro-agent → patch-writer
                          │
                          ▼
              Human approval gate → rubric grading → memory store
```

## Stack

- **deepagents** — agent harness (planning, subagents, filesystem, memory, rubric)
- **LangGraph** — custom state machines (repro-agent)
- **Google Gemini** — LLM provider (free tier, zero cost)
- **Docker** — sandboxed execution backend (local, free)
- **break-o-matic** — synthetic target service with injectable bugs

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url> && cd sre-agent
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env — add your GOOGLE_API_KEY

# 3. Verify Docker sandbox works
python scripts/verify_phase0.py

# 4. Run an incident
python scripts/run_incident.py incidents/sample_n_plus_one.json
```

## Project Structure

```
sre-agent/
├── agent/                  # Core agent logic
│   ├── docker_sandbox.py   # Local Docker sandbox backend
│   ├── orchestrator.py     # Top-level agent entrypoint
│   ├── memory.py           # Persistent incident memory
│   ├── fanout.py           # Parallel hypothesis dispatch
│   ├── approval.py         # Human-in-the-loop gate
│   ├── rubric_config.py    # Grading middleware
│   └── subagents/          # Specialist subagents
├── breakomatic/            # Target service with injectable bugs
├── incidents/              # Sample incident payloads
├── evals/                  # Evaluation harness
├── dashboard/              # Streaming status UI (optional)
└── scripts/                # CLI entrypoints
```

## License

MIT
