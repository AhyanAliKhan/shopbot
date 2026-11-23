"""Real tools the sales agent can call. All of them read/write the database.

The user_id is NEVER taken from the model's arguments: it comes from the
request context (`ctx`), so the model cannot reach another user's data even if
a prompt tells it to.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Callable

from sqlalchemy import delete, func, or_, select

from .db import Cart, CartItem, Coupon, Order, PendingAction, Product, UserMemory, now, session

SHIPPING_FEE = 5.99
FREE_SHIPPING_OVER = 50.0
FAST_CITIES = {"karachi", "lahore", "islamabad", "rawalpindi", "new york", "london", "dubai",
               "toronto", "san francisco", "los angeles", "chicago", "berlin", "paris"}
MEMORY_KEY_RE = re.compile(r"[^a-z0-9_]+")
AFFIRMATIVE_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|confirm(ed)?|go ahead|do it|place (it|the order)|proceed|ok(ay)?|"
    r"please do|sounds good|absolutely|cancel it)\b", re.I)
# "no, don't cancel it" / "not okay" must never count as a yes.
NEGATIVE_RE = re.compile(r"\b(no|nope|not|don'?t|do not|never|wait|stop|hold on)\b", re.I)
PENDING_TTL = dt.timedelta(minutes=15)


# ---------------------------------------------------------------- tool schemas
TOOL_SPECS: list[dict] = [
    {
        "name": "search_products",
        "description": "Search the store catalog. Use for any product question. Returns up to 6 matches with id, price, stock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. 'running shoes', 'vegan gift'. Empty = browse."},
                "category": {"type": "string", "enum": ["footwear", "apparel", "accessories", "home", "beauty", "electronics"]},
                "max_price": {"type": "number"},
                "min_price": {"type": "number"},
            },
        },
    },
    {
        "name": "get_product_details",
        "description": "Full details for one product id (e.g. P001).",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    },
    {
        "name": "add_to_cart",
        "description": "Add a product to the customer's cart (checks stock).",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["product_id"],
        },
    },
    {
        "name": "remove_from_cart",
        "description": "Remove a product from the cart, or lower its quantity.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1, "description": "Omit to remove all."}},
            "required": ["product_id"],
        },
    },
    {
        "name": "view_cart",
        "description": "Show the cart with subtotal, discount, shipping and total.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "apply_coupon",
        "description": "Apply a discount code to the cart.",
        "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
    },
    {
        "name": "check_shipping",
        "description": "Shipping cost and delivery estimate to a city for the current cart.",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
    {
        "name": "checkout",
        "description": "RISKY: prepares an order from the cart and returns a summary. Does NOT place it. Show the summary and ask the customer to confirm.",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string", "description": "Delivery city"}}, "required": ["city"]},
    },
    {
        "name": "cancel_order",
        "description": "RISKY: requests cancellation of one of the customer's orders. Does NOT cancel yet; ask the customer to confirm.",
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
    {
        "name": "confirm_pending_action",
        "description": "Execute the pending checkout or cancellation. Only call after the customer explicitly said yes in their latest message.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_my_orders",
        "description": "List the customer's orders with status, or one order if order_id is given.",
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    },
    {
        "name": "save_customer_memory",
        "description": "Remember a lasting fact about the customer for future chats (name, sizes, style, budget, allergies, city, gift recipients). Call whenever they share one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "short snake_case label, e.g. name, shoe_size, favorite_color"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
]
# Cache the (stable) tool list: the breakpoint on the last tool caches all of them.
TOOL_SPECS[-1]["cache_control"] = {"type": "ephemeral"}


# ---------------------------------------------------------------- helpers
def _product_brief(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "price": p.price, "category": p.category,
            "in_stock": p.stock, "rating": p.rating}


def _norm_id(pid: str) -> str:
    pid = (pid or "").strip().upper()
    if re.fullmatch(r"\d{1,3}", pid):
        pid = f"P{int(pid):03d}"
    return pid


def _cart_summary(s, user_id: str, city: str | None = None) -> dict:
    rows = s.execute(
        select(CartItem, Product).join(Product, Product.id == CartItem.product_id)
        .where(CartItem.user_id == user_id)
    ).all()
    items = [{"product_id": p.id, "name": p.name, "unit_price": p.price, "quantity": c.quantity,
              "line_total": round(p.price * c.quantity, 2)} for c, p in rows]
    subtotal = round(sum(i["line_total"] for i in items), 2)
    cart = s.get(Cart, user_id)
    code = cart.coupon if cart else None
    discount, free_ship = 0.0, False
    if code:
        cp = s.get(Coupon, code)
        if cp and cp.active and subtotal >= cp.min_subtotal:
            discount = round(subtotal * cp.percent_off / 100, 2)
            free_ship = code == "FREESHIP"
        else:
            code = None
    shipping = 0.0 if (not items or free_ship or subtotal - discount >= FREE_SHIPPING_OVER) else SHIPPING_FEE
    out = {"items": items, "subtotal": subtotal, "coupon": code, "discount": discount,
           "shipping": shipping, "total": round(subtotal - discount + shipping, 2)}
    if city:
        out["delivery_estimate"] = _eta(city)
    return out


def _eta(city: str) -> str:
    return "2-3 business days" if city.strip().lower() in FAST_CITIES else "4-6 business days"


# ---------------------------------------------------------------- tools
def search_products(ctx, query: str = "", category: str | None = None,
                    max_price: float | None = None, min_price: float | None = None):
    with session() as s:
        stmt = select(Product).where(Product.active.is_(True))
        if category:
            stmt = stmt.where(Product.category == category.lower())
        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)
        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)
        products = list(s.scalars(stmt))
    words = [w for w in re.findall(r"[a-z0-9\-]+", (query or "").lower())
             if w not in {"a", "an", "the", "for", "me", "some", "any", "with", "and", "under", "of", "to", "i", "want", "need", "show"}]
    if words:
        def score(p: Product) -> int:
            hay = f"{p.name} {p.category} {p.tags} {p.description}".lower()
            # match singular/plural loosely ("shoes" ~ "shoe")
            return sum(1 for w in words if w in hay or w.rstrip("s") in hay)
        scored = [(score(p), p) for p in products]
        products = [p for sc, p in sorted(scored, key=lambda t: (-t[0], -t[1].rating)) if sc > 0]
    else:
        products.sort(key=lambda p: -p.rating)
    results = [_product_brief(p) for p in products[:6]]
    return {"count": len(results), "results": results} if results else {
        "count": 0, "results": [], "note": "No matching products. Suggest related categories."}


def get_product_details(ctx, product_id: str):
    with session() as s:
        p = s.get(Product, _norm_id(product_id))
        if not p or not p.active:
            return {"error": f"Product {product_id} not found."}
        return {**_product_brief(p), "description": p.description, "tags": p.tags.split(",")}


def add_to_cart(ctx, product_id: str, quantity: int = 1):
    quantity = max(1, min(int(quantity or 1), 20))
    with session() as s:
        p = s.get(Product, _norm_id(product_id))
        if not p or not p.active:
            return {"error": f"Product {product_id} not found."}
        item = s.scalar(select(CartItem).where(CartItem.user_id == ctx["user_id"], CartItem.product_id == p.id))
        new_qty = quantity + (item.quantity if item else 0)
        if p.stock < new_qty:
            return {"error": f"Only {p.stock} of {p.name} in stock.", "in_stock": p.stock}
        if item:
            item.quantity = new_qty
        else:
            s.add(CartItem(user_id=ctx["user_id"], product_id=p.id, quantity=quantity))
        s.flush()
        return {"added": p.name, "quantity": quantity, "cart": _cart_summary(s, ctx["user_id"])}


def remove_from_cart(ctx, product_id: str, quantity: int | None = None):
    with session() as s:
        item = s.scalar(select(CartItem).where(CartItem.user_id == ctx["user_id"],
                                               CartItem.product_id == _norm_id(product_id)))
        if not item:
            return {"error": "That product is not in the cart."}
        if quantity and quantity < item.quantity:
            item.quantity -= quantity
        else:
            s.delete(item)
        s.flush()
        return {"removed": _norm_id(product_id), "cart": _cart_summary(s, ctx["user_id"])}


def view_cart(ctx):
    with session() as s:
        cart = _cart_summary(s, ctx["user_id"])
    if not cart["items"]:
        return {"items": [], "note": "Cart is empty."}
    return cart


def apply_coupon(ctx, code: str):
    code = (code or "").strip().upper()
    with session() as s:
        cp = s.get(Coupon, code)
        if not cp or not cp.active:
            return {"error": f"Coupon {code} is not valid."}
        summary = _cart_summary(s, ctx["user_id"])
        if summary["subtotal"] < cp.min_subtotal:
            return {"error": f"{code} needs a subtotal of at least ${cp.min_subtotal:.0f}.",
                    "subtotal": summary["subtotal"]}
        cart = s.get(Cart, ctx["user_id"]) or Cart(user_id=ctx["user_id"])
        cart.coupon = code
        s.merge(cart)
        s.flush()
        return {"applied": code, "cart": _cart_summary(s, ctx["user_id"])}


def check_shipping(ctx, city: str):
    with session() as s:
        cart = _cart_summary(s, ctx["user_id"])
    return {"city": city, "delivery_estimate": _eta(city),
            "shipping_cost": cart["shipping"] if cart["items"] else SHIPPING_FEE,
            "rule": f"Free shipping on orders of ${FREE_SHIPPING_OVER:.0f}+ after discount; otherwise ${SHIPPING_FEE}."}


def checkout(ctx, city: str):
    with session() as s:
        cart = _cart_summary(s, ctx["user_id"], city)
        if not cart["items"]:
            return {"error": "Cart is empty. Add products first."}
        for i in cart["items"]:
            p = s.get(Product, i["product_id"])
            if p.stock < i["quantity"]:
                return {"error": f"Only {p.stock} of {p.name} left. Adjust the cart."}
        s.merge(PendingAction(user_id=ctx["user_id"], action="checkout",
                              payload={"city": city, "total": cart["total"]},
                              turn_id=ctx["turn_id"], created_at=now()))
    return {"status": "awaiting_confirmation", "order_preview": cart,
            "instruction": "Show this summary and ask the customer to reply 'yes' to place the order."}


def cancel_order(ctx, order_id: str):
    with session() as s:
        o = s.get(Order, (order_id or "").strip().upper())
        if not o or o.user_id != ctx["user_id"]:
            return {"error": f"Order {order_id} not found for this customer."}
        if o.status in ("shipped", "delivered", "cancelled"):
            return {"error": f"Order {o.id} is {o.status} and cannot be cancelled."}
        s.merge(PendingAction(user_id=ctx["user_id"], action="cancel", payload={"order_id": o.id},
                              turn_id=ctx["turn_id"], created_at=now()))
        return {"status": "awaiting_confirmation", "order_id": o.id, "total": o.total,
                "instruction": "Ask the customer to reply 'yes' to cancel this order."}


def confirm_pending_action(ctx):
    with session() as s:
        pa = s.get(PendingAction, ctx["user_id"])
        if not pa:
            return {"error": "Nothing is waiting for confirmation."}
        if pa.turn_id == ctx["turn_id"]:
            return {"error": "The customer has not confirmed yet. Ask them first and wait for their reply."}
        if now() - pa.created_at > PENDING_TTL:
            s.delete(pa)
            return {"error": "That request expired. Run checkout or cancel_order again and re-confirm."}
        msg = ctx.get("user_message", "")
        if not AFFIRMATIVE_RE.search(msg) or NEGATIVE_RE.search(msg):
            return {"error": "The customer's latest message is not a clear yes. Ask them to confirm explicitly."}
        action, payload = pa.action, dict(pa.payload)
        s.delete(pa)
        if action == "cancel":
            o = s.get(Order, payload["order_id"])
            if not o or o.user_id != ctx["user_id"]:
                return {"error": "Order not found."}
            o.status = "cancelled"
            for i in o.items:
                p = s.get(Product, i["product_id"])
                if p:
                    p.stock += i["quantity"]
            return {"cancelled": o.id, "refund": o.total}
        # checkout
        cart = _cart_summary(s, ctx["user_id"], payload.get("city"))
        if not cart["items"]:
            return {"error": "Cart is empty."}
        if cart["total"] != payload.get("total"):
            return {"error": "The cart changed since the summary. Run checkout again and re-confirm."}
        for i in cart["items"]:
            p = s.get(Product, i["product_id"])
            if p.stock < i["quantity"]:
                return {"error": f"Only {p.stock} of {p.name} left. Order not placed."}
            p.stock -= i["quantity"]
        order = Order(id="ORD-" + uuid.uuid4().hex[:6].upper(), user_id=ctx["user_id"], items=cart["items"],
                      subtotal=cart["subtotal"], discount=cart["discount"], shipping=cart["shipping"],
                      total=cart["total"], coupon=cart["coupon"], city=payload.get("city"))
        s.add(order)
        s.execute(delete(CartItem).where(CartItem.user_id == ctx["user_id"]))
        c = s.get(Cart, ctx["user_id"])
        if c:
            c.coupon = None
        return {"order_placed": order.id, "total": order.total, "delivery_estimate": cart.get("delivery_estimate"),
                "payment": "Cash on delivery"}


def get_my_orders(ctx, order_id: str | None = None):
    with session() as s:
        stmt = select(Order).where(Order.user_id == ctx["user_id"])
        if order_id:
            stmt = stmt.where(Order.id == order_id.strip().upper())
        orders = list(s.scalars(stmt.order_by(Order.created_at.desc()).limit(10)))
    if not orders:
        return {"orders": [], "note": "No orders found for this customer." if not order_id else f"Order {order_id} not found for this customer."}
    return {"orders": [{"id": o.id, "status": o.status, "total": o.total, "city": o.city,
                        "date": o.created_at.strftime("%Y-%m-%d"),
                        "items": [f'{i["quantity"]}x {i["name"]}' for i in o.items]} for o in orders]}


def save_customer_memory(ctx, key: str, value: str):
    key = MEMORY_KEY_RE.sub("_", (key or "").lower()).strip("_")[:60] or "note"
    value = (value or "").strip()[:400]
    if not value:
        return {"error": "Empty value."}
    upsert_memory(ctx["user_id"], key, value)
    return {"saved": {key: value}}


# ---------------------------------------------------------------- memory api
def upsert_memory(user_id: str, key: str, value: str) -> None:
    with session() as s:
        row = s.scalar(select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key))
        if row:
            row.value = value
            row.updated_at = now()
        else:
            s.add(UserMemory(user_id=user_id, key=key, value=value))


def load_memory(user_id: str) -> dict[str, str]:
    with session() as s:
        rows = s.scalars(select(UserMemory).where(UserMemory.user_id == user_id)
                         .order_by(UserMemory.updated_at.desc()).limit(25))
        return {r.key: r.value for r in rows}


def user_snapshot(user_id: str) -> dict[str, Any]:
    """Cheap per-turn context: cart size, order count, pending action."""
    with session() as s:
        cart_n = s.scalar(select(func.coalesce(func.sum(CartItem.quantity), 0)).where(CartItem.user_id == user_id))
        orders_n = s.scalar(select(func.count(Order.id)).where(Order.user_id == user_id))
        pa = s.get(PendingAction, user_id)
        return {"cart_items": int(cart_n or 0), "orders": int(orders_n or 0),
                "pending": f"{pa.action} {pa.payload}" if pa else None}


REGISTRY: dict[str, Callable] = {
    "search_products": search_products, "get_product_details": get_product_details,
    "add_to_cart": add_to_cart, "remove_from_cart": remove_from_cart, "view_cart": view_cart,
    "apply_coupon": apply_coupon, "check_shipping": check_shipping, "checkout": checkout,
    "cancel_order": cancel_order, "confirm_pending_action": confirm_pending_action,
    "get_my_orders": get_my_orders, "save_customer_memory": save_customer_memory,
}


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    fn = REGISTRY.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    args = {k: v for k, v in (args or {}).items() if k not in ("user_id", "ctx")}
    try:
        return fn(ctx, **args)
    except TypeError as e:
        return {"error": f"Bad arguments: {e}"}
    except Exception as e:  # keep the conversation alive on DB hiccups
        return {"error": f"Tool failed: {type(e).__name__}"}
