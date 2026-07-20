"""
Bug injector CLI — activate one of the 5 injectable bugs.

Usage:
    python -m breakomatic.inject --bug n_plus_one     # inject a bug
    python -m breakomatic.inject --bug n_plus_one --alert  # inject + print alert
    python -m breakomatic.inject --clear              # remove active bug
    python -m breakomatic.inject --list               # show available bugs
    python -m breakomatic.inject --status             # show current state

After injecting, restart the service for the bug to take effect.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from breakomatic.bugs import BUG_REGISTRY, list_bugs
from breakomatic.config import clear_active_bug, get_active_bug, set_active_bug


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="breakomatic-inject",
        description="Inject or clear bugs in the break-o-matic service.",
    )
    parser.add_argument(
        "--bug",
        type=str,
        choices=list(BUG_REGISTRY.keys()),
        help="Bug to inject (restart service after injecting)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear any active bug",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_bugs",
        help="List all available bugs",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show which bug is currently active",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Generate and print a synthetic alert for the injected bug",
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Reset the database (drop + recreate + reseed)",
    )

    args = parser.parse_args()

    # ── --list ───────────────────────────────────────────────────
    if args.list_bugs:
        print("\n🐛  Available bugs:\n")
        for bug in list_bugs():
            print(f"  • {bug['name']}")
            print(f"    {bug['description'][:100]}...")
            print()
        return

    # ── --status ─────────────────────────────────────────────────
    if args.status:
        active = get_active_bug()
        if active:
            print(f"🐛  Active bug: {active}")
        else:
            print("✅  No bug active — service running normally")
        return

    # ── --clear ──────────────────────────────────────────────────
    if args.clear:
        clear_active_bug()
        print("✅  Bug cleared — restart the service for clean operation")
        if args.reset_db:
            _reset_db()
        return

    # ── --reset-db ───────────────────────────────────────────────
    if args.reset_db and not args.bug:
        _reset_db()
        return

    # ── --bug <name> ─────────────────────────────────────────────
    if args.bug:
        # Reset DB first to ensure clean state
        if args.reset_db:
            _reset_db()

        set_active_bug(args.bug)
        print(f"🐛  Injected: {args.bug}")
        print(f"   Restart the service for the bug to take effect:")
        print(f"   uvicorn breakomatic.app:app --port 8099 --reload")

        # Generate alert if requested
        if args.alert:
            from breakomatic.alerts import generate_alert
            alert = generate_alert(args.bug)
            print(f"\n📋  Synthetic alert:")
            print(json.dumps(alert, indent=2))

            # Also save to incidents/
            incidents_dir = Path(__file__).parent.parent / "incidents"
            incidents_dir.mkdir(exist_ok=True)
            alert_file = incidents_dir / f"alert_{args.bug}.json"
            alert_file.write_text(json.dumps(alert, indent=2) + "\n")
            print(f"\n   Saved to {alert_file}")
        return

    # No arguments — show help
    parser.print_help()


def _reset_db() -> None:
    """Reset database to clean state with fresh seed data."""
    from breakomatic.database import create_session_factory, get_engine, reset_database, seed_database

    print("🗄️  Resetting database...")
    engine = get_engine()
    reset_database(engine)
    session_factory = create_session_factory(engine)
    seed_database(engine, session_factory)
    print("✅  Database reset with fresh seed data")


if __name__ == "__main__":
    main()
