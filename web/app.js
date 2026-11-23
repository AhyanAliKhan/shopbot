const API = window.SHOPBOT_API;
const $ = (id) => document.getElementById(id);
const CATS = ["all", "footwear", "apparel", "accessories", "home", "beauty", "electronics"];
let products = [];
let activeCat = "all";

// ---------- storage helpers (never crash if storage is blocked) ----------
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

function toast(t) {
  const el = $("toast"); el.textContent = t; el.style.display = "block";
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.style.display = "none"), 2200);
}
const money = (n) => "$" + Number(n).toFixed(2);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- session: every visitor gets a user_id (guest or signed-in) ----------
async function ensureSession(email) {
  let s = store.get("bb_session");
  if (!s || email) {
    const em = email || `guest-${Math.random().toString(36).slice(2, 10)}@guest.bazaarbloom`;
    const r = await fetch(`${API}/auth/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: em }) });
    if (!r.ok) throw new Error("login failed");
    s = await r.json();
    s.guest = !email;
    s.thread = "t_" + Date.now().toString(36);
    store.set("bb_session", s);
    store.set("bb_chat", []);
  }
  $("who").textContent = s.guest ? "Guest" : s.display;
  $("loginBtn").textContent = s.guest ? "Sign in" : "Switch user";
  return s;
}
let SESSION = null;
const authHeaders = () => ({ "X-User-Id": SESSION.user_id, "X-User-Token": SESSION.token, "Content-Type": "application/json" });

$("loginBtn").onclick = async () => {
  const email = prompt("Sign in with your email (demo – no password).\nEach email is a separate customer with its own cart, orders and memory.");
  if (!email) return;
  try { SESSION = await ensureSession(email.trim()); $("msgs").innerHTML = ""; greet(); refreshCart(); toast("Signed in as " + SESSION.display); }
  catch { toast("Please enter a valid email"); }
};

// ---------- catalog ----------
function renderFilters() {
  $("filters").innerHTML = CATS.map((c) => `<button class="chip ${c === activeCat ? "active" : ""}" data-c="${c}">${c[0].toUpperCase() + c.slice(1)}</button>`).join("") +
    `<input id="search" placeholder="Search products…" />`;
  $("filters").querySelectorAll(".chip").forEach((b) => (b.onclick = () => { activeCat = b.dataset.c; renderFilters(); renderGrid(); }));
  $("search").oninput = renderGrid;
}
function renderGrid() {
  const q = ($("search")?.value || "").toLowerCase();
  const list = products.filter((p) => (activeCat === "all" || p.category === activeCat) &&
    (!q || `${p.name} ${p.tags} ${p.description}`.toLowerCase().includes(q)));
  $("grid").innerHTML = list.map((p) => `
    <article class="card">
      <div class="img">${p.image}</div>
      <div class="body">
        <div class="muted" style="font-size:12px">${esc(p.category)} · ${p.id} · ★ ${p.rating}</div>
        <div class="name">${esc(p.name)}</div>
        <div class="muted" style="font-size:13px">${esc(p.description)}</div>
        <div class="row">
          <span class="price">${money(p.price)}</span>
          ${p.stock > 0 ? `<button class="btn small primary" onclick="addToCart('${p.id}')">Add</button>` : `<span class="pill bad">Sold out</span>`}
        </div>
        <button class="btn small ghost" style="align-self:flex-start;padding-left:0" onclick="openChat('Tell me more about ${p.id}')">Ask Bloom →</button>
      </div>
    </article>`).join("") || `<p class="muted">No products match.</p>`;
}
async function loadProducts() {
  try { products = await (await fetch(`${API}/products`)).json(); }
  catch { $("grid").innerHTML = `<p class="muted">Can't reach the shop API at ${esc(API)}. Is it running?</p>`; return; }
  renderFilters(); renderGrid();
}

// ---------- cart / orders / memory ----------
async function addToCart(pid) {
  const r = await (await fetch(`${API}/me/cart`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ product_id: pid, quantity: 1 }) })).json();
  toast(r.error || `Added ${r.added}`); refreshCart();
}
async function removeItem(pid) {
  await fetch(`${API}/me/cart/${pid}`, { method: "DELETE", headers: authHeaders() }); refreshCart(); showCart();
}
async function refreshCart() {
  try {
    const c = await (await fetch(`${API}/me/cart`, { headers: authHeaders() })).json();
    $("cartCount").textContent = (c.items || []).reduce((a, i) => a + i.quantity, 0);
    return c;
  } catch { return { items: [] }; }
}
function openDrawer(title, html) { $("drawerTitle").textContent = title; $("drawerBody").innerHTML = html; $("drawer").classList.add("open"); }
function closeDrawer() { $("drawer").classList.remove("open"); }
async function showCart() {
  const c = await refreshCart();
  if (!c.items || !c.items.length) return openDrawer("Cart", `<p class="muted">Your cart is empty.</p><button class="btn primary" onclick="closeDrawer();openChat('Recommend something popular')">Get a recommendation</button>`);
  const rows = c.items.map((i) => {
    const p = products.find((x) => x.id === i.product_id) || {};
    return `<div class="line-item"><span class="em">${p.image || "🛍️"}</span><div class="grow"><b>${esc(i.name)}</b><div class="muted">${i.quantity} × ${money(i.unit_price)}</div></div><b>${money(i.line_total)}</b><button class="btn small ghost" onclick="removeItem('${i.product_id}')">✕</button></div>`;
  }).join("");
  openDrawer("Cart", rows + `
    <div class="totals" style="margin-top:14px">
      <div><span>Subtotal</span><span>${money(c.subtotal)}</span></div>
      ${c.discount ? `<div><span>Discount (${esc(c.coupon)})</span><span>−${money(c.discount)}</span></div>` : ""}
      <div><span>Shipping</span><span>${c.shipping ? money(c.shipping) : "Free"}</span></div>
      <div class="grand"><span>Total</span><span>${money(c.total)}</span></div>
    </div>
    <p class="muted" style="font-size:13px">Checkout happens in chat: Bloom shows the summary and asks before placing the order.</p>
    <button class="btn primary" style="width:100%" onclick="closeDrawer();openChat('I want to check out')">Checkout with Bloom</button>`);
}
async function showOrders() {
  const [orders, mem] = await Promise.all([
    fetch(`${API}/me/orders`, { headers: authHeaders() }).then((r) => r.json()).catch(() => []),
    fetch(`${API}/me/memory`, { headers: authHeaders() }).then((r) => r.json()).catch(() => ({})),
  ]);
  const cls = { placed: "warn", packed: "warn", shipped: "ok", delivered: "ok", cancelled: "bad" };
  const o = orders.length ? orders.map((x) => `<div class="line-item"><div class="grow"><b>${x.id}</b> <span class="pill ${cls[x.status] || ""}">${x.status}</span><div class="muted" style="font-size:13px">${x.items.map((i) => `${i.quantity}× ${esc(i.name)}`).join(", ")}</div></div><b>${money(x.total)}</b></div>`).join("") : `<p class="muted">No orders yet.</p>`;
  const keys = Object.keys(mem);
  const m = keys.length ? `<table>${keys.map((k) => `<tr><td class="muted">${esc(k)}</td><td>${esc(mem[k])}</td></tr>`).join("")}</table><button class="btn small" style="margin-top:10px" onclick="clearMemory()">Forget everything about me</button>` : `<p class="muted">Nothing yet. Tell Bloom your size, budget or style and it will remember across chats.</p>`;
  openDrawer("Your account", `<h3>Orders</h3>${o}<h3 style="margin-top:22px">What Bloom remembers</h3>${m}`);
}
async function clearMemory() {
  if (!confirm("Delete everything Bloom remembers about you?")) return;
  await fetch(`${API}/me/memory`, { method: "DELETE", headers: authHeaders() }); showOrders(); toast("Memory cleared");
}
$("cartBtn").onclick = showCart;
$("ordersBtn").onclick = showOrders;

// ---------- chat ----------
const SUGGESTIONS = ["Gifts under $30", "Running shoes size 42", "What's in my cart?", "Track my order", "Apply WELCOME10"];
function addMsg(role, text, tools) {
  const el = document.createElement("div");
  el.className = "msg " + (role === "user" ? "me" : "bot");
  // escape first, then turn the model's **bold** into <b>
  if (role === "user") el.textContent = text;
  else el.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  if (tools && tools.length) {
    const t = document.createElement("span"); t.className = "tools";
    t.textContent = "🔧 " + tools.map((c) => c.name).join(", "); el.appendChild(t);
  }
  $("msgs").appendChild(el); $("msgs").scrollTop = $("msgs").scrollHeight;
}
function greet() {
  const hist = store.get("bb_chat") || [];
  $("msgs").innerHTML = "";
  if (!hist.length) addMsg("bot", "Hi! I'm Bloom 🌸 Tell me what you're shopping for, or ask about your cart and orders.");
  hist.forEach((m) => addMsg(m.role, m.text, m.tools));
  $("suggest").innerHTML = SUGGESTIONS.map((s) => `<button class="btn small">${s}</button>`).join("");
  $("suggest").querySelectorAll("button").forEach((b) => (b.onclick = () => send(b.textContent)));
}
function openChat(prefill) {
  $("chat").classList.add("open"); $("chatFab").style.display = "none";
  if (prefill) send(prefill); else $("chatInput").focus();
}
function closeChat() { $("chat").classList.remove("open"); $("chatFab").style.display = ""; }
function newThread() {
  SESSION.thread = "t_" + Date.now().toString(36); store.set("bb_session", SESSION); store.set("bb_chat", []);
  greet(); toast("New conversation – Bloom still remembers your profile");
}
let busy = false;
async function send(text) {
  text = (text || "").trim(); if (!text || busy) return;
  busy = true; addMsg("user", text); $("chatInput").value = "";
  const hist = store.get("bb_chat") || []; hist.push({ role: "user", text });
  const typing = document.createElement("div"); typing.className = "typing"; typing.textContent = "Bloom is typing…"; $("msgs").appendChild(typing);
  try {
    const r = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: SESSION.user_id, thread_id: SESSION.thread, message: text }) });
    const d = await r.json();
    typing.remove(); addMsg("bot", d.reply, d.tool_calls);
    hist.push({ role: "bot", text: d.reply, tools: d.tool_calls });
    if ((d.tool_calls || []).some((c) => /cart|confirm|coupon|checkout/.test(c.name))) refreshCart();
  } catch {
    typing.remove(); addMsg("bot", "I couldn't reach the server. Please try again.");
  }
  store.set("bb_chat", hist.slice(-60)); busy = false;
}
$("chatForm").onsubmit = (e) => { e.preventDefault(); send($("chatInput").value); };

// ---------- boot ----------
(async () => {
  loadProducts();
  try { SESSION = await ensureSession(); refreshCart(); greet(); }
  catch { $("who").textContent = "offline"; }
})();
