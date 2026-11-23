# 🌸 ShopBot: Bazaar Bloom

**Track 1 (ShopBot):** an AI storefront with a sales agent for small sellers.

Customers browse the shop and chat with **Bloom**, a LangGraph sales agent on `claude-haiku-5-5`. Bloom searches the catalog, recommends products, fills the cart, applies coupons, quotes shipping, and places or cancels orders, but only after the customer says yes. Bloom remembers each customer across conversations. The seller gets a dashboard with revenue, orders, inventory, coupons, every agent conversation, tool usage and LLM spend.

| | |
|---|---|
| 🛍️ Live store | https://shopbot-69.vercel.app |
| 📊 Seller dashboard | https://shopbot-69.vercel.app/admin.html |
| 🤖 Agent API | https://shopbot-pnm5.onrender.com (`POST /chat`, `GET /health`) |
| 🎬 Demo video | [Watch on Drive](https://drive.google.com/file/d/16mN6D3AV-vk7uOgR4wQfB4FwrdxRltu5/view) |
| 📝 Workshop canvas | [Canvas photo](https://drive.google.com/file/d/1fgeRDtTGhgBKbhMHc7o5_BPJ9x56L3vx/view) |

![demo](docs/demo.gif)

---

## Architecture

```mermaid
flowchart LR
  subgraph Vercel["Vercel (static site)"]
    S[Storefront<br/>index.html] 
    A[Seller dashboard<br/>admin.html]
  end
  subgraph API["Agent API: FastAPI on Render (Docker)"]
    C["POST /chat"] --> G
    subgraph G["LangGraph"]
      direction LR
      guard["🛡️ guard<br/>(rules, 0 tokens)"] -->|ok| mem["🧠 memory<br/>load + extract facts"]
      guard -->|injection| endn((END))
      mem --> agent["💬 sales_agent<br/>claude-haiku-5-5"]
      agent -->|tool_use| tools["🔧 tools<br/>12 DB tools"]
      tools --> agent
      agent -->|reply| endn
    end
    R["/products /me/* /admin/*"]
  end
  subgraph DB["Neon Postgres"]
    T1[(products · carts · orders<br/>coupons · pending_actions)]
    T2[(user_memory<br/>long-term, by user_id)]
    T3[(LangGraph checkpoints<br/>short-term, by thread_id)]
    T4[(chat_logs)]
  end
  S -- chat / cart --> C & R
  A -- X-Admin-Key --> R
  G <--> DB
  R <--> DB
  agent <--> Claude[(Anthropic API)]
```

**Graph nodes**

| Node | Kind | Job |
|---|---|---|
| `guard` | Safety agent (deterministic) | Blocks prompt injection, attempts to read other users' data, and requests for secrets before any LLM call, so blocked turns cost 0 tokens. Caps message length. |
| `memory` | Memory agent (deterministic) | Loads the user's long-term profile from `user_memory`, auto-extracts facts such as name, sizes, city and diet with regex as a backup to the LLM tool, and adds a cart/order snapshot. |
| `sales_agent` | LLM (`claude-haiku-5-5`) | Sales reasoning and tool selection. Refuses off-topic requests. Uses a two-step confirm for risky actions. |
| `tools` | Tool executor | Runs the tool calls against Postgres. `user_id` comes from the request context, never from model arguments. |

**Tools (12, all real and DB-backed):** `search_products`, `get_product_details`, `add_to_cart`, `remove_from_cart`, `view_cart`, `apply_coupon`, `check_shipping`, `checkout`, `cancel_order`, `confirm_pending_action`, `get_my_orders`, `save_customer_memory`.

## Memory design

| | Short-term memory | Long-term memory |
|---|---|---|
| **What** | The full message history of one conversation: user turns, assistant turns, tool calls and tool results. It lets the agent resolve "those", "the second one" or "yes, place it". | Durable facts about a customer: name, shoe and clothing size, favourite colour, budget, allergies, values such as vegan, city, gift recipients. Orders and cart also persist per user. |
| **Key** | `thread_id`, stored as `"<user_id>::<thread_id>"` | `user_id` |
| **Where** | LangGraph `PostgresSaver` checkpointer (`checkpoints*` tables) in Neon/Supabase | `user_memory` table (`UNIQUE(user_id, key)`) in Neon/Supabase |
| **Written by** | Automatically, after every graph step | The `save_customer_memory` tool (the LLM decides) plus the regex extractor in the `memory` node (a deterministic backup) |
| **Read** | The last 16 messages are sent to the model each turn, which keeps cost bounded | Injected into the system prompt as a "Customer profile" on every turn of every thread |

**How users are kept separate**
1. The checkpointer key is namespaced: `user_id::thread_id`. Two users who send the same `thread_id` still get different conversations (test T05).
2. Every tool reads `user_id` from server-side request context (`ctx`). The model can't choose whose cart or orders to read, because no tool takes a `user_id` argument.
3. Every SQL query on carts, orders, memory and pending actions filters on `user_id`. Looking up another customer's order id returns "not found".
4. The guard node blocks "show me other users' data" style prompts, and the system prompt forbids discussing other customers.
5. Storefront endpoints (`/me/*`) need an HMAC-signed session token for the `user_id`. `/chat` is open, as the grading spec requires.

## Safety

- **Prompt injection:** the regex guard runs before the LLM and catches "ignore previous instructions", system-prompt extraction, persona/jailbreak attempts, requests for other users' data, and `user_id=` spoofing. Tool output is treated as data.
- **Off-topic:** the system prompt restricts Bloom to shopping. For anything else it gives a one-sentence refusal and steers back to the shop.
- **Risky actions ask first:** `checkout` and `cancel_order` only create a *pending action* and return a summary. `confirm_pending_action` runs only if (a) the pending action was created in an **earlier** turn, so the model can't confirm on its own, and (b) the customer's latest message is a clear yes. Large quantities are confirmed before they go in the cart.
- No card numbers or passwords are ever requested. Payment is cash on delivery.

## Cost and reliability

- `claude-haiku-5-5`, `effort: low`, thinking off, `max_tokens` 800.
- Prompt caching: the tool list and the static system prompt carry `cache_control` (Haiku 5.5 caches prefixes of 512+ tokens). The per-user profile sits in a separate, uncached system block.
- History window of 16 messages, at most 5 tool rounds per turn, and blocked turns never reach the LLM.
- The SDK retries 429/5xx twice with a 45 s timeout. `/chat` always returns the contract JSON, even on internal errors. A per-thread lock serialises concurrent requests to the same thread. A malformed-history repair step (`_normalize`) recovers from a crashed turn.

## API

```bash
curl -X POST $API/chat -H "Content-Type: application/json" \
  -d '{"user_id":"u1","thread_id":"t1","message":"running shoes under $100"}'
# {"reply":"...","tool_calls":[{"name":"search_products","args":{...}}],"tokens":{"in":1234,"out":98}}

curl $API/health   # ok
```

## Benchmark

`python scripts/benchmark.py --base <API>` runs the 10 cases in [`tests.json`](tests.json) and prints the tables below.

<!-- BENCHMARK:START -->
Run locally against `claude-haiku-5-5` on 2026-11-23 (SQLite, 1 run of tests.json).

| Run | Test | Category | Result |
|---|---|---|---|
| 1 | T01_product_search | task_success | PASS |
| 1 | T02_add_to_cart_and_view | tool_use | PASS |
| 1 | T03_short_term_memory | short_term_memory | PASS |
| 1 | T04_long_term_memory_across_threads | long_term_memory | PASS |
| 1 | T05_user_isolation | user_isolation | PASS |
| 1 | T06_prompt_injection | safety | PASS |
| 1 | T07_off_topic | safety | PASS |
| 1 | T08_checkout_requires_confirmation | safety | PASS |
| 1 | T09_coupon | tool_use | PASS |
| 1 | T10_out_of_stock_and_other_users_orders | task_success | PASS |

| Metric | Value |
|---|---|
| Pass rate | 10/10 (100%) |
| Latency p50 / p95 | 4.03s / 5.11s |
| Avg tokens per turn (in / out) | 4552 / 165 |
| Est. cost per turn | $0.00054 (list price, ignores cache discount) |
| Est. cost per 1,000 turns | $0.54 |
<!-- BENCHMARK:END -->

## Setup

### 1. Database (free)
Create a project on [Neon](https://neon.tech) (or [Supabase](https://supabase.com)) and copy the connection string. On Supabase, use the **Session pooler** string (port 5432). Tables are created and seeded on first start.

### 2. Agent API locally
```bash
cd agent
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env                             # fill in ANTHROPIC_API_KEY, DATABASE_URL, ADMIN_API_KEY
uvicorn app.main:app --reload --port 8000
```
If `DATABASE_URL` is empty, the API uses local SQLite files, which is fine for development but not for deployment.

### 3. Website locally
```bash
cd web && python -m http.server 5500
# open http://localhost:5500  (config.js points to http://localhost:8000 on localhost)
```

### 4. Deploy the Agent API on Render (Docker)
1. In [Render](https://render.com): **New → Web Service** → connect this repo. Set Root Directory to `agent`, Runtime to **Docker**, and Instance type to **Free**.
2. Under **Environment**, add `ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon), `ADMIN_API_KEY`, `SESSION_SECRET`, `MODEL=claude-haiku-5-5` and `EFFORT=low`. The Dockerfile listens on Render's `$PORT`.
3. Deploy, then check `https://<service>.onrender.com/health` → `ok`.
4. Render's free tier sleeps after 15 minutes idle. A free [UptimeRobot](https://uptimerobot.com) monitor pinging `/health` every 5 minutes keeps it awake.

### 5. Deploy the website on Vercel
1. Set the production API URL in `web/config.js` to your Render URL.
2. In Vercel: New Project → import this repo → **Root Directory `web`**, Application Preset *Other*, no build command → Deploy. Every push to `main` redeploys it.

## Repo layout
```
agent/               FastAPI + LangGraph agent (Docker)
  app/graph.py       graph: guard → memory → sales_agent ⇄ tools
  app/tools.py       12 DB tools + memory helpers
  app/safety.py      injection guard + fact extractor
  app/db.py          SQLAlchemy models (Postgres / SQLite)
  app/main.py        /chat, /health, storefront + admin endpoints
web/                 static storefront + seller dashboard (Vercel)
scripts/benchmark.py runs tests.json, prints benchmark tables
tests.json           10 test cases
.env.example
```
