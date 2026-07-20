"""Break-o-matic — a synthetic target service with injectable bugs for SRE agent testing."""

from breakomatic.config import clear_active_bug, get_active_bug, set_active_bug

__all__ = ["get_active_bug", "set_active_bug", "clear_active_bug"]
