"""Preflight agent: validates everything the pipeline needs BEFORE any
fetching or writing happens. Read-only -- never touches disk state or git.

Returns a PreflightReport; the orchestrator stops the run if .ok is False
for every requested platform.
"""

import os
from dataclasses import dataclass, field

import requests

GRAPHQL_URL = "https://leetcode.com/graphql"


@dataclass
class PreflightReport:
    cf_ok: bool = False
    lc_ok: bool = False
    checks: list = field(default_factory=list)   # (name, passed, detail)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))

    def summary(self) -> str:
        return "; ".join(
            f"{name}: {'ok' if passed else 'FAIL'}{f' ({detail})' if detail and not passed else ''}"
            for name, passed, detail in self.checks
        )


def check_codeforces(report: PreflightReport) -> None:
    handle = os.environ.get("CF_HANDLE")
    if not handle:
        report.add("CF_HANDLE", False, "not set")
        return
    report.add("CF_HANDLE", True)

    key, secret = os.environ.get("CF_API_KEY"), os.environ.get("CF_API_SECRET")
    if bool(key) != bool(secret):
        report.add("CF_API_KEY/SECRET", False, "only one of the pair is set")
        return
    report.add("CF_API_KEY/SECRET", True, "signed mode" if key else "anonymous mode")

    local_dir = os.environ.get("CF_LOCAL_SOLUTIONS_DIR")
    if local_dir and not os.path.isdir(local_dir):
        report.add("CF_LOCAL_SOLUTIONS_DIR", False, f"not a directory: {local_dir}")
        return
    report.add("CF_LOCAL_SOLUTIONS_DIR", True,
               "set" if local_dir else "not set -- placeholders only")
    report.cf_ok = True


def check_leetcode(report: PreflightReport) -> None:
    sess, csrf = os.environ.get("LEETCODE_SESSION"), os.environ.get("LEETCODE_CSRF_TOKEN")
    if not sess or not csrf:
        report.add("LEETCODE cookies", False, "LEETCODE_SESSION/LEETCODE_CSRF_TOKEN not set")
        return
    report.add("LEETCODE cookies", True)

    # Live auth ping: catches an expired cookie up-front, before extraction.
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": "query { userStatus { username } }"},
            cookies={"LEETCODE_SESSION": sess, "csrftoken": csrf},
            headers={"Content-Type": "application/json",
                     "Referer": "https://leetcode.com",
                     "x-csrftoken": csrf,
                     "User-Agent": "Mozilla/5.0 (streak-sync-bot)"},
            timeout=30,
        )
        resp.raise_for_status()
        username = resp.json()["data"]["userStatus"]["username"]
        if username:
            report.add("LeetCode auth ping", True)
            report.lc_ok = True
        else:
            report.add("LeetCode auth ping", False, "cookie expired -- refresh it")
    except Exception as e:
        report.add("LeetCode auth ping", False, str(e))


def run(platforms: set) -> PreflightReport:
    report = PreflightReport()
    if "codeforces" in platforms:
        check_codeforces(report)
    if "leetcode" in platforms:
        check_leetcode(report)
    return report
