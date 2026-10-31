"""config.py — loads environment variables from .env and exposes typed constants.

All other modules import from here; never use os.environ directly in feature code.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (two levels up from src/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env", override=False)


def _require(name: str) -> str:
    """Return env var or raise a clear error."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {name}. Copy .env.example ? .env and fill it in."
        )
    return val


# -- Groq / LLM ----------------------------------------------------------------
GROQ_API_KEY: str = _require("GROQ_API_KEY")
ORCH_MODEL: str = os.getenv("ORCH_MODEL", "openai/gpt-oss-120b")
SOLVER_MODEL: str = os.getenv("SOLVER_MODEL", "llama-3.3-70b-versatile")
FAST_MODEL: str = os.getenv("FAST_MODEL", "llama-3.1-8b-instant")

# -- Feature flags --------------------------------------------------------------
CHAOS_MODE: bool = os.getenv("CHAOS_MODE", "0").strip() not in ("0", "false", "")

# -- Paths ----------------------------------------------------------------------
DATA_DIR: Path = _ROOT / "data"
REPORTS_DIR: Path = _ROOT / "reports"
DB_PATH: Path = DATA_DIR / "qbank.db"
GROUND_TRUTH_PATH: Path = DATA_DIR / "ground_truth.json"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# -- Agent limits ---------------------------------------------------------------
MAX_STEPS: int = 30
MAX_SOLVER_CALLS: int = 40
