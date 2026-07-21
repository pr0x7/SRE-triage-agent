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

## Supported Stack v1 & Declarative Configuration

To generalize the agent across repositories beyond `break-o-matic`, repo owners provide an `sre-agent.yaml` configuration file.

### Scope: Supported Stack v1
- **Language**: Python 3.10+
- **Environment**: Docker containerized sandbox
- **Testing Framework**: `pytest`

### Declarative Schema (`sre-agent.yaml`)
```yaml
service_name: "my-service"
language: "python"
framework: "fastapi" # or flask, django, etc.
entrypoint: "uvicorn my_service.app:app --host 0.0.0.0 --port 8080"
build_command: "pip install -e ."
test_command: "pytest tests/"
log_source: "/tmp/app.log"
db_connection_string: "postgresql://readonly:secret@localhost:5432/mydb" # optional
deploy_remote: "origin/main" # optional
```
Sample configuration files are available at [`sre-agent.yaml`](file:///Users/prox/Desktop/SRE/sre-agent.yaml) and [`examples/sre-agent.sample.yaml`](file:///Users/prox/Desktop/SRE/examples/sre-agent.sample.yaml).

## Installation & Setup

```bash
# 1. Clone and install
git clone https://github.com/pr0x7/SRE-triage-agent.git
cd SRE-triage-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env and add your LANGSMITH_API_KEY and Groq/Gemini API keys

# 3. Verify Docker sandbox works
python scripts/verify_phase0.py
```

## Quick Start (60-Second Walkthrough)

Here is what happens when you trigger an incident:

1. **Inject a bug**: We purposely break the `break-o-matic` synthetic service (e.g. `python scripts/seed_bug.py --bug n_plus_one`).
2. **Trigger the agent**: We feed the resulting stack trace into our Orchestrator:
   ```bash
   python scripts/run_incident.py --incident incidents/sample_n_plus_one.json
   ```
3. **Parallel Fan-out**: The Orchestrator dispatches three specialist subagents (`log-analyzer`, `deploy-diff`, `db-inspector`) simultaneously. They independently gather forensic clues.
4. **Reproduction & Patch**: The `repro-agent` boots up a Docker sandbox, spins up the broken service, and writes a test script to confidently trigger the exact bug. The `patch-writer` then drops in a fix and reruns the test.
5. **Human Approval & Rubric Grading**: Before anything touches production, execution pauses. You get a clean diff. If approved, the agent self-grades the patch against strict SRE rules. If it fails, it branches, rewinds, and tries again!

## Project Structure

```
SRE-triage-agent/
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
