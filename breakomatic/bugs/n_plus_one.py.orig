"""
Bug: N+1 Query
─────────────
Replaces the /orders endpoint with a version that fetches each order's items
in a separate query (one SELECT per order instead of a single JOIN/subquery).
Under load, this hammers the DB and can exhaust the connection pool.

Symptom:  /orders becomes extremely slow, eventually times out.
Fix:      Use selectinload() or joinedload() to eager-load Order.items.
"""
from __future__ import annotations

import time
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.session import Session as SQLAlchemySession

from fastapi import Depends, FastAPI
from breakomatic.app import replace_route
from breakomatic.models import Order, OrderItem

NAME = "n_plus_one"
DESCRIPTION = (
    "GET /orders fetches each order's items with a separate DB query (N+1). "
    "With ~30 orders, that's ~30 extra queries per request. Under concurrency, "
    "the connection pool exhausts and requests start timing out."
)
EXPECTED_FIX = (
    "Add selectinload(Order.items) or joinedload(Order.items) to the query in "
    "the /orders endpoint to eager-load items in a single batch query."
)


def inject(app: FastAPI, engine, get_db) -> None:
    """Replace /orders GET with a buggy version."""
    @app.get("/orders", response_model=list[dict])
    def list_orders(db: Session = Depends(get_db)):
        # Use selectinload to eager-load Order.items
        orders = db.query(Order).options(joinedload(Order.items)).all()
        result = []
        for order in orders:
            # Simulate realistic processing delay
            time.sleep(0.01)
            result.append({
                "id": order.id,
                "user_id": order.user_id,
                "total": order.total,
                "status": order.status,
                "items": [
                    {
                        "product_name": i.product_name,
                        "quantity": i.quantity,
                        "price": i.price,
                    }
                    for i in order.items
                ],
            })
        return result

    replace_route(app, "/orders", "GET", list_orders)