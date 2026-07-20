"""
Break-o-matic FastAPI service.

A tiny order-management API that serves as the "broken production service"
the SRE agent investigates. Supports injecting one of 5 bugs at startup.

Usage:
    # Normal (no bug):
    uvicorn breakomatic.app:app --port 8099

    # With a bug injected:
    python -m breakomatic.inject --bug n_plus_one
    uvicorn breakomatic.app:app --port 8099 --reload
"""
from __future__ import annotations

import os
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session, selectinload

from breakomatic.config import get_active_bug
from breakomatic.database import create_session_factory, get_engine, seed_database
from breakomatic.models import Base, Order, OrderItem, User

# ── Module-level state (set during create_app) ──────────────────────
_engine = None
_SessionLocal = None
_active_bug: str | None = None


def get_db():
    """FastAPI dependency — provides a DB session, properly closed after use."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Route replacement helper (used by bug injectors) ────────────────

def replace_route(app: FastAPI, path: str, method: str, new_endpoint) -> None:
    """Replace a route's endpoint. Creates a fresh APIRoute so dependency
    injection is properly wired for the new function."""
    method = method.upper()
    for i, route in enumerate(app.routes):
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in (route.methods or set())
        ):
            app.routes[i] = APIRoute(
                path=path,
                endpoint=new_endpoint,
                methods={method},
                tags=route.tags,
                name=route.name,
            )
            return
    raise ValueError(f"Route {method} {path} not found — cannot replace")


# ── App factory ─────────────────────────────────────────────────────

def create_app(active_bug: str | None = None) -> FastAPI:
    """Build the FastAPI application, optionally injecting a bug."""
    global _engine, _SessionLocal, _active_bug

    _active_bug = active_bug or get_active_bug()

    # ── Broken env: crash on startup (before engine creation) ────
    if _active_bug == "broken_env":
        from breakomatic.bugs.broken_env import inject_startup
        inject_startup()  # raises RuntimeError — service won't start

    # ── Engine + tables + seed data ──────────────────────────────
    _engine = get_engine()
    _SessionLocal = create_session_factory(_engine)
    Base.metadata.create_all(bind=_engine)
    seed_database(_engine, _SessionLocal)

    # ── FastAPI app ──────────────────────────────────────────────
    app = FastAPI(
        title="Break-o-matic",
        description="Synthetic service with injectable bugs for SRE agent testing",
        version="1.0.0",
    )

    # ── Routes ───────────────────────────────────────────────────

    @app.get("/health", tags=["meta"])
    def health():
        return {
            "status": "ok",
            "active_bug": _active_bug,
            "version": "1.0.0",
        }

    @app.get("/users", tags=["users"])
    def list_users(db: Session = Depends(get_db)):
        users = db.query(User).all()
        return [
            {"id": u.id, "name": u.name, "email": u.email}
            for u in users
        ]

    @app.get("/users/{user_id}", tags=["users"])
    def get_user(user_id: int, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "profile_bio": user.profile_bio,
            "profile_summary": (
                f"Bio: {user.profile_bio.strip()}"
                if user.profile_bio
                else "No bio provided"
            ),
            "orders": [
                {"id": o.id, "total": o.total, "status": o.status}
                for o in user.orders
            ],
        }

    @app.get("/orders", tags=["orders"])
    def list_orders(db: Session = Depends(get_db)):
        orders = (
            db.query(Order)
            .options(selectinload(Order.items))
            .all()
        )
        return [
            {
                "id": o.id,
                "user_id": o.user_id,
                "total": o.total,
                "status": o.status,
                "items": [
                    {
                        "product_name": i.product_name,
                        "quantity": i.quantity,
                        "price": i.price,
                    }
                    for i in o.items
                ],
            }
            for o in orders
        ]

    @app.post("/orders", tags=["orders"])
    def create_order(
        user_id: int,
        items: list[dict],
        db: Session = Depends(get_db),
    ):
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        total = sum(
            item.get("price", 0) * item.get("quantity", 1) for item in items
        )
        order = Order(user_id=user_id, total=round(total, 2))
        db.add(order)
        db.flush()

        for item in items:
            db.add(OrderItem(
                order_id=order.id,
                product_name=item["product_name"],
                quantity=item.get("quantity", 1),
                price=item["price"],
            ))
        db.commit()
        db.refresh(order)
        return {"id": order.id, "total": order.total, "status": order.status}

    # ── Inject bug (after routes + DB exist) ─────────────────────
    if _active_bug and _active_bug != "broken_env":
        from breakomatic.bugs import get_bug_module
        bug_module = get_bug_module(_active_bug)
        bug_module.inject(app, _engine, get_db)
        print(f"  🐛  Bug injected: {_active_bug}")

    return app


# ── Default app instance for uvicorn ─────────────────────────────
# `uvicorn breakomatic.app:app --port 8099`
try:
    app = create_app()
except RuntimeError as e:
    # broken_env bug causes a startup crash — print the traceback
    print(f"\n❌  FATAL: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
