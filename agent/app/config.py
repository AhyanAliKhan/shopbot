"""Central configuration, read once from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-haiku-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "800"))
EFFORT = os.getenv("EFFORT", "low")

# Postgres (Neon / Supabase) in production; SQLite file locally.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./shopbot.db"

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-me-admin")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-session-secret")
STORE_NAME = os.getenv("STORE_NAME", "Bazaar Bloom")

# How many past messages of a thread are sent to the model (cost control).
HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "16"))
# Max agent <-> tool round trips in one turn.
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "5"))
MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "2000"))

IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))


def sqlalchemy_url() -> str:
    """SQLAlchemy needs the psycopg (v3) driver name in the URL."""
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def libpq_url() -> str:
    """The LangGraph Postgres checkpointer wants a plain libpq URL."""
    url = DATABASE_URL
    for prefix in ("postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    return url
