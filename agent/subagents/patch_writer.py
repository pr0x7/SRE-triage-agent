"""
Patch Writer subagent implementation.
Given a confirmed bug, writes a fix to the bug module and writes a regression test.
Verifies the fix by running pytest inside the sandbox.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from agent.docker_sandbox import DockerSandbox
from agent.llm import ChatGroqWithRetry

logger = logging.getLogger(__name__)


# ── Sandbox Helper for Patch Writer ───────────────────────────────

def run_sandbox_tests(bug_name: str) -> str:
    """Deploy current host code to sandbox, run target with bug_name, and run pytest."""
    logger.info(f"patch_writer: starting sandbox to verify fix for bug: {bug_name}")
    sandbox = DockerSandbox(image="python:3.11-slim")
    sandbox.start()

    try:
        from agent.sandbox_tools import DeployBreakomaticTool
        deploy_tool = DeployBreakomaticTool(sandbox=sandbox)
        deploy_result = deploy_tool._run(bug_name=bug_name)

        # Run pytest inside the sandbox
        res = sandbox.execute("pytest /workspace/evals")
        return f"Deploy Result: {deploy_result}\n\nPytest Output:\n{res.output}"
    except Exception as e:
        return f"Error running sandbox tests: {e}"
    finally:
        sandbox.stop()


# ── LLM Direct Helper ──────────────────────────────────────────────

def clean_python_code(content: str) -> str:
    """Extract code within ```python blocks if present, otherwise return content as-is."""
    match = re.search(r"```python\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return content.strip()


def run_patch_writer(bug_name: str) -> str:
    """Run the patch writer agent to write the fix and regression test using standard text completions."""
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    # Use Llama-3.1-8b-instant for robust tool-free text generations
    llm = ChatGroqWithRetry(
        model="llama-3.1-8b-instant",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    project_root = Path("/Users/prox/Desktop/SRE")
    bug_file_path = project_root / "breakomatic" / "bugs" / f"{bug_name}.py"
    reg_test_path = project_root / "evals" / "test_regression.py"

    logger.info(f"patch_writer: starting patch creation for bug '{bug_name}'...")
    
    # 1. Read original buggy code
    orig_code = ""
    if bug_file_path.exists():
        orig_code = bug_file_path.read_text()
    else:
        orig_code = f"# Bug file breakomatic/bugs/{bug_name}.py not found."

    # 2. Query LLM to write the fix
    fix_prompt = f"""\
You are an SRE Senior Developer.
We have an active bug in our break-o-matic service called '{bug_name}'.
Below is the content of 'breakomatic/bugs/{bug_name}.py'. Your task is to rewrite this file so that it behaves correctly (i.e. is FIXED) even when injected!

Original code:
```python
{orig_code}
```

Instructions for the fix depending on the bug name:
- For 'n_plus_one': Modify the orders GET endpoint query to use eager loading (selectinload or joinedload) of items to avoid N+1 queries. Import selectinload or joinedload from sqlalchemy.orm.
- For 'null_deref': Protect the upper() call when bio is NULL/None in the users GET route. Use 'No bio provided' (without the 'BIO:' prefix) if user.profile_bio is None, and f"BIO: {{user.profile_bio.upper()}}" otherwise.
- For 'bad_migration': In inject(), do NOT drop the status column, or add it back using text("ALTER TABLE orders ADD COLUMN status VARCHAR(20) DEFAULT 'pending'").
- For 'leaked_connection': In get_db(), ensure db.close() is called inside a finally block so connections are not leaked.
- For 'broken_env': Keep the 'inject_startup()' function signature. Modify it to delete 'DATABASE_URL' from 'os.environ' (e.g. using os.environ.pop('DATABASE_URL', None) or del os.environ['DATABASE_URL']) so the default absolute database path is used, and do not raise RuntimeError. Do not define 'inject()' as raising an error.

Provide the COMPLETE updated python code of 'breakomatic/bugs/{bug_name}.py' inside a single markdown code block starting with ```python and ending with ```.
Do not output anything else.
"""
    messages = [
        SystemMessage(content="You are an SRE patch writer that output python code blocks."),
        HumanMessage(content=fix_prompt)
    ]
    
    logger.info("patch_writer: requesting code fix from LLM...")
    response = llm.invoke(messages)
    fixed_code = clean_python_code(response.content)
    
    # Write the backup to the host filesystem first if not already backed up
    orig_backup_path = bug_file_path.with_suffix(".py.orig")
    if not orig_backup_path.exists():
        orig_backup_path.write_text(orig_code)

    # Write the fix to the host filesystem
    bug_file_path.write_text(fixed_code)
    logger.info(f"patch_writer: successfully wrote code fix to host file {bug_file_path.name}")

    # 3. Read existing app tests for reference
    app_tests_path = project_root / "evals" / "test_breakomatic_app.py"
    app_tests_code = ""
    if app_tests_path.exists():
        app_tests_code = app_tests_path.read_text()

    # 4. Query LLM to write the regression test
    test_prompt = f"""\
You are an SRE QA Engineer.
Your task is to write a pytest regression test in 'evals/test_regression.py' for the bug '{bug_name}' in breakomatic.
The test must verify that the bug scenario behaves correctly.

Refer to 'evals/test_breakomatic_app.py' to see how the client is initialized:
```python
{app_tests_code}
```

Instructions for regression test depending on the bug name:
- For 'n_plus_one': Hit GET /orders and verify that it returns 200 OK and contains orders. If possible, query orders and check that the DB query log or response has items.
- For 'null_deref': Hit GET /users/3 (which has a null profile summary/bio) and assert that it returns 200 OK and matches Charlie Brown.
- For 'bad_migration': Hit GET /orders and assert response is 200 OK and contains status column.
- For 'leaked_connection': Query orders 10 times in a loop and assert all of them return 200 OK (no database timeout).
- For 'broken_env': Hit GET /health and assert response is 200 OK and status is 'ok'.

Provide the COMPLETE updated python code of 'evals/test_regression.py' inside a single markdown code block starting with ```python and ending with ```.
Do not output anything else.
"""
    logger.info("patch_writer: requesting regression test from LLM...")
    messages_test = [
        SystemMessage(content="You are an SRE test writer that output python code blocks."),
        HumanMessage(content=test_prompt)
    ]
    response_test = llm.invoke(messages_test)
    test_code = clean_python_code(response_test.content)

    # Write the regression test to the host filesystem
    reg_test_path.write_text(test_code)
    logger.info(f"patch_writer: successfully wrote regression test to host file {reg_test_path.name}")

    # 5. Run tests inside the sandbox
    logger.info("patch_writer: running verification tests inside the sandbox...")
    test_output = run_sandbox_tests(bug_name)
    
    # 6. Check results and retry once if it failed
    if "failed" in test_output.lower() or "error" in test_output.lower() or "exit_code: 0" not in test_output:
        logger.warning("patch_writer: sandbox tests failed. Requesting self-correction...")
        correction_prompt = f"""\
The tests we wrote failed inside the sandbox!
Here is the pytest output:
{test_output}

Here is the code of the bug fix:
```python
{fixed_code}
```

Here is the code of the regression test:
```python
{test_code}
```

Please review both files and write a corrected version of the bug fix 'breakomatic/bugs/{bug_name}.py'.
Make sure it resolves the errors/failures shown in the pytest output.
Provide the COMPLETE updated python code of 'breakomatic/bugs/{bug_name}.py' inside a single markdown code block starting with ```python.
"""
        messages_correction = [
            SystemMessage(content="You are a senior debugging developer."),
            HumanMessage(content=correction_prompt)
        ]
        response_correction = llm.invoke(messages_correction)
        fixed_code = clean_python_code(response_correction.content)
        bug_file_path.write_text(fixed_code)
        logger.info("patch_writer: wrote corrected bug fix. Re-running sandbox tests...")
        test_output = run_sandbox_tests(bug_name)

    return f"Patch Writer Run Summary:\n- Fixed File: breakomatic/bugs/{bug_name}.py\n- Regression Test: evals/test_regression.py\n- Sandbox Verification Results:\n{test_output}"
