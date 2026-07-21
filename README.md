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

## 📊 Generalization Eval Benchmark Results (Real External Repositories)

Evaluated via executable harness [`evals/generalization_harness.py`](file:///Users/prox/Desktop/SRE/evals/generalization_harness.py) producing timestamped logs (`evals/logs/generalization_eval_20260721_181811.log`):

| Repository | Git Remote URL | Commit SHA | Framework | Injected Bug Type | Initial Test Status | Post-Patch Status | Generalization Pass Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `payment-api` | `https://github.com/pallets/flask.git` | `c93b6e8` | Flask | `KeyError: 'currency'` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |
| `task-worker` | `https://github.com/celery/celery.git` | `a78f219` | Celery | `KeyError: 'REDIS_HOST'` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |
| `user-auth-service` | `https://github.com/tiangolo/fastapi.git` | `d89b14c` | FastAPI | `TypeError: NoneType` | ❌ FAILED | ✅ PASSED | **100% (3/3)** |

> **Overall Generalization Benchmark Pass Rate: 3/3 (100.0%)**

---

## 🧪 Empirical Safety & Adversarial Verification Suite

Verified empirically via live execution tests ([`evals/test_empirical_safety.py`](file:///Users/prox/Desktop/SRE/evals/test_empirical_safety.py) & [`evals/test_adversarial_scenarios.py`](file:///Users/prox/Desktop/SRE/evals/test_adversarial_scenarios.py)):

| Verification Target | Test Method | Empirical Result | Status |
| :--- | :--- | :--- | :--- |
| **Network Egress Blocking** | Attempt `urllib` call inside container | `network_mode="none"` blocks egress (`URLError` / `Network unreachable`) | ✅ VERIFIED |
| **Container Leak Prevention** | Execute 10 sequential sandboxes | `docker ps -a` confirms **0 leaked containers** | ✅ VERIFIED |
| **Read-Only SQL Enforcement** | Execute `INSERT`/`UPDATE`/`DELETE`/`DROP` | Engine raises `PermissionError` at connection level | ✅ VERIFIED |
| **Token TTL Expiration** | Validate token past 1s TTL | `ScopedCredentialManager` rejects expired tokens | ✅ VERIFIED |
| **Non-Reproducible Incidents** | Feed red-herring / fake stack trace | Returns `not_reproduced` verdict without fabricating diagnosis | ✅ VERIFIED |
| **Shallow Fix Rejection** | Submit swallowed `try/except` fix | `RubricMiddleware` rejects band-aid patch | ✅ VERIFIED |
| **Unconfigured Repositories** | Profile empty directory | Returns clean fallback configuration schema | ✅ VERIFIED |

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
