#!/usr/bin/env python3
"""Orchestrator: the single entry point. Your cron / Task Scheduler /
GitHub Actions workflow calls THIS, never the agents directly.

Sequence and failure policy:
  1. Preflight  -- if a platform fails its checks, that platform is dropped
                   from the run (and logged). If ALL platforms fail, stop.
  2. Extraction -- per-platform errors are captured, not raised; whatever
                   succeeded still flows to the pusher.
  3. Push       -- git state is snapshotted first; on unrecoverable git
                   failure the working tree is rolled back so no half-done
                   run is ever left behind.

Usage:
  python orchestrator.py                       # both platforms (local cron)
  python orchestrator.py --platforms leetcode  # cloud workflow (no local FS)
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agents import preflight, extractor, pusher  # noqa: E402
from agents.state import REPO_ROOT, load_state, log  # noqa: E402


def load_dotenv() -> None:
    """Minimal .env loader (no dependency needed)."""
    path = os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def git_snapshot() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_rollback(snapshot: str) -> None:
    if snapshot:
        subprocess.run(["git", "reset", "--hard", snapshot], cwd=REPO_ROOT,
                       capture_output=True, text=True)
        subprocess.run(["git", "clean", "-fd", "solutions", "data"],
                       cwd=REPO_ROOT, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platforms", default="codeforces,leetcode",
                        help="comma-separated: codeforces,leetcode")
    parser.add_argument("--no-push", action="store_true",
                        help="write files + state but skip git (for testing)")
    args = parser.parse_args()
    requested = {p.strip() for p in args.platforms.split(",") if p.strip()}

    load_dotenv()

    # ---- Stage 1: preflight ----
    report = preflight.run(requested)
    active = set()
    if "codeforces" in requested and report.cf_ok:
        active.add("codeforces")
    if "leetcode" in requested and report.lc_ok:
        active.add("leetcode")

    dropped = requested - active
    if dropped:
        log(f"**Preflight dropped {', '.join(sorted(dropped))}**: {report.summary()}")
    if not active:
        log(f"**Run aborted -- preflight failed for all platforms**: {report.summary()}")
        print(f"Preflight failed: {report.summary()}")
        return 1
    print(f"Preflight OK for: {', '.join(sorted(active))}")

    # ---- Stage 2: extraction (read-only, safe) ----
    state = load_state()
    extraction = extractor.run(active, state)
    if extraction.cf_error:
        log(f"**Codeforces extraction FAILED**: `{extraction.cf_error}`")
        print(f"Codeforces extraction failed: {extraction.cf_error}")
    if extraction.lc_error:
        log(f"**LeetCode extraction FAILED**: `{extraction.lc_error}`")
        print(f"LeetCode extraction failed: {extraction.lc_error}")
    if not extraction.items:
        log("Run complete: nothing new.")
        print("Nothing new to sync.")
        # Still commit the log line if we're pushing, so failures surface.
        if not args.no_push:
            pusher.push_to_git(pusher.PushResult(),
                               f"sync: log update {_now()}")
        return 0

    # ---- Stage 3: push (snapshot -> write -> commit -> push) ----
    snapshot = git_snapshot()
    try:
        result = pusher.write_items(extraction.items, state)
        summary = (f"{result.new_count} new, {result.upgraded_count} upgraded "
                   f"({', '.join(sorted(active))})")
        log(f"Run complete: {summary}")
        if not args.no_push:
            result = pusher.push_to_git(result, f"sync: {summary} {_now()}")
            if result.committed and not result.pushed:
                git_rollback(snapshot)
                print(f"Push failed, rolled back: {result.error}")
                return 1
        print(f"Done: {summary}")
        return 0
    except Exception as e:
        git_rollback(snapshot)
        log(f"**Push stage crashed, rolled back**: `{e}`")
        print(f"Push stage crashed, rolled back: {e}")
        return 1


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    sys.exit(main())
