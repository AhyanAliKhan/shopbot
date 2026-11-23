"""FastAPI server.

Public (grading):  POST /chat, GET /health
Storefront:        GET /products, /products/{id}, POST /auth/session, /me/*
Admin dashboard:   /admin/*  (header X-Admin-Key)
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from . import config as settings
from .db import ChatLog, Coupon, Order, Product, UserMemory, init_db, session
from .graph import build_graph, make_checkpointer
from .tools import _cart_summary, add_to_cart, load_memory, remove_from_cart

GRAPH = None
_thread_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
ID_RE = re.compile(r"^[\w.@:\-]{1,120}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH
    init_db()
    GRAPH = build_graph(make_checkpointer())
    yield


app = FastAPI(title="ShopBot Agent API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "internal_error"})


@app.exception_handler(RequestValidationError)
async def bad_request(request: Request, exc: RequestValidationError):
    # /chat must answer in the graded contract shape even for malformed bodies
    if request.url.path == "/chat":
        return JSONResponse(status_code=400, content={
            "reply": "Sorry, I couldn't read that request. Send JSON with user_id, thread_id and message.",
            "tool_calls": [], "tokens": {"in": 0, "out": 0}})
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


# ------------------------------------------------------------------ grading API
class ChatIn(BaseModel):
    user_id: str = Field(default="anonymous")
    thread_id: str = Field(default="default")
    message: str = Field(default="")


def _clean_id(v: str, fallback: str) -> str:
    v = (v or "").strip()
    if not v:
        return fallback
    return v if ID_RE.match(v) else hashlib.sha256(v.encode()).hexdigest()[:32]


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@app.get("/")
def root():
    return {"service": "ShopBot Agent API", "endpoints": ["POST /chat", "GET /health"]}


@app.post("/chat")
def chat(body: ChatIn):
    user_id = _clean_id(body.user_id, "anonymous")
    thread_id = _clean_id(body.thread_id, "default")
    message = (body.message or "").strip()
    if not message:
        return {"reply": "Hi! I'm Bloom, the shop assistant. What are you looking for today?",
                "tool_calls": [], "tokens": {"in": 0, "out": 0}}

    started = time.time()
    turn_id = uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": f"{user_id}::{thread_id}", "turn_id": turn_id},
           "recursion_limit": 25}
    reply, calls, t_in, t_out, blocked, error = "", [], 0, 0, False, None
    with _thread_locks[f"{user_id}::{thread_id}"]:
        try:
            out = GRAPH.invoke({"user_id": user_id, "incoming": message}, cfg)
            reply = out.get("reply") or "Sorry, I didn't catch that. Could you rephrase?"
            calls = out.get("turn_tool_calls", [])
            t_in, t_out = out.get("tokens_in", 0), out.get("tokens_out", 0)
            blocked = bool(out.get("blocked"))
        except Exception as e:  # never break the API contract
            error = f"{type(e).__name__}: {e}"[:500]
            reply = "Sorry, I'm having trouble right now. Please try again in a moment."
    latency = int((time.time() - started) * 1000)
    try:
        with session() as s:
            s.add(ChatLog(user_id=user_id, thread_id=thread_id, message=message[:4000], reply=reply,
                          tool_calls=calls, tokens_in=t_in, tokens_out=t_out, latency_ms=latency,
                          blocked=blocked, error=error))
    except Exception:
        pass
    return {"reply": reply, "tool_calls": calls, "tokens": {"in": t_in, "out": t_out}}


# ------------------------------------------------------------------ storefront
def _product_json(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "category": p.category, "price": p.price, "stock": p.stock,
            "description": p.description, "tags": p.tags, "rating": p.rating, "image": p.image,
            "active": p.active}


@app.get("/products")
def list_products(category: str | None = None, q: str | None = None):
    with session() as s:
        stmt = select(Product).where(Product.active.is_(True))
        if category:
            stmt = stmt.where(Product.category == category)
        items = [_product_json(p) for p in s.scalars(stmt.order_by(Product.id))]
    if q:
        ql = q.lower()
        items = [p for p in items if ql in f"{p['name']} {p['tags']} {p['description']}".lower()]
    return items


@app.get("/products/{pid}")
def get_product(pid: str):
    with session() as s:
        p = s.get(Product, pid.upper())
        if not p:
            raise HTTPException(404, "not found")
        return _product_json(p)


class SessionIn(BaseModel):
    email: str


def _sign(user_id: str) -> str:
    return hmac.new(settings.SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()


@app.post("/auth/session")
def create_session(body: SessionIn):
    """Passwordless demo login: email -> stable user_id + signed token."""
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "invalid email")
    user_id = "u_" + hashlib.sha256(email.encode()).hexdigest()[:16]
    return {"user_id": user_id, "token": _sign(user_id), "display": email.split("@")[0]}


def current_user(x_user_id: str = Header(...), x_user_token: str = Header(...)) -> str:
    if not hmac.compare_digest(_sign(x_user_id), x_user_token):
        raise HTTPException(401, "bad session")
    return x_user_id


class CartIn(BaseModel):
    product_id: str
    quantity: int = 1


@app.get("/me/cart")
def my_cart(user_id: str = Depends(current_user)):
    with session() as s:
        return _cart_summary(s, user_id)


@app.post("/me/cart")
def my_cart_add(body: CartIn, user_id: str = Depends(current_user)):
    return add_to_cart({"user_id": user_id}, body.product_id, body.quantity)


@app.delete("/me/cart/{pid}")
def my_cart_remove(pid: str, user_id: str = Depends(current_user)):
    return remove_from_cart({"user_id": user_id}, pid)


@app.get("/me/orders")
def my_orders(user_id: str = Depends(current_user)):
    with session() as s:
        rows = s.scalars(select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()))
        return [{"id": o.id, "items": o.items, "total": o.total, "status": o.status, "city": o.city,
                 "created_at": o.created_at.isoformat()} for o in rows]


@app.get("/me/memory")
def my_memory(user_id: str = Depends(current_user)):
    return load_memory(user_id)


@app.delete("/me/memory")
def my_memory_clear(user_id: str = Depends(current_user)):
    with session() as s:
        s.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    return {"cleared": True}


# ------------------------------------------------------------------ admin
def admin(x_admin_key: str = Header(...)):
    # fail closed if the deploy forgot to set ADMIN_API_KEY
    if settings.ADMIN_API_KEY == "change-me-admin" or not hmac.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(401, "bad admin key")


@app.get("/admin/stats", dependencies=[Depends(admin)])
def admin_stats():
    with session() as s:
        live = Order.status != "cancelled"
        revenue = s.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(live)) or 0
        orders = s.scalar(select(func.count(Order.id))) or 0
        customers = s.scalar(select(func.count(func.distinct(ChatLog.user_id)))) or 0
        threads = s.scalar(select(func.count(func.distinct(ChatLog.thread_id)))) or 0
        chats = s.scalar(select(func.count(ChatLog.id))) or 0
        t_in = s.scalar(select(func.coalesce(func.sum(ChatLog.tokens_in), 0))) or 0
        t_out = s.scalar(select(func.coalesce(func.sum(ChatLog.tokens_out), 0))) or 0
        avg_lat = s.scalar(select(func.coalesce(func.avg(ChatLog.latency_ms), 0))) or 0
        blocked = s.scalar(select(func.count(ChatLog.id)).where(ChatLog.blocked.is_(True))) or 0
        errors = s.scalar(select(func.count(ChatLog.id)).where(ChatLog.error.is_not(None))) or 0
        low_stock = [_product_json(p) for p in s.scalars(select(Product).where(Product.stock <= 5, Product.active.is_(True)))]
        tool_counts: dict[str, int] = defaultdict(int)
        for calls in s.scalars(select(ChatLog.tool_calls).order_by(ChatLog.id.desc()).limit(1000)):
            for c in calls or []:
                tool_counts[c.get("name", "?")] += 1
        top = s.execute(
            select(Order.items).where(live).order_by(Order.created_at.desc()).limit(500)).scalars()
        sold: dict[str, int] = defaultdict(int)
        for items in top:
            for i in items:
                sold[i["name"]] += i["quantity"]
    # Haiku 5.5 list price: $0.10 / MTok in, $0.50 / MTok out (cache reads are cheaper; this is an upper bound)
    cost = t_in / 1e6 * 0.10 + t_out / 1e6 * 0.50
    return {"revenue": round(float(revenue), 2), "orders": orders, "customers": customers, "threads": threads,
            "chats": chats, "tokens_in": t_in, "tokens_out": t_out, "est_cost_usd": round(cost, 4),
            "avg_latency_ms": int(avg_lat), "blocked": blocked, "errors": errors, "low_stock": low_stock,
            "tool_usage": dict(sorted(tool_counts.items(), key=lambda kv: -kv[1])),
            "top_products": dict(sorted(sold.items(), key=lambda kv: -kv[1])[:8])}


class ProductIn(BaseModel):
    id: str | None = None
    name: str
    category: str
    price: float = Field(gt=0)
    stock: int = Field(ge=0)
    description: str = ""
    tags: str = ""
    image: str = "🛍️"
    active: bool = True


@app.get("/admin/products", dependencies=[Depends(admin)])
def admin_products():
    with session() as s:
        return [_product_json(p) for p in s.scalars(select(Product).order_by(Product.id))]


@app.post("/admin/products", dependencies=[Depends(admin)])
def admin_upsert_product(body: ProductIn):
    with session() as s:
        pid = (body.id or "").upper()
        if not pid:
            n = s.scalar(select(func.count(Product.id))) or 0
            pid = f"P{n + 1:03d}"
            while s.get(Product, pid):
                n += 1
                pid = f"P{n + 1:03d}"
        p = s.get(Product, pid) or Product(id=pid, rating=4.5)
        for k, v in body.model_dump(exclude={"id"}).items():
            setattr(p, k, v)
        s.merge(p)
    return {"saved": pid}


@app.delete("/admin/products/{pid}", dependencies=[Depends(admin)])
def admin_archive_product(pid: str):
    with session() as s:
        p = s.get(Product, pid.upper())
        if not p:
            raise HTTPException(404, "not found")
        p.active = False
    return {"archived": pid.upper()}


@app.get("/admin/orders", dependencies=[Depends(admin)])
def admin_orders():
    with session() as s:
        rows = s.scalars(select(Order).order_by(Order.created_at.desc()).limit(200))
        return [{"id": o.id, "user_id": o.user_id, "items": o.items, "total": o.total, "status": o.status,
                 "city": o.city, "coupon": o.coupon, "created_at": o.created_at.isoformat()} for o in rows]


class StatusIn(BaseModel):
    status: str


@app.patch("/admin/orders/{oid}", dependencies=[Depends(admin)])
def admin_order_status(oid: str, body: StatusIn):
    if body.status not in {"placed", "packed", "shipped", "delivered", "cancelled"}:
        raise HTTPException(400, "bad status")
    with session() as s:
        o = s.get(Order, oid.upper())
        if not o:
            raise HTTPException(404, "not found")
        o.status = body.status
    return {"id": oid.upper(), "status": body.status}


@app.get("/admin/conversations", dependencies=[Depends(admin)])
def admin_conversations(limit: int = 100):
    with session() as s:
        rows = s.scalars(select(ChatLog).order_by(ChatLog.id.desc()).limit(min(limit, 500)))
        return [{"id": r.id, "user_id": r.user_id, "thread_id": r.thread_id, "message": r.message,
                 "reply": r.reply, "tool_calls": r.tool_calls, "tokens_in": r.tokens_in,
                 "tokens_out": r.tokens_out, "latency_ms": r.latency_ms, "blocked": r.blocked,
                 "error": r.error, "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/admin/coupons", dependencies=[Depends(admin)])
def admin_coupons():
    with session() as s:
        return [{"code": c.code, "percent_off": c.percent_off, "min_subtotal": c.min_subtotal,
                 "active": c.active} for c in s.scalars(select(Coupon))]


class CouponIn(BaseModel):
    code: str
    percent_off: int = Field(ge=0, le=90)
    min_subtotal: float = 0
    active: bool = True


@app.post("/admin/coupons", dependencies=[Depends(admin)])
def admin_coupon_upsert(body: CouponIn):
    with session() as s:
        s.merge(Coupon(code=body.code.strip().upper(), percent_off=body.percent_off,
                       min_subtotal=body.min_subtotal, active=body.active))
    return {"saved": body.code.strip().upper()}
