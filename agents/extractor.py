"""Extraction agent: talks to Codeforces and LeetCode APIs only.

Produces a list of Item payloads and NEVER touches the repo, disk state, or
git -- so an API bug here can't corrupt anything. The pusher consumes the
payload.

Codeforces: official API gives metadata only (never source code), so code
comes from matching your locally saved solutions (CF_LOCAL_SOLUTIONS_DIR).
If a key/secret pair is set (codeforces.com/settings/api), requests are
signed per codeforces.com/apiHelp for a personal rate limit.

LeetCode: unofficial GraphQL endpoint with session-cookie auth; returns
real source code.
"""

import glob
import hashlib
import os
import random
import string
import time
from dataclasses import dataclass
from typing import Optional

import requests

CF_API = "https://codeforces.com/api/user.status"
GRAPHQL_URL = "https://leetcode.com/graphql"

CF_LANG_EXT = {
    "GNU C++": "cpp", "GNU C++11": "cpp", "GNU C++14": "cpp", "GNU C++17": "cpp",
    "GNU C++20": "cpp", "MS C++": "cpp", "Clang++": "cpp",
    "Python 3": "py", "PyPy 3": "py", "Python 2": "py",
    "Java 8": "java", "Java 11": "java", "Java 17": "java",
    "Kotlin": "kt", "Go": "go", "Rust": "rs", "JavaScript": "js",
    "C#": "cs", "Ruby": "rb",
}
LC_LANG_EXT = {
    "python": "py", "python3": "py", "java": "java", "c": "c", "cpp": "cpp",
    "csharp": "cs", "javascript": "js", "typescript": "ts", "kotlin": "kt",
    "swift": "swift", "golang": "go", "ruby": "rb", "scala": "scala",
    "rust": "rs", "php": "php",
}

RECENT_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id title titleSlug timestamp lang
  }
}
"""
DETAIL_QUERY = """
query submissionDetails($submissionId: Int!) {
  submissionDetails(submissionId: $submissionId) { code lang { name } }
}
"""


@dataclass
class Item:
    platform: str          # "codeforces" | "leetcode"
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
    lc_error: Optional[str] = None


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


def find_local_source(local_dir: str, contest_id, index: str) -> Optional[str]:
    """Heuristic filename match; adjust patterns to your naming convention."""
    for pattern in (f"{contest_id}{index}.*", f"{contest_id}_{index}.*",
                    f"{contest_id}-{index}.*", f"{index}.*"):
        matches = glob.glob(os.path.join(local_dir, "**", pattern), recursive=True)
        if matches:
            return matches[0]
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

        items.append(Item(
            platform="codeforces",
            submission_id=sub_id,
            label=f"{cid}{idx} - {name}",
            dir_name=f"{cid}{idx}-{name.replace(' ', '_')}",
            ext=CF_LANG_EXT.get(lang, "txt"),
            code=code,
            timestamp=sub["creationTimeSeconds"],
        ))
        time.sleep(0.1)
    return items


# ---------------- LeetCode ----------------

def _lc_session() -> requests.Session:
    s = requests.Session()
    s.cookies.set("LEETCODE_SESSION", os.environ["LEETCODE_SESSION"], domain="leetcode.com")
    s.cookies.set("csrftoken", os.environ["LEETCODE_CSRF_TOKEN"], domain="leetcode.com")
    s.headers.update({
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "x-csrftoken": os.environ["LEETCODE_CSRF_TOKEN"],
        "User-Agent": "Mozilla/5.0 (streak-sync-bot)",
    })
    return s


def extract_leetcode(known_ids: set, limit: int = 40) -> list:
    s = _lc_session()
    resp = s.post(GRAPHQL_URL, json={"query": "query { userStatus { username } }"}, timeout=30)
    resp.raise_for_status()
    username = resp.json()["data"]["userStatus"]["username"]
    if not username:
        raise RuntimeError("LeetCode cookie expired -- refresh LEETCODE_SESSION/CSRF")

    resp = s.post(GRAPHQL_URL, json={
        "query": RECENT_QUERY, "variables": {"username": username, "limit": limit},
    }, timeout=30)
    resp.raise_for_status()
    subs = resp.json()["data"]["recentAcSubmissionList"]
    subs.sort(key=lambda x: int(x["timestamp"]))

    items = []
    for sub in subs:
        sub_id = str(sub["id"])
        if sub_id in known_ids:
            continue
        resp = s.post(GRAPHQL_URL, json={
            "query": DETAIL_QUERY, "variables": {"submissionId": int(sub_id)},
        }, timeout=30)
        resp.raise_for_status()
        detail = resp.json()["data"]["submissionDetails"]
        items.append(Item(
            platform="leetcode",
            submission_id=sub_id,
            label=sub["title"],
            dir_name=sub["titleSlug"],
            ext=LC_LANG_EXT.get(sub.get("lang", "").lower(), "txt"),
            code=detail["code"],
            timestamp=int(sub["timestamp"]),
        ))
        time.sleep(0.5)
    return items


# ---------------- entry ----------------

def run(platforms: set, state: dict) -> ExtractionResult:
    """Failures are captured per-platform, never raised past this point --
    one platform breaking must not discard the other's results."""
    result = ExtractionResult(items=[])
    if "codeforces" in platforms:
        try:
            result.items += extract_codeforces(
                set(state["codeforces"]["synced_ids"]),
                set(state["codeforces"]["pending_ids"]),
            )
        except Exception as e:
            result.cf_error = str(e)
    if "leetcode" in platforms:
        try:
            result.items += extract_leetcode(set(state["leetcode"]["synced_ids"]))
        except Exception as e:
            result.lc_error = str(e)
    return result
