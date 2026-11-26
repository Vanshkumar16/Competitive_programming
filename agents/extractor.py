"""Extraction agent: talks to Codeforces API only.

Produces a list of Item payloads and NEVER touches the repo, disk state, or
git -- so an API bug here can't corrupt anything. The pusher consumes the
payload.

Codeforces: official API gives metadata only (never source code), so code
comes from matching your locally saved solutions (CF_LOCAL_SOLUTIONS_DIR).
If a key/secret pair is set (codeforces.com/settings/api), requests are
signed per codeforces.com/apiHelp for a personal rate limit.
"""

import glob
import hashlib
import os
import random
import re
import string
import time
from dataclasses import dataclass
from typing import Optional

import requests

CF_API = "https://codeforces.com/api/user.status"

CF_LANG_EXT = {
    "GNU C++": "cpp", "GNU C++11": "cpp", "GNU C++14": "cpp", "GNU C++17": "cpp",
    "GNU C++20": "cpp", "MS C++": "cpp", "Clang++": "cpp",
    "Python 3": "py", "PyPy 3": "py", "Python 2": "py",
    "Java 8": "java", "Java 11": "java", "Java 17": "java",
    "Kotlin": "kt", "Go": "go", "Rust": "rs", "JavaScript": "js",
    "C#": "cs", "Ruby": "rb",
}


@dataclass
class Item:
    platform: str          # "codeforces"
    submission_id: str
    label: str             # human-readable, e.g. "1234A - Watermelon"
    dir_name: str          # folder name under solutions/<platform>/
    ext: str
    code: Optional[str]    # None => no source available (CF placeholder case)
    timestamp: int


@dataclass
class ExtractionResult:
    items: list
    cf_error: Optional[str] = None


# ---------------- Codeforces ----------------

def build_signed_params(method: str, params: dict, key: str, secret: str) -> dict:
    """Codeforces' official signing scheme (codeforces.com/apiHelp)."""
    p = dict(params)
    p["apiKey"] = key
    p["time"] = str(int(time.time()))
    sorted_query = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
    rand = "".join(random.choices(string.digits, k=6))
    digest = hashlib.sha512(f"{rand}/{method}?{sorted_query}#{secret}".encode()).hexdigest()
    p["apiSig"] = rand + digest
    return p


def sanitize_dir_name(name: str) -> str:
    """Strip filesystem-illegal characters and trim whitespace/dots."""
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name).strip().replace(' ', '_')
    cleaned = cleaned.rstrip('. ')
    return cleaned or "unknown"


def find_local_source(local_dir: str, contest_id, index: str) -> Optional[str]:
    """Heuristic filename match; matches combinations like 1234A.*, 1234_a.*,
    or A.* inside a contest-named subfolder. Avoids loose global single-letter matching."""
    if not contest_id or not index:
        return None
    cid_str = str(contest_id).strip()
    idx_str = str(index).strip()
    candidates = {
        f"{cid_str}{idx_str}".lower(),
        f"{cid_str}_{idx_str}".lower(),
        f"{cid_str}-{idx_str}".lower(),
    }

    for root, _, files in os.walk(local_dir):
        rel_root = os.path.relpath(root, local_dir)
        is_contest_dir = (
            rel_root.lower() == cid_str.lower() or
            os.path.basename(root).lower() == cid_str.lower()
        )
        for file in files:
            base, _ = os.path.splitext(file)
            base_lower = base.lower()
            if base_lower in candidates:
                return os.path.join(root, file)
            if is_contest_dir and base_lower == idx_str.lower():
                return os.path.join(root, file)
    return None


def extract_codeforces(known_ids: set, pending_ids: set) -> list:
    handle = os.environ["CF_HANDLE"]
    key, secret = os.environ.get("CF_API_KEY"), os.environ.get("CF_API_SECRET")
    local_dir = os.environ.get("CF_LOCAL_SOLUTIONS_DIR")

    params = {"handle": handle}
    if key and secret:
        params = build_signed_params("user.status", params, key, secret)

    resp = requests.get(CF_API, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "OK":
        raise RuntimeError(f"Codeforces API error: {payload}")

    accepted = [s for s in payload["result"] if s.get("verdict") == "OK"]
    accepted.sort(key=lambda s: s["creationTimeSeconds"])

    items = []
    for sub in accepted:
        sub_id = str(sub["id"])
        # Skip fully-synced items; re-visit pending ones (self-correct loop).
        if sub_id in known_ids and sub_id not in pending_ids:
            continue
        prob = sub["problem"]
        cid, idx = prob.get("contestId"), prob.get("index")
        name = prob.get("name", "unknown")
        lang = sub.get("programmingLanguage", "")

        code = None
        if local_dir:
            src = find_local_source(local_dir, cid, idx)
            if src:
                with open(src, "r", encoding="utf-8", errors="ignore") as f:
                    code = f.read()

        if sub_id in pending_ids and code is None:
            continue  # still nothing new for this pending item

        safe_name = sanitize_dir_name(str(name))
        items.append(Item(
            platform="codeforces",
            submission_id=sub_id,
            label=f"{cid}{idx} - {name}",
            dir_name=f"{cid}{idx}-{safe_name}",
            ext=CF_LANG_EXT.get(lang, "txt"),
            code=code,
            timestamp=sub["creationTimeSeconds"],
        ))
        time.sleep(0.1)
    return items


# ---------------- entry ----------------

def run(platforms: set = None, state: dict = None) -> ExtractionResult:
    """Failures are captured, never raised past this point."""
    if state is None and isinstance(platforms, dict):
        state = platforms
    if state is None:
        state = {}
    result = ExtractionResult(items=[])
    try:
        cf_state = state.get("codeforces", {})
        result.items += extract_codeforces(
            set(cf_state.get("synced_ids", [])),
            set(cf_state.get("pending_ids", [])),
        )
    except Exception as e:
        result.cf_error = str(e)
    return result
