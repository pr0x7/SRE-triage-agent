"""
Security & Credential Hardening Module for SRE Agent.

Provides short-lived, scoped ephemeral credential management to prevent
standing long-lived secrets from persisting inside sandbox environments.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
import uuid
from typing import Dict, List, Optional


@dataclass
class EphemeralToken:
    """Short-lived scoped access token."""

    token_id: str
    scope: str
    created_at: float
    expires_at: float

    @property
    def is_valid(self) -> bool:
        """Check if token is active and not expired."""
        return time.time() < self.expires_at


class ScopedCredentialManager:
    """Manages creation, validation, and expiration of scoped short-lived credentials."""

    def __init__(self, default_ttl_seconds: int = 300):
        self.default_ttl = default_ttl_seconds
        self._active_tokens: Dict[str, EphemeralToken] = {}

    def issue_token(self, scope: str, ttl_seconds: Optional[int] = None) -> EphemeralToken:
        """Issue a short-lived scoped token.

        Args:
            scope: Operational scope boundary (e.g. 'sandbox:execute', 'db:read_only', 'logs:fetch').
            ttl_seconds: Time-to-live in seconds (defaults to 300s / 5 min).
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        token = EphemeralToken(
            token_id=f"token-{uuid.uuid4().hex[:12]}",
            scope=scope,
            created_at=now,
            expires_at=now + ttl,
        )
        self._active_tokens[token.token_id] = token
        return token

    def validate_token(self, token_id: str, required_scope: str) -> bool:
        """Validate if token exists, is unexpired, and matches required scope boundary."""
        token = self._active_tokens.get(token_id)
        if not token or not token.is_valid:
            return False

        # Match exact scope or wildcard prefix (e.g. 'sandbox:*' matches 'sandbox:execute')
        if token.scope == required_scope or token.scope == "*":
            return True

        if token.scope.endswith(":*"):
            prefix = token.scope[:-2]
            return required_scope.startswith(prefix)

        return False

    def revoke_token(self, token_id: str) -> bool:
        """Revoke an active token immediately."""
        if token_id in self._active_tokens:
            del self._active_tokens[token_id]
            return True
        return False

    def list_active_tokens(self) -> List[EphemeralToken]:
        """Return list of unexpired active tokens."""
        now = time.time()
        return [t for t in self._active_tokens.values() if t.expires_at > now]
