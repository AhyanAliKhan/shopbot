"""Guard node logic: cheap, deterministic checks that run before the LLM.

Blocking obvious prompt injection here costs zero tokens. Subtler off-topic
requests are handled by the sales agent's system prompt.
"""
import re

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules?|prompts?|guidelines?|polic(y|ies)|system)\b",
    r"\b(system|developer|hidden|initial|original)\s+(prompt|message|instructions?)\b",
    r"\b(reveal|print|show|repeat|leak|output)\b.{0,30}\b(your|the)\s+(prompt|instructions|rules|configuration|api key)\b",
    r"\byou are now\b|\bfrom now on you (are|will)\b|\bnew persona\b",
    r"\b(jailbreak|DAN mode|developer mode|god mode|admin mode|sudo mode)\b",
    r"\bpretend (to be|you are)\b.{0,40}\b(unrestricted|without rules|no limits|evil|hacker)\b",
    r"\b(other|another|all|every)\s+(users?|customers?)('s?)?\s+(data|orders?|carts?|memor(y|ies)|info|details|emails?|addresses)\b",
    r"\b(user_id|thread_id)\s*[:=]",
    r"</?(system|instructions?|admin)>",
    r"\b(api[_ ]?key|password|credentials?)\b.{0,20}\b(give|show|tell|send)\b|\b(give|show|tell|send)\b.{0,20}\b(api[_ ]?key|password|credentials?)\b",
]
_INJECTION_RE = [re.compile(p, re.I | re.S) for p in INJECTION_PATTERNS]

REFUSAL_INJECTION = (
    "I can't do that. I'm the shop assistant, so I only help with products, your cart, "
    "orders and delivery, and I can't change my rules or share anyone else's data. "
    "What can I help you find today?"
)


def check_message(text: str) -> tuple[bool, str | None]:
    """Return (blocked, reason)."""
    for rx in _INJECTION_RE:
        if rx.search(text):
            return True, "prompt_injection"
    return False, None


# ---- deterministic long-term-memory extraction (backup for the LLM tool) ----
_NAME_STOP = {"looking", "interested", "trying", "here", "back", "fine", "good", "new", "not", "just",
              "a", "an", "the", "so", "very", "really", "going", "vegan", "vegetarian", "allergic"}
FACT_PATTERNS = [
    # prefix is case-insensitive; a surname is only taken if Capitalised ("Dave Khan", not "Dave and")
    ("name", re.compile(r"\b(?i:my name is|my name's|call me)\s+([A-Za-z][a-z\-']{1,30}(?:\s+[A-Z][a-z\-']{1,30})?)\b")),
    ("name", re.compile(r"\b(?i:i am|i'm)\s+([A-Z][a-z\-']{1,30})\b(?=\s*(?:[,.!]|$|(?i:and)\b))")),
    ("shoe_size", re.compile(r"\b(?:shoe size|i wear (?:a )?size|my size is)\s*(?:is\s*)?(\d{2}(?:\.\d)?)\b", re.I)),
    ("clothing_size", re.compile(r"\b(?:clothing size|shirt size|i wear (?:a )?size|my size is)\s*(?:is\s*)?(XXS|XS|S|M|L|XL|XXL|small|medium|large)\b", re.I)),
    ("city", re.compile(r"\b(?:i live in|i'm from|i am from|i'm based in|ship(?:ping)? to|deliver(?:y)? to)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)", re.I)),
    ("diet_or_values", re.compile(r"\b(i(?:'m| am) (?:vegan|vegetarian))\b", re.I)),
    ("allergy", re.compile(r"\b(?:i(?:'m| am) allergic to|allergy to)\s+([a-z ]{2,30}?)(?:[,.!]|$| and )", re.I)),
    ("favorite_color", re.compile(r"\b(?:my )?fav(?:ou?rite)? colou?r is\s+([a-z]{3,15})\b", re.I)),
    ("budget", re.compile(r"\bmy budget is\s+(\$?\s?\d+(?:\.\d+)?\s?\$?)", re.I)),
]


def extract_facts(text: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for key, rx in FACT_PATTERNS:
        if key in facts:
            continue
        m = rx.search(text)
        if not m:
            continue
        val = m.group(1).strip(" .,!")
        if key == "name" and val.split()[0].lower() in _NAME_STOP:
            continue
        facts[key] = val.title() if key in ("name", "city") else val
    return facts
