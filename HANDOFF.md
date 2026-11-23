# HANDOFF: ShopBot (Bazaar Bloom), hackathon Track 1

Last updated: 2026-11-23. Repo: https://github.com/AhyanAliKhan/shopbot

This file lets you (or Claude Code) pick up the work on another machine. Delete it before final submission if you like.

---

## 1. Where things stand

| Item | Status |
|---|---|
| LangGraph agent API (FastAPI) in `agent/` | ✅ Built. Runs locally. Health, guard, tools, confirm flow, isolation and admin endpoints tested without the LLM. |
| Storefront (`web/index.html`) + seller dashboard (`web/admin.html`) | ✅ Built. Storefront checked visually against the local API. |
| `tests.json` (10 cases) + `scripts/benchmark.py` | ✅ Written. ❌ **Never run against Claude yet** (no API key was configured). |
| README (architecture diagram, memory design, setup, deploy) | ✅ Written. Still has placeholders: live URLs, demo GIF, benchmark table. |
| `.env.example`, `.gitignore` | ✅ |
| GitHub repo (public) | ✅ https://github.com/AhyanAliKhan/shopbot |
| Website on Vercel | ⏳ Import page opened, deploy not confirmed. See step 3. |
| Agent API hosting (HF Spaces) | ❌ Not started |
| Postgres (Neon/Supabase) | ❌ Not started |
| Claude API key wired in | ❌ Not done. Key is in the group leader's email. |
| Demo video, demo GIF, canvas photo link | ❌ Yours to make |

---

## 2. Set up on the new laptop

Needs Python 3.11+ (tested on 3.14), Git, and optionally Node.

```bash
git clone https://github.com/AhyanAliKhan/shopbot.git
cd shopbot/agent
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
```

Edit `agent/.env`:
- `ANTHROPIC_API_KEY=`: the group key. **Never commit it** (`.env` is gitignored).
- `ADMIN_API_KEY=`: any long random string. This is the password for `admin.html`.
- `SESSION_SECRET=`: another long random string.
- `DATABASE_URL=`: leave empty to use local SQLite, or paste the Neon URL (step 4).

The old `.env` and the local SQLite files stayed on the first laptop and are **not** in git. That's fine: the database seeds itself on first start.

Run:
```bash
uvicorn app.main:app --port 8000        # from shopbot/agent
# in another terminal:
cd shopbot/web && python -m http.server 5500   # open http://localhost:5500
```

Smoke test:
```bash
curl localhost:8000/health    # -> ok
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"user_id":"u1","thread_id":"t1","message":"running shoes under $100"}'
```

---

## 3. Remaining steps, in order

### Step A: First real LLM test and benchmark (do this first)
1. Put the key in `agent/.env` and restart uvicorn.
2. Run `python scripts/benchmark.py --base http://localhost:8000 --verbose`.
3. Fix any failing case. Likely tuning spots:
   - `SYSTEM_PROMPT` in `agent/app/graph.py`
   - tool descriptions in `agent/app/tools.py` (`TOOL_SPECS`)
   - regexes in `agent/app/safety.py`
4. Paste the two printed tables into the README between `<!-- BENCHMARK:START -->` and `<!-- BENCHMARK:END -->`.
5. Budget: Haiku 5.5 costs about $0.10 per million input tokens and $0.50 per million output tokens, so one full benchmark run costs well under one cent. The $2 limit is plenty, but don't loop it thousands of times.

**Unverified assumption to watch:** the agent calls the API with `thinking={"type":"disabled"}` plus `output_config={"effort":"low"}`. Per the docs this is valid for `claude-haiku-5-5` at effort low/medium/high. If the first call returns a 400 about thinking or effort, remove `thinking=...` and keep `effort: low`. Adaptive thinking would then be on, so the history must stay append-only. That's already true, except that `_normalize()` trims to the last 16 messages; if that causes 400s on long threads, raise `HISTORY_WINDOW`.

### Step B: Database (Neon, free)
1. Go to https://neon.tech → New project → copy the connection string (`postgresql://...?sslmode=require`).
2. Put it in `DATABASE_URL` in `agent/.env`, restart, and run the benchmark again. Tables and the LangGraph checkpoint tables are created automatically.
3. On Supabase instead, use the **Session pooler** URL (port 5432). The code already sets `prepare_threshold=None` for poolers.

### Step C: Agent API on Hugging Face Spaces (Docker)
1. Go to https://huggingface.co/new-space → SDK **Docker** → Blank → Public.
2. Clone the Space repo and copy in everything inside `shopbot/agent/` (`Dockerfile`, `requirements.txt`, `app/`).
3. Create a `README.md` in the Space with this header:
   ```yaml
   ---
   title: ShopBot Agent
   emoji: 🌸
   sdk: docker
   app_port: 7860
   ---
   ```
4. Under Space Settings → Variables and secrets, add the secrets `ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon), `ADMIN_API_KEY` and `SESSION_SECRET`.
5. Push, wait for the build, then check `https://<user>-<space>.hf.space/health` returns `ok`.
6. Run the benchmark against it: `python scripts/benchmark.py --base https://<user>-<space>.hf.space`.

Don't use Render's free tier for grading: it sleeps after 15 minutes and the first request takes about 50 seconds, which would hurt the reliability score.

### Step D: Point the website at the API and deploy on Vercel
1. In `web/config.js`, replace `https://YOUR-SPACE.hf.space` with the real Space URL. Commit and push.
2. In Vercel (sign in with GitHub as AhyanAliKhan), go to https://vercel.com/new/import?s=https://github.com/AhyanAliKhan/shopbot
   - **Root Directory: `web`** (important)
   - Framework/Application Preset: **Other**, no build command
   - Deploy
3. If the project was already imported, every push to `main` redeploys it automatically.
4. Check `https://<project>.vercel.app` (the store) and `/admin.html` (enter `ADMIN_API_KEY`).

### Step E: Submission material
- [ ] README: fill in the live store URL, admin URL, API URL, demo video link and canvas photo link (top table).
- [ ] Demo GIF at `docs/demo.gif` (README references it). Record the chat: search → add → checkout → "yes" → order shows in admin.
- [ ] 2–3 minute demo video (YouTube unlisted / Drive "anyone with link"). Suggested script:
  1. storefront and chat
  2. personal fact, then a new chat showing it's remembered
  3. checkout that asks first, then yes
  4. injection attempt and an off-topic request, both refused
  5. admin dashboard: orders, conversations, tool usage, spend
  6. `curl /chat`
- [ ] Canvas photo on Drive (anyone with link).
- [ ] Make sure no key is committed: `git log -p | grep -i "sk-ant"` should print nothing.

---

## 4. Design facts (so you don't have to re-derive them)

- **Graph:** `guard` → `memory` → `sales_agent` ⇄ `tools` (LangGraph `StateGraph`, `agent/app/graph.py`).
  - `guard`: regex prompt-injection block, no LLM call (0 tokens).
  - `memory`: loads the `user_memory` table and runs a regex fact extractor (name, sizes, city, vegan, allergy, colour, budget).
  - `sales_agent`: calls Claude through the official `anthropic` SDK (not langchain-anthropic).
  - `tools`: executes tool calls.
- **Short-term memory:** LangGraph checkpointer (PostgresSaver, or SqliteSaver locally). The `thread_id` is namespaced as `user_id::thread_id`, so users never share a thread.
- **Long-term memory:** `user_memory(user_id, key, value)` table, written by the `save_customer_memory` tool and by the regex extractor.
- **Isolation:** tools take `user_id` from server context (`ctx`), never from model arguments. Every query filters on `user_id`.
- **Risky actions:** `checkout` / `cancel_order` create a `pending_actions` row tagged with the `turn_id`. `confirm_pending_action` refuses in the same turn, and refuses unless the latest user message is a clear yes (`AFFIRMATIVE_RE`).
- **12 tools**, all backed by the database: search, details, add/remove/view cart, coupon, shipping, checkout, cancel, confirm, orders, save memory.
- **Coupons:** `WELCOME10` (10% off), `BLOOM20` (20% off over $100), `FREESHIP`. Shipping is $5.99, free at $50+ after discount.
- **Cost settings:** Haiku 5.5, effort low, max_tokens 800, prompt caching on tools and the system prompt, a 16-message window, and at most 5 tool rounds.
- **API contract:** `POST /chat` → `{"reply", "tool_calls":[{"name","args"}], "tokens":{"in","out"}}`. `GET /health` → plain-text `ok`. It never returns a non-contract body, even on errors.
- **Storefront auth:** passwordless email → `user_id = u_<sha256[:16]>` + HMAC token, used for `/me/*`. Guests get an auto guest email.
- Admin endpoints need the `X-Admin-Key` header.

## 5. Resume prompt for Claude Code

Open the cloned `shopbot` folder in Claude Code and paste:

> Read HANDOFF.md. This is our hackathon ShopBot project. Continue from "Remaining steps": first help me run the benchmark against Claude with our key in agent/.env (don't print the key), fix failures, then deploy the agent to Hugging Face Spaces with a Neon database, update web/config.js and redeploy the Vercel site, and fill the README placeholders.
