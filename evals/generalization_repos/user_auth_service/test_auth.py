"""
Pytest suite for User Auth service.
"""
import pytest
from evals.generalization_repos.user_auth_service.auth import get_user_profile


def test_get_user_profile_valid():
    res = get_user_profile({"user": {"id": "usr_100", "profile": {"role": "admin"}}})
    assert res["authenticated"] is True
    assert res["role"] == "admin"


def test_get_user_profile_missing_user_returns_unauthenticated():
    # Expect get_user_profile to handle None user gracefully
    res = get_user_profile({"user": None})
    assert res is None or res.get("authenticated") is False
