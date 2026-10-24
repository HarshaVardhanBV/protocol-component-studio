"""
config.py — bridge Streamlit secrets into environment variables.

Streamlit reads `.streamlit/secrets.toml` automatically; plain scripts and the
Anthropic / Neo4j clients read `os.environ`. `load_secrets()` copies the former
into the latter so both worlds use one source of truth. No-op if the file is
absent (e.g. in CI or the sandbox), so importing/using this never crashes.
"""
from __future__ import annotations

import os
import pathlib

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

SECRETS_PATH = pathlib.Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"


def load_secrets(path: pathlib.Path = SECRETS_PATH, override: bool = True) -> None:
    """Load top-level keys from secrets.toml into os.environ.

    override=True (default): secrets.toml WINS over any pre-existing shell env var,
    so the repo's secrets file is the single source of truth and a stray exported
    key (e.g. a leftover `export ANTHROPIC_API_KEY=...`) can never shadow it. This is
    the `load_dotenv(override=True)` lesson, applied here.
    Pass override=False to defer to values already set in the environment.
    Silently does nothing if the file or tomllib is unavailable."""
    if tomllib is None or not path.exists():
        return
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for key, value in data.items():
        if isinstance(value, (str, int, float)) and (override or key not in os.environ):
            os.environ[key] = str(value)
