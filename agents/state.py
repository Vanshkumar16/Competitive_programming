"""Shared state + logging helpers used by all agents.

data/state.json:
{
  "codeforces": {"synced_ids": [...], "pending_ids": [...]},
  "leetcode":   {"synced_ids": [...]}
}
pending_ids = submissions committed as placeholders (no local source found
yet); the extractor re-checks them each run so they self-correct.
"""

import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "data", "state.json")
LOG_PATH = os.path.join(REPO_ROOT, "data", "sync_log.md")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        state = {}
    else:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    state.setdefault("codeforces", {}).setdefault("synced_ids", [])
    state["codeforces"].setdefault("pending_ids", [])
    state.setdefault("leetcode", {}).setdefault("synced_ids", [])
    return state


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def log(message: str) -> None:
    """Append a timestamped line to data/sync_log.md -- committed with each
    run, so failures are visible as diffs instead of buried in cron output."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Sync log\n\nMost recent runs at the bottom.\n\n")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"- `{ts}` {message}\n")
