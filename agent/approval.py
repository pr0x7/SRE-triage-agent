"""
Approval — interrupt() + resume logic for human-in-the-loop gate.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

def get_patch_diff(bug_name: str) -> str:
    """Generate a unified diff between the original buggy file and the newly patched file."""
    project_root = Path("/Users/prox/Desktop/SRE")
    bug_file_path = project_root / "breakomatic" / "bugs" / f"{bug_name}.py"
    orig_file_path = bug_file_path.with_suffix(".py.orig")

    if not bug_file_path.exists():
        return f"Patched file {bug_file_path} does not exist."
    if not orig_file_path.exists():
        return f"Original backup file {orig_file_path} does not exist. Cannot show diff."

    orig_content = orig_file_path.read_text().splitlines(keepends=True)
    fixed_content = bug_file_path.read_text().splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_content,
        fixed_content,
        fromfile=f"a/breakomatic/bugs/{bug_name}.py (BUGGY)",
        tofile=f"b/breakomatic/bugs/{bug_name}.py (PATCHED)",
    )
    return "".join(diff)

def prompt_approval_gate(bug_name: str, grader_feedback: str = "") -> bool:
    """Surface the proposed fix diff and wait for human approval in the terminal."""
    diff = get_patch_diff(bug_name)
    
    print("\n" + "=" * 60)
    print("🚨 HUMAN APPROVAL REQUIRED FOR PATCH DEPLOYMENT 🚨")
    print("=" * 60)
    print(f"Proposed patch for bug: {bug_name}\n")
    if grader_feedback:
        print("📋 Rubric Grade:")
        print(grader_feedback)
        print()
    print("📄 Diff:")
    print(diff)
    print("=" * 60)
    
    while True:
        try:
            choice = input("Approve and apply this patch? [y/N]: ").strip().lower()
            if choice in ("y", "yes"):
                print("✅ Patch approved! Proceeding with triage finalization...")
                return True
            elif choice in ("", "n", "no"):
                print("❌ Patch rejected. Aborting finalization.")
                return False
            else:
                print("Please enter 'y' (yes) or 'n' (no).")
        except (KeyboardInterrupt, EOFError):
            print("\n⚠️ Input interrupted. Exiting.")
            sys.exit(1)
