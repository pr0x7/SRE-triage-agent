"""
Database setup — engine factory, session factory, and seed data.
Uses SQLAlchemy with QueuePool so the leaked_connection bug can exhaust it.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool


# Default database path
_DB_DIR = Path(__file__).parent
_DEFAULT_DB_URL = f"sqlite:///{_DB_DIR / 'breakomatic.db'}"


def get_engine(
    db_url: str | None = None,
    pool_size: int = 5,
    max_overflow: int = 3,
    pool_timeout: int = 5,
):
    """Create a SQLAlchemy engine.

    Pool is intentionally small (5+3 = 8 max connections) so the
    leaked_connection bug exhausts it within a handful of requests.
    """
    url = db_url or os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=300,
    )

    # Enable WAL mode for SQLite — allows concurrent reads
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def create_session_factory(engine) -> sessionmaker:
    """Create a bound session factory."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def seed_database(engine, session_factory: sessionmaker) -> None:
    """Insert sample data if the tables are empty.

    Creates 5 users (2 with profile_bio=None for null_deref bug),
    ~25 orders, and ~60 order items.
    """
    from breakomatic.models import Base, Order, OrderItem, User

    Base.metadata.create_all(bind=engine)

    db: Session = session_factory()
    try:
        if db.query(User).count() > 0:
            return  # Already seeded

        # Users — some with profile_bio=None (crucial for null_deref bug)
        users_data = [
            ("Alice Johnson", "alice@example.com", "Senior engineer at Acme Corp"),
            ("Bob Smith", "bob@example.com", "DevOps lead, 10 years experience"),
            ("Charlie Brown", "charlie@example.com", None),          # No profile!
            ("Diana Prince", "diana@example.com", "SRE manager at CloudScale"),
            ("Eve Wilson", "eve@example.com", None),                 # No profile!
        ]

        users = []
        for name, email, bio in users_data:
            user = User(name=name, email=email, profile_bio=bio)
            db.add(user)
            users.append(user)
        db.flush()

        # Products catalog
        products = [
            ("Widget A", 9.99), ("Widget B", 19.99), ("Gadget X", 49.99),
            ("Gadget Y", 29.99), ("Thingamajig", 4.99), ("Doohickey", 14.99),
            ("Whatchamacallit", 39.99), ("Gizmo Pro", 24.99),
        ]
        statuses = ["pending", "shipped", "delivered", "cancelled"]

        random.seed(42)  # Reproducible seed data
        for user in users:
            for _ in range(random.randint(3, 8)):
                num_items = random.randint(1, 4)
                selected = random.sample(products, num_items)
                total = sum(p[1] * random.randint(1, 3) for p in selected)

                order = Order(
                    user_id=user.id,
                    total=round(total, 2),
                    status=random.choice(statuses),
                )
                db.add(order)
                db.flush()

                for product_name, price in selected:
                    qty = random.randint(1, 3)
                    db.add(OrderItem(
                        order_id=order.id,
                        product_name=product_name,
                        quantity=qty,
                        price=price,
                    ))

        db.commit()

        n_users = db.query(User).count()
        n_orders = db.query(Order).count()
        n_items = db.query(OrderItem).count()
        print(f"  🌱  Seeded {n_users} users, {n_orders} orders, {n_items} items")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_database(engine) -> None:
    """Drop and recreate all tables — useful between bug injections."""
    from breakomatic.models import Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
