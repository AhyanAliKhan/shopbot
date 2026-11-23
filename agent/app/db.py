"""Database models (SQLAlchemy 2.0). Same schema on Postgres and SQLite.

Every row that belongs to a customer carries `user_id`, and every query in the
tools layer filters on it. That is how users are kept apart.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import config


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), index=True)
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    image: Mapped[str] = mapped_column(String(20), default="🛍️")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class Cart(Base):
    """Per-user cart metadata (coupon)."""
    __tablename__ = "carts"
    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    coupon: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Coupon(Base):
    __tablename__ = "coupons"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    percent_off: Mapped[int] = mapped_column(Integer)
    min_subtotal: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    items: Mapped[list] = mapped_column(JSON)
    subtotal: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float, default=0)
    shipping: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float)
    coupon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="placed")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class PendingAction(Base):
    """A risky action (checkout / cancel) waiting for the customer's yes.

    `turn_id` is the chat turn that created it; it can only be confirmed in a
    later turn, so the model can never ask-and-confirm by itself.
    """
    __tablename__ = "pending_actions"
    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    action: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    turn_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class UserMemory(Base):
    """Long-term memory: durable facts about one user, across all threads."""
    __tablename__ = "user_memory"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(String(400))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ChatLog(Base):
    """One row per /chat call, for the admin dashboard and benchmarking."""
    __tablename__ = "chat_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    thread_id: Mapped[str] = mapped_column(String(120), index=True)
    message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


_engine_kwargs: dict = {"pool_pre_ping": True}
if config.IS_POSTGRES:
    # prepare_threshold=None keeps it working behind Supabase/Neon poolers.
    _engine_kwargs.update(pool_size=5, max_overflow=5, pool_recycle=300,
                          connect_args={"prepare_threshold": None})
else:
    _engine_kwargs.update(connect_args={"check_same_thread": False})

engine = create_engine(config.sqlalchemy_url(), **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    from .seed import seed

    Base.metadata.create_all(engine)
    with session() as s:
        if s.scalar(select(Product.id).limit(1)) is None:
            seed(s)
