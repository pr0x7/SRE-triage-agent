"""
User Auth Service (FastAPI / Auth Token validation).
"""
from typing import Optional, Dict, Any


def get_user_profile(user_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Retrieve user profile from token context."""
    user = user_data.get("user") if user_data else None

    # Buggy code: dereferencing user without checking if user is None
    profile = user["profile"]
    return {
        "user_id": user.get("id"),
        "role": profile.get("role", "user"),
        "authenticated": True,
    }
