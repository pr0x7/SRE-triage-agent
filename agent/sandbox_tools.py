"""
Sandbox tools for agent interaction with the target service inside the sandbox.
These tools are run on the host but delegate execution/requests to the DockerSandbox container.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from agent.docker_sandbox import DockerSandbox


def _get_project_files() -> list[tuple[str, bytes]]:
    """Read all break-o-matic source files from the host to upload to the sandbox."""
    root = Path("/Users/prox/Desktop/SRE")
    files: list[tuple[str, bytes]] = []

    # Copy breakomatic files
    for p in root.glob("breakomatic/**/*.py"):
        if "__pycache__" in p.parts or ".active_bug" in p.name:
            continue
        rel_path = p.relative_to(root)
        files.append((str(rel_path), p.read_bytes()))

    # Copy evals files
    for p in root.glob("evals/**/*.py"):
        if "__pycache__" in p.parts or "test_breakomatic_bugs" in p.name or "harness" in p.name:
            continue
        rel_path = p.relative_to(root)
        files.append((str(rel_path), p.read_bytes()))

    # Copy pyproject.toml
    if (root / "pyproject.toml").exists():
        files.append(("pyproject.toml", (root / "pyproject.toml").read_bytes()))

    return files


def run_python_in_sandbox(sandbox: DockerSandbox, python_code: str) -> Any:
    """Run python code in the sandbox without shell quoting issues by using base64 encoding."""
    b64_code = base64.b64encode(python_code.encode("utf-8")).decode("utf-8")
    cmd = f"python3 -c \"import base64; exec(base64.b64decode('{b64_code}').decode('utf-8'))\""
    return sandbox.execute(cmd)


# ── Deploy Break-o-matic ──────────────────────────────────────────

class DeployBreakomaticInput(BaseModel):
    bug_name: str | None = Field(
        None,
        description="The name of the bug to inject (n_plus_one, null_deref, bad_migration, leaked_connection, broken_env) or None for a clean deploy.",
    )


class DeployBreakomaticTool(BaseTool):
    name: str = "deploy_breakomatic"
    description: str = (
        "Deploys or restarts the break-o-matic target service inside the sandbox. "
        "If a bug_name is provided, that bug is injected. Returns deployment status."
    )
    args_schema: type[BaseModel] = DeployBreakomaticInput
    sandbox: DockerSandbox = Field(exclude=True)

    def _run(self, bug_name: str | None = None) -> str:
        try:
            # 1. Kill any existing uvicorn process robustly using Python via /proc
            kill_code = (
                "import os, signal\n"
                "killed = False\n"
                "for pid in os.listdir('/proc'):\n"
                "    if pid.isdigit():\n"
                "        try:\n"
                "            with open(f'/proc/{pid}/cmdline', 'r') as f:\n"
                "                cmd = f.read()\n"
                "                if 'uvicorn' in cmd:\n"
                "                    os.kill(int(pid), signal.SIGKILL)\n"
                "                    killed = True\n"
                "        except:\n"
                "            pass\n"
                "if killed:\n"
                "    print('Killed existing uvicorn')\n"
                "else:\n"
                "    print('No existing uvicorn found')"
            )
            kill_res = run_python_in_sandbox(self.sandbox, kill_code)
            
            # Wait for port 8099 to become free
            port_check_code = (
                "import socket\n"
                "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
                "try:\n"
                "    s.connect(('127.0.0.1', 8099))\n"
                "    s.close()\n"
                "    print('busy')\n"
                "except Exception:\n"
                "    print('free')"
            )
            for _ in range(10):
                res = run_python_in_sandbox(self.sandbox, port_check_code)
                if "free" in res.output:
                    break
                time.sleep(0.5)

            # 2. Upload codebase
            files = _get_project_files()
            upload_results = self.sandbox.upload_files(files)
            failed_uploads = [r.path for r in upload_results if r.error]
            if failed_uploads:
                return f"Error: Failed to upload files: {failed_uploads}"

            # 3. Inject active bug file if specified
            if bug_name:
                bug_data = {"active_bug": bug_name}
                self.sandbox.upload_files([
                    ("breakomatic/.active_bug.json", json.dumps(bug_data).encode())
                ])
            else:
                # Remove active bug if deploying clean
                self.sandbox.execute("rm -f breakomatic/.active_bug.json")

            # 4. Check/Install dependencies (fastapi, uvicorn, sqlalchemy, pydantic, pytest, httpx)
            pip_res = self.sandbox.execute("pip install fastapi uvicorn sqlalchemy pydantic pytest httpx")
            if pip_res.exit_code != 0:
                return f"Error installing dependencies: {pip_res.output}"

            # 5. Reset/initialize DB inside sandbox if not broken_env
            if bug_name != "broken_env":
                db_code = (
                    "from breakomatic.database import get_engine, reset_database, create_session_factory, seed_database\n"
                    "engine = get_engine()\n"
                    "reset_database(engine)\n"
                    "seed_database(engine, create_session_factory(engine))"
                )
                db_res = run_python_in_sandbox(self.sandbox, db_code)
                if db_res.exit_code != 0:
                    return f"Error seeding database: {db_res.output}"

            # Clear previous uvicorn logs to avoid reading stale traces
            self.sandbox.execute("rm -f /tmp/breakomatic.log")

            # 6. Start the server in background
            start_cmd = "nohup uvicorn breakomatic.app:app --host 0.0.0.0 --port 8099 > /tmp/breakomatic.log 2>&1 &"
            self.sandbox.execute(start_cmd)

            # Wait a moment for server to boot
            time.sleep(2.5)

            # 7. Check status
            if bug_name == "broken_env":
                # For broken_env, it is expected to have crashed on startup
                # Let's read the startup log
                log_res = self.sandbox.execute("cat /tmp/breakomatic.log")
                return (
                    "Deploy request finished. Since 'broken_env' was injected, "
                    "the service is expected to crash on startup. Startup logs:\n"
                    f"{log_res.output}"
                )

            # Query health endpoint
            health_code = (
                "import urllib.request\n"
                "import json\n"
                "try:\n"
                "    with urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=2) as r:\n"
                "        print(r.read().decode())\n"
                "except Exception as e:\n"
                "    print(json.dumps({'error': str(e)}))"
            )
            status_res = run_python_in_sandbox(self.sandbox, health_code)
            return f"Service deployed successfully. Health check response: {status_res.output.strip()}"

        except Exception as e:
            return f"Exception during deployment: {e}"


# ── Query Break-o-matic Endpoint ──────────────────────────────────

class QueryBreakomaticInput(BaseModel):
    method: str = Field(..., description="HTTP method (GET, POST, etc.)")
    path: str = Field(..., description="Endpoint path, e.g. /users, /orders, /users/3")
    payload: str | None = Field(None, description="Optional JSON payload string (for POST requests)")


class QueryBreakomaticTool(BaseTool):
    name: str = "query_breakomatic"
    description: str = (
        "Queries the break-o-matic service running inside the sandbox container. "
        "Returns the HTTP status code and response body."
    )
    args_schema: type[BaseModel] = QueryBreakomaticInput
    sandbox: DockerSandbox = Field(exclude=True)

    def _run(self, method: str, path: str, payload: str | None = None) -> str:
        python_code = f"""
import urllib.request
import json
import sys

url = 'http://127.0.0.1:8099{path}'
data = {repr(payload.encode('utf-8') if payload else None)}
headers = {{}}
if data:
    headers['Content-Type'] = 'application/json'

req = urllib.request.Request(url, data=data, headers=headers, method={repr(method.upper())})
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        status = response.status
        body = response.read().decode('utf-8', errors='replace')
        print(json.dumps({{"status": status, "body": body}}))
except urllib.error.HTTPError as e:
    err_body = e.read().decode('utf-8', errors='replace')
    print(json.dumps({{"status": e.code, "body": err_body}}))
except Exception as e:
    print(json.dumps({{"status": 500, "error": str(e)}}))
"""
        try:
            res = run_python_in_sandbox(self.sandbox, python_code)
            return res.output.strip()
        except Exception as e:
            return json.dumps({"status": 500, "error": str(e)})


# ── Deploy Diff Git Tools ──────────────────────────────────────────

class GitLogInput(BaseModel):
    limit: int = Field(10, description="Number of commits to retrieve.")


class GitLogTool(BaseTool):
    name: str = "git_log"
    description: str = "Retrieve recent commit logs for the breakomatic repository."
    args_schema: type[BaseModel] = GitLogInput

    def _run(self, limit: int = 10) -> str:
        import subprocess
        try:
            res = subprocess.run(
                ["git", "log", "-n", str(limit), "--oneline"],
                cwd="/Users/prox/Desktop/SRE",
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout
        except Exception as e:
            return f"Error running git log: {e}"


class GitDiffInput(BaseModel):
    sha: str = Field(..., description="Commit SHA to diff.")


class GitDiffTool(BaseTool):
    name: str = "git_diff"
    description: str = "Retrieve the diff/changes introduced in a specific git commit."
    args_schema: type[BaseModel] = GitDiffInput

    def _run(self, sha: str) -> str:
        import subprocess
        try:
            res = subprocess.run(
                ["git", "show", sha],
                cwd="/Users/prox/Desktop/SRE",
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout[:5000]
        except Exception as e:
            return f"Error running git diff: {e}"


# ── DB Inspector SQL Tool ──────────────────────────────────────────

class DbQueryInput(BaseModel):
    sql: str = Field(..., description="SQL SELECT query to execute against SQLite database.")


class DbQueryTool(BaseTool):
    name: str = "db_query"
    description: str = "Run a read-only SELECT query against the SQLite database inside the sandbox."
    args_schema: type[BaseModel] = DbQueryInput
    sandbox: DockerSandbox = Field(exclude=True)

    def _run(self, sql: str) -> str:
        if not sql.strip().lower().startswith("select"):
            return "Error: Only read-only SELECT queries are allowed."

        python_code = f"""
import sqlite3
import json
conn = sqlite3.connect('/workspace/breakomatic/breakomatic.db')
cursor = conn.cursor()
try:
    cursor.execute({repr(sql)})
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    print(json.dumps({{"columns": cols, "rows": rows}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
finally:
    conn.close()
"""
        try:
            res = run_python_in_sandbox(self.sandbox, python_code)
            return res.output.strip()
        except Exception as e:
            return json.dumps({"error": str(e)})
