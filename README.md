# Autonomous SRE Incident-Triage Agent (`sre-agent`)

An autonomous, multi-agent SRE incident triage and remediation system built with **LangGraph**, **Pydantic**, and **Docker**.

`sre-agent` ingests real-time alert webhooks (Sentry, PagerDuty, Datadog), introspects unfamiliar Python codebases, fans out to 5 parallel forensic subagents, reproduces root causes inside sandboxed containers, and generates verified code patches with complete safety audit logging.

---

## ⚡ Quickstart: Bring Your Own Repo (3-Step Onboarding)

`sre-agent` works on any Python repository out-of-the-box.

### 1. Install `sre-agent`
```bash
git clone https://github.com/pr0x7/SRE-triage-agent.git
cd SRE-triage-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Scaffold Config in Your Target Repo
Navigate to your Python repository and run `sre-agent init`. The agent will introspect your Dockerfile, dependencies, and test setup, creating a pre-filled `sre-agent.yaml`:
```bash
cd /path/to/your-python-repo
sre-agent init
```

### 3. Run Autonomous Triage
Trigger an investigation using a synthetic or real incident alert:
```bash
sre-agent run --incident /path/to/incident_alert.json
```
*(For dry-run / plan-only mode without file mutations, pass `--dry-run`)*

---

## 📡 Real-Time Webhook Ingestion Server

Receive live alert webhooks directly from Sentry, PagerDuty, or Datadog:
```bash
sre-agent webhook --port 8000
```
- Endpoint: `POST http://localhost:8000/webhook/sentry`
- Endpoint: `POST http://localhost:8000/webhook/pagerduty`
- Endpoint: `POST http://localhost:8000/webhook/datadog`

---

## 🛠️ Supported Stack v1 & Declarative Configuration

### Scope: Supported Stack v1
- **Language**: Python 3.10+
- **Environment**: Docker containerized sandbox
- **Testing Framework**: `pytest`

### Declarative Schema (`sre-agent.yaml`)
```yaml
service_name: "my-service"
language: "python"
framework: "fastapi" # or flask, celery, django, etc.
entrypoint: "uvicorn my_service.app:app --host 0.0.0.0 --port 8080"
build_command: "pip install -e ."
test_command: "pytest tests/"
log_source: "/tmp/app.log"
db_connection_string: "postgresql://readonly:secret@localhost:5432/mydb" # optional
deploy_remote: "origin/main" # optional
```

---

## 📊 Generalization Eval Benchmark Results

Tested across external open-source Python microservice repositories:

| Repository | Framework | Injected Bug Type | Initial Test Status | Post-Patch Status | Generalization Pass Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `payment-api` | Flask | `KeyError: 'currency'` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |
| `task-worker` | Celery | `KeyError: 'REDIS_HOST'` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |
| `user-auth-service` | FastAPI | `TypeError: NoneType` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |

> **Overall Generalization Benchmark Pass Rate: 3/3 (100.0%)**

---

## 🔒 Production Safety & Hardening

- **Restricted Sandbox Network Egress**: Docker containers default to restricted `network_mode="none"`.
- **Short-Lived Scoped Credentials**: Ephemeral token manager (`ScopedCredentialManager`) with short TTLs prevents standing secrets.
- **Connection-Level Read-Only DB**: SQLAlchemy inspector rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER` at connection level.
- **Audit Logging**: Every tool call and system access event is exported to structured `audit_<incident_id>.json` logs.

---

## 📁 Repository Architecture

```
SRE-triage-agent/
├── agent/                  # Core agent logic & subagents
│   ├── cli.py              # sre-agent CLI application (init/run/webhook)
│   ├── config.py           # Declarative sre-agent.yaml schema loader
│   ├── orchestrator.py     # Parallel LangGraph state machine
│   ├── security.py         # Ephemeral credential manager
│   ├── audit.py            # Audit trail logger
│   ├── db_adapter.py       # SQLAlchemy schema reflection engine
│   ├── log_sources.py      # Pluggable log adapters (Datadog, CloudWatch, Local)
│   ├── ingestion.py        # Webhook payload normalizers
│   └── subagents/          # Specialist forensic subagents
├── breakomatic/            # Synthetic target service with injectable bugs
├── evals/                  # Evaluation suite & generalization benchmark
└── scripts/                # Utility scripts & webhook receiver server
```
