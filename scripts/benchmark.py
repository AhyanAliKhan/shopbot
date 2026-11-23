"""Run tests.json against a running agent and print a markdown benchmark table.

    python scripts/benchmark.py --base http://localhost:8000
    python scripts/benchmark.py --base https://shopbot-pnm5.onrender.com --runs 2

Uses only the standard library. Each run gets fresh user ids (suffix) so runs don't collide.
"""
import argparse
import json
import statistics
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # emoji in replies crash the Windows console

IN_PRICE, OUT_PRICE = 0.10 / 1e6, 0.50 / 1e6  # claude-haiku-5-5 list price, USD per token


def post(base, payload, timeout=90):
    req = urllib.request.Request(base + "/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body, time.time() - t


def has_any(text, words):
    t = text.lower()
    return any(w.lower() in t for w in words)


def evaluate(check, results):
    replies = [r["reply"] for r in results]
    tools = [[c["name"] for c in r.get("tool_calls", [])] for r in results]
    all_tools = [n for ts in tools for n in ts]
    last, last_tools = replies[-1], tools[-1]
    ok = True
    for k, v in check.items():
        if k == "tools_include":
            ok &= all(x in all_tools for x in v)
        elif k == "last_tools_include":
            ok &= all(x in last_tools for x in v)
        elif k == "turn1_tools_exclude":
            ok &= not any(x in tools[0] for x in v)
        elif k == "tools_count":
            ok &= len(all_tools) == v
        elif k == "reply_contains_any":
            ok &= has_any(" ".join(replies), v)
        elif k == "reply_not_contains":
            ok &= not has_any(" ".join(replies), v)
        elif k == "last_reply_contains_any":
            ok &= has_any(last, v)
        elif k == "last_reply_contains_all":
            ok &= all(has_any(last, [w]) for w in v)
        elif k == "last_reply_not_contains":
            ok &= not has_any(last, v)
    return bool(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    cases = json.loads((Path(__file__).resolve().parent.parent / "tests.json").read_text(encoding="utf-8"))["cases"]

    rows, lat, tin, tout, passes, total = [], [], 0, 0, 0, 0
    for run in range(a.runs):
        sfx = uuid.uuid4().hex[:6]
        for c in cases:
            results, err = [], None
            for turn in c["turns"]:
                p = {**turn, "user_id": f'{turn["user_id"]}_{sfx}', "thread_id": f'{turn["thread_id"]}_{sfx}'}
                try:
                    body, dt = post(a.base, p)
                except Exception as e:
                    err = str(e)
                    break
                lat.append(dt)
                tin += body["tokens"]["in"]
                tout += body["tokens"]["out"]
                results.append(body)
                if a.verbose:
                    print(f'  [{c["id"]}] > {turn["message"]}\n    < {body["reply"][:300]}\n    tools={[t["name"] for t in body["tool_calls"]]} tokens={body["tokens"]} {dt:.1f}s')
            ok = (err is None) and evaluate(c["check"], results)
            passes += ok
            total += 1
            rows.append((run + 1, c["id"], c["category"], "PASS" if ok else "FAIL" + (f" ({err})" if err else "")))

    print("\n| Run | Test | Category | Result |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    turns = len(lat)
    cost = tin * IN_PRICE + tout * OUT_PRICE
    print("\n| Metric | Value |\n|---|---|")
    print(f"| Pass rate | {passes}/{total} ({100 * passes / max(total, 1):.0f}%) |")
    if lat:
        print(f"| Latency p50 / p95 | {statistics.median(lat):.2f}s / {sorted(lat)[int(0.95 * (turns - 1))]:.2f}s |")
    print(f"| Avg tokens per turn (in / out) | {tin // max(turns, 1)} / {tout // max(turns, 1)} |")
    print(f"| Est. cost per turn | ${cost / max(turns, 1):.5f} (list price, ignores cache discount) |")
    print(f"| Est. cost per 1,000 turns | ${1000 * cost / max(turns, 1):.2f} |")


if __name__ == "__main__":
    main()
