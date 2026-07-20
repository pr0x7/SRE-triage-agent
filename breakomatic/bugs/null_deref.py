"""
Bug: Unhandled Null Dereference
───────────────────────────────
Replaces /users/{user_id} with a version that calls .upper() on
profile_bio without checking for None. Users 3 (Charlie) and 5 (Eve)
have profile_bio=NULL, so requesting them returns a 500.

Symptom:  GET /users/3 → 500 Internal Server Error (AttributeError)
Fix:      Add a None check before accessing profile_bio attributes.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

NAME = "null_deref"
DESCRIPTION = (
    "GET /users/{id} crashes with AttributeError when a user's profile_bio "
    "is NULL. Specifically, the code calls user.profile_bio.upper() without "
    "a None guard. Users 3 and 5 trigger the crash; others work fine."
)
EXPECTED_FIX = (
    "Guard the profile_bio access with a None check: "
    "user.profile_bio.upper() if user.profile_bio else 'No bio provided'"
)


def inject(app: FastAPI, engine, get_db) -> None:
    """Replace /users/{user_id} GET with a fixed version."""
    from breakomatic.app import replace_route
    from breakomatic.models import User

    def fixed_get_user(user_id: int, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Fix: Add a None check before accessing profile_bio attributes.
        profile_text = user.profile_bio.upper() if user.profile_bio else 'No bio provided'

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "profile_summary": profile_text,  # Removed the 'BIO: ' prefix
            "orders": [
                {"id": o.id, "total": o.total, "status": o.status}
                for o in user.orders
            ],
        }

    replace_route(app, "/users/{user_id}", "GET", fixed_get_user)