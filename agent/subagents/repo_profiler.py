"""
Repo Profiler Subagent — Introspects unknown repositories to infer build, run, and test commands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.config import SREAgentConfig, load_config
from agent.llm import ChatGroqWithRetry
from langchain_core.messages import HumanMessage, SystemMessage


SYSTEM_PROMPT = """\
You are an expert SRE and DevOps Repository Profiler.
Your job is to analyze repository manifests (Dockerfile, pyproject.toml, requirements.txt, CI workflows, README) \
and infer the correct commands to build, start, and test the Python service.

Output ONLY a JSON object matching this schema (do not wrap in markdown code blocks unless raw JSON):
{
  "service_name": "string",
  "language": "python",
  "framework": "fastapi|flask|django|other",
  "entrypoint": "command to start service",
  "build_command": "command to build/install dependencies",
  "test_command": "command to run tests",
  "log_source": "log file path"
}
"""


def _scan_repo_files(repo_path: Path) -> dict[str, str]:
    """Scan repository for key configuration files and return their text content snippets."""
    snippets: dict[str, str] = {}

    files_to_check = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "README.md",
    ]

    for fname in files_to_check:
        fpath = repo_path / fname
        if fpath.exists() and fpath.is_file():
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                snippets[fname] = text[:2000]  # Cap snippet length
            except Exception:
                pass

    # Check CI workflows
    workflows_dir = repo_path / ".github" / "workflows"
    if workflows_dir.exists() and workflows_dir.is_dir():
        for wf in workflows_dir.glob("*.yml"):
            try:
                snippets[f".github/workflows/{wf.name}"] = wf.read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                pass

    return snippets


def _infer_heuristics(snippets: dict[str, str], repo_name: str) -> dict[str, Any]:
    """Fallback deterministic heuristic parser if LLM is unavailable or for initial baseline."""
    build_cmd = "pip install -e ."
    if "requirements.txt" in snippets and "setup.py" not in snippets and "pyproject.toml" not in snippets:
        build_cmd = "pip install -r requirements.txt"

    test_cmd = "pytest"
    if "pyproject.toml" in snippets and "pytest" in snippets["pyproject.toml"]:
        test_cmd = "pytest"

    entrypoint = f"python -m {repo_name}"
    dockerfile = snippets.get("Dockerfile", "")
    for line in dockerfile.splitlines():
        if line.strip().startswith("CMD"):
            import re
            cmds = re.findall(r'"([^"]+)"', line) or re.findall(r"'([^']+)'", line)
            if cmds:
                entrypoint = " ".join(cmds)
                break

    if "uvicorn" in entrypoint or "uvicorn" in dockerfile:
        framework = "fastapi"
    elif "flask" in entrypoint or "flask" in dockerfile or "flask" in snippets.get("requirements.txt", ""):
        framework = "flask"
    else:
        framework = "python"

    return {
        "service_name": repo_name,
        "language": "python",
        "framework": framework,
        "entrypoint": entrypoint,
        "build_command": build_cmd,
        "test_command": test_cmd,
        "log_source": f"/tmp/{repo_name}.log",
    }


def profile_repository(repo_path: Path | str) -> SREAgentConfig:
    """Introspect repository to generate structured SREAgentConfig.

    Precedence:
    1. Explicit sre-agent.yaml file if present in repository root.
    2. Auto-detection via LLM analysis of repository manifests.
    3. Heuristic fallback.
    """
    root = Path(repo_path).resolve()
    config_file = root / "sre-agent.yaml"

    explicit_config: dict[str, Any] = {}
    if config_file.exists():
        try:
            loaded = load_config(config_file)
            explicit_config = loaded.model_dump(exclude_none=True)
        except Exception:
            pass

    snippets = _scan_repo_files(root)
    heuristics = _infer_heuristics(snippets, root.name)

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm_profile: dict[str, Any] = {}

    if groq_api_key and snippets:
        try:
            llm = ChatGroqWithRetry(
                model="llama-3.3-70b-versatile",
                api_key=groq_api_key,
                temperature=0.0,
                max_tool_retries=2,
            )

            prompt = f"Repository Name: {root.name}\n\nManifest Snippets:\n"
            for name, content in snippets.items():
                prompt += f"--- {name} ---\n{content}\n\n"

            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]

            response = llm.invoke(messages)
            raw = response.content.strip()
            if raw.startswith("```"):
                lines = [l for l in raw.splitlines() if not l.strip().startswith("```")]
                raw = "\n".join(lines).strip()

            llm_profile = json.loads(raw)
            if llm_profile.get("framework") in ("other", "python", None) and heuristics.get("framework") not in ("python", None):
                llm_profile["framework"] = heuristics["framework"]
        except Exception:
            pass

    # Merge hierarchy: heuristics -> LLM inferred -> explicit sre-agent.yaml overrides
    merged = {**heuristics, **llm_profile, **explicit_config}
    return SREAgentConfig(**merged)
