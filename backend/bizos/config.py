"""Settings from the repo-root .env (real environment variables win). Secrets stay server-side."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.lstrip().startswith("#"))
    return {k.strip(): v.strip().strip('"').strip("'") for k, v in pairs}


_env = {**_load_env(ROOT / ".env"), **os.environ}

AGENT_API_KEY = _env.get("AGENT_API_KEY", "")
AGENT_BASE_URL = _env.get("AGENT_BASE_URL", "").rstrip("/")
AGENT_MODEL = _env.get("AGENT_MODEL", "")
PAYPAL_CLIENT_ID = _env.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = _env.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_SANDBOX_RECEIVER = _env.get("PAYPAL_SANDBOX_RECEIVER", "")  # a sandbox personal account, so test money settles
PAYPAL_RETURN_URL = _env.get("PAYPAL_RETURN_URL", "https://www.paypal.com")  # where a payment link sends buyers after paying
PAYPAL_BASE_URL = _env.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
EXTENSION_TOKEN = _env.get("BIZOS_EXTENSION_TOKEN", "")
DB_PATH = Path(_env.get("BIZOS_DB", ROOT / "data" / "mock" / "bizos.db"))
AUDIT_PATH = Path(_env.get("BIZOS_AUDIT", ROOT / "app" / "backend" / "audit.jsonl"))
MEMORY_PATH = Path(_env.get("BIZOS_MEMORY", Path.home() / ".bizos" / "memory.db"))  # long-term memory, local
