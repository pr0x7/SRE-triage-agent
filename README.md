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

## The Rehearsed Demo Sequence

To show off the full power of the agent in a live demo, follow these exact steps:

1. **Setup**: Have your terminal open on the left and [LangSmith / LangGraph Studio](https://smith.langchain.com) open on the right.
2. **Trigger**: Run `python scripts/run_incident.py --incident incidents/sample_n_plus_one.json`
3. **Trace the Fan-out**: Look at LangSmith. Point out the three subagents executing in parallel to gather context.
4. **Repro Confirmation**: Show the terminal logging: `✅ Bug reproduced successfully in sandbox`.
5. **The Approval Gate**: The terminal will pause with a giant `🚨 HUMAN APPROVAL REQUIRED 🚨` prompt, showing the exact code diff. 
6. **Rejecting a Bad Patch (Optional)**: If you manually reject it, or if the Rubric Grader catches an issue (like swallowed exceptions), point out the terminal output: `🌲 Branching... ⏪ Rewinding checkpoint`. The agent time-travels back to triage and tries the next best hypothesis!
7. **Memory Usage**: Once resolved, run the exact same command again. The agent will instantly print: `I've seen this before... jumping to known fix` and bypass the entire parallel investigation phase!

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
