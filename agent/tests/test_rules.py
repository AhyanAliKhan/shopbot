"""No-LLM checks for the rule-based parts. Run from agent/: python -m pytest tests -q"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")

from app import tools  # noqa: E402
from app.db import init_db  # noqa: E402
from app.safety import extract_facts  # noqa: E402

init_db()


def ctx(turn, msg=""):
    return {"user_id": "u_test", "turn_id": turn, "user_message": msg}


def test_city_needs_capital():
    assert "city" not in extract_facts("please ship to my house")
    assert extract_facts("ship to Lahore please")["city"] == "Lahore"


def test_confirm_flow():
    tools.add_to_cart(ctx("t1"), "P005", 1)
    assert tools.checkout(ctx("t1"), "Lahore")["status"] == "awaiting_confirmation"
    assert "error" in tools.confirm_pending_action(ctx("t1", "yes"))                  # same turn
    assert "error" in tools.confirm_pending_action(ctx("t2", "no, don't go ahead"))   # negated yes
    tools.add_to_cart(ctx("t2"), "P011", 1)                                          # cart changed
    assert "changed" in tools.confirm_pending_action(ctx("t3", "yes"))["error"]
    tools.checkout(ctx("t4"), "Lahore")
    assert "order_placed" in tools.confirm_pending_action(ctx("t5", "yes please"))
