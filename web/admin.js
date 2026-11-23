const API = window.SHOPBOT_API;
const $ = (id) => document.getElementById(id);
const money = (n) => "$" + Number(n || 0).toFixed(2);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let KEY = (() => { try { return sessionStorage.getItem("bb_admin") || ""; } catch { return ""; } })();
let tab = "overview";

function toast(t) { const el = $("toast"); el.textContent = t; el.style.display = "block"; clearTimeout(toast._t); toast._t = setTimeout(() => (el.style.display = "none"), 2200); }

async function api(path, opts = {}) {
  const r = await fetch(API + path, { ...opts, headers: { "X-Admin-Key": KEY, "Content-Type": "application/json", ...(opts.headers || {}) } });
  if (r.status === 401) { lock(); throw new Error("unauthorized"); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function lock() { KEY = ""; try { sessionStorage.removeItem("bb_admin"); } catch {} $("app").style.display = "none"; $("login").style.display = ""; $("logout").style.display = "none"; }
$("logout").onclick = lock;
$("loginForm").onsubmit = async (e) => {
  e.preventDefault(); KEY = $("key").value.trim();
  try { await api("/admin/stats"); try { sessionStorage.setItem("bb_admin", KEY); } catch {} start(); }
  catch { $("loginErr").textContent = "That key didn't work (or the API is unreachable)."; }
};
function start() { $("login").style.display = "none"; $("app").style.display = ""; $("logout").style.display = ""; render(); }

$("side").querySelectorAll("button").forEach((b) => (b.onclick = () => {
  tab = b.dataset.tab; $("side").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b)); render();
}));

async function render() {
  $("main").innerHTML = `<p class="muted">Loading…</p>`;
  try { await ({ overview, orders, products, conversations, coupons })[tab](); }
  catch (e) { $("main").innerHTML = `<p class="muted">Couldn't load: ${esc(e.message)}</p>`; }
}

function bars(obj) {
  const entries = Object.entries(obj); if (!entries.length) return `<p class="muted">No data yet.</p>`;
  const max = Math.max(...entries.map((e) => e[1]));
  return entries.map(([k, v]) => `<div class="bar-row"><span>${esc(k)}</span><div class="bar" style="width:${Math.max(4, (v / max) * 100)}%"></div><b>${v}</b></div>`).join("");
}

async function overview() {
  const s = await api("/admin/stats");
  const k = (label, value, sub = "") => `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="muted" style="font-size:12px">${sub}</div></div>`;
  $("main").innerHTML = `
    <h2 style="margin-top:0">Overview</h2>
    <div class="kpis">
      ${k("Revenue", money(s.revenue), "excl. cancelled")}
      ${k("Orders", s.orders)}
      ${k("Customers", s.customers, `${s.threads} conversations`)}
      ${k("Agent turns", s.chats, `${s.blocked} blocked · ${s.errors} errors`)}
      ${k("Avg latency", (s.avg_latency_ms / 1000).toFixed(1) + "s")}
      ${k("LLM spend", "$" + s.est_cost_usd.toFixed(4), `${s.tokens_in.toLocaleString()} in · ${s.tokens_out.toLocaleString()} out`)}
    </div>
    <div class="two">
      <div class="panel"><h3 style="margin-top:0">Tool usage</h3>${bars(s.tool_usage)}</div>
      <div class="panel"><h3 style="margin-top:0">Best sellers (units)</h3>${bars(s.top_products)}</div>
    </div>
    <div class="panel"><h3 style="margin-top:0">Low stock (≤ 5)</h3>
      ${s.low_stock.length ? `<table><tr><th>ID</th><th>Product</th><th>Stock</th></tr>${s.low_stock.map((p) => `<tr><td>${p.id}</td><td>${p.image} ${esc(p.name)}</td><td><span class="pill ${p.stock ? "warn" : "bad"}">${p.stock}</span></td></tr>`).join("")}</table>` : `<p class="muted">All good.</p>`}
    </div>`;
}

async function orders() {
  const list = await api("/admin/orders");
  const statuses = ["placed", "packed", "shipped", "delivered", "cancelled"];
  $("main").innerHTML = `<h2 style="margin-top:0">Orders</h2><div class="panel table-wrap">
    ${list.length ? `<table><tr><th>Order</th><th>Customer</th><th>Items</th><th>City</th><th>Total</th><th>Status</th></tr>
    ${list.map((o) => `<tr><td><b>${o.id}</b><div class="muted" style="font-size:12px">${o.created_at.slice(0, 16).replace("T", " ")}</div></td>
      <td class="muted" style="font-size:12px">${esc(o.user_id)}</td>
      <td>${o.items.map((i) => `${i.quantity}× ${esc(i.name)}`).join("<br>")}</td><td>${esc(o.city || "")}</td>
      <td>${money(o.total)}${o.coupon ? `<div class="pill">${esc(o.coupon)}</div>` : ""}</td>
      <td><select data-id="${o.id}">${statuses.map((s) => `<option ${s === o.status ? "selected" : ""}>${s}</option>`).join("")}</select></td></tr>`).join("")}</table>`
      : `<p class="muted">No orders yet. They appear here when Bloom closes a sale.</p>`}</div>`;
  $("main").querySelectorAll("select").forEach((sel) => (sel.onchange = async () => {
    await api(`/admin/orders/${sel.dataset.id}`, { method: "PATCH", body: JSON.stringify({ status: sel.value }) }); toast(`${sel.dataset.id} → ${sel.value}`);
  }));
}

async function products() {
  const list = await api("/admin/products");
  $("main").innerHTML = `<h2 style="margin-top:0">Products</h2>
    <div class="panel"><h3 style="margin-top:0" id="formTitle">Add product</h3>
      <form id="pForm" class="form-grid">
        <input name="id" placeholder="ID (blank = new)" />
        <input name="name" placeholder="Name" required class="wide" />
        <select name="category">${["footwear", "apparel", "accessories", "home", "beauty", "electronics"].map((c) => `<option>${c}</option>`).join("")}</select>
        <input name="price" type="number" step="0.01" min="0.01" placeholder="Price" required />
        <input name="stock" type="number" min="0" placeholder="Stock" required />
        <input name="image" placeholder="Emoji" value="🛍️" />
        <input name="tags" placeholder="tags,comma,separated" />
        <textarea name="description" placeholder="Description" class="wide" rows="2"></textarea>
        <label style="display:flex;gap:6px;align-items:center"><input name="active" type="checkbox" checked style="width:auto" /> Active</label>
        <button class="btn primary">Save</button>
      </form></div>
    <div class="panel table-wrap"><table><tr><th>ID</th><th>Product</th><th>Category</th><th>Price</th><th>Stock</th><th></th></tr>
      ${list.map((p) => `<tr style="${p.active ? "" : "opacity:.5"}"><td>${p.id}</td><td>${p.image} ${esc(p.name)}</td><td>${p.category}</td><td>${money(p.price)}</td>
      <td><span class="pill ${p.stock > 5 ? "ok" : p.stock ? "warn" : "bad"}">${p.stock}</span></td>
      <td><button class="btn small" data-edit="${p.id}">Edit</button> ${p.active ? `<button class="btn small" data-del="${p.id}">Archive</button>` : ""}</td></tr>`).join("")}</table></div>`;
  const f = $("pForm");
  f.onsubmit = async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f));
    d.price = +d.price; d.stock = +d.stock; d.active = f.active.checked;
    const r = await api("/admin/products", { method: "POST", body: JSON.stringify(d) }); toast("Saved " + r.saved); products();
  };
  $("main").querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => {
    const p = list.find((x) => x.id === b.dataset.edit);
    for (const k of ["id", "name", "category", "price", "stock", "image", "tags", "description"]) f[k].value = p[k];
    f.active.checked = p.active; $("formTitle").textContent = "Edit " + p.id; f.scrollIntoView({ behavior: "smooth" });
  }));
  $("main").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`Archive ${b.dataset.del}? Customers and Bloom will stop seeing it.`)) return;
    await api(`/admin/products/${b.dataset.del}`, { method: "DELETE" }); toast("Archived"); products();
  }));
}

async function conversations() {
  const list = await api("/admin/conversations?limit=150");
  $("main").innerHTML = `<h2 style="margin-top:0">Conversations</h2><p class="muted">Every agent turn, newest first. Blocked = stopped by the safety guard before reaching the model.</p>
    <div class="panel table-wrap">${list.length ? `<table><tr><th>When</th><th>User / thread</th><th>Customer said</th><th>Bloom replied</th><th>Tools</th><th>Tokens</th><th>ms</th></tr>
    ${list.map((c) => `<tr><td class="muted" style="font-size:12px;white-space:nowrap">${c.created_at.slice(5, 16).replace("T", " ")}</td>
      <td style="font-size:12px">${esc(c.user_id)}<div class="muted">${esc(c.thread_id)}</div></td>
      <td>${esc(c.message)}${c.blocked ? ` <span class="pill bad">blocked</span>` : ""}${c.error ? ` <span class="pill bad" title="${esc(c.error)}">error</span>` : ""}</td>
      <td style="max-width:360px">${esc(c.reply)}</td>
      <td style="font-size:12px">${(c.tool_calls || []).map((t) => esc(t.name)).join("<br>")}</td>
      <td style="font-size:12px">${c.tokens_in}/${c.tokens_out}</td><td style="font-size:12px">${c.latency_ms}</td></tr>`).join("")}</table>` : `<p class="muted">No conversations yet.</p>`}</div>`;
}

async function coupons() {
  const list = await api("/admin/coupons");
  $("main").innerHTML = `<h2 style="margin-top:0">Coupons</h2>
    <div class="panel"><form id="cForm" class="form-grid">
      <input name="code" placeholder="CODE" required /><input name="percent_off" type="number" min="0" max="90" placeholder="% off" required />
      <input name="min_subtotal" type="number" min="0" placeholder="Min subtotal" value="0" />
      <label style="display:flex;gap:6px;align-items:center"><input name="active" type="checkbox" checked style="width:auto" /> Active</label>
      <button class="btn primary">Save coupon</button></form></div>
    <div class="panel"><table><tr><th>Code</th><th>% off</th><th>Min subtotal</th><th>Status</th></tr>
      ${list.map((c) => `<tr><td><b>${esc(c.code)}</b></td><td>${c.percent_off}%</td><td>${money(c.min_subtotal)}</td><td><span class="pill ${c.active ? "ok" : ""}">${c.active ? "active" : "off"}</span></td></tr>`).join("")}</table></div>`;
  const f = $("cForm");
  f.onsubmit = async (e) => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(f));
    d.percent_off = +d.percent_off; d.min_subtotal = +d.min_subtotal; d.active = f.active.checked;
    await api("/admin/coupons", { method: "POST", body: JSON.stringify(d) }); toast("Saved"); coupons();
  };
}

if (KEY) api("/admin/stats").then(start).catch(lock);
