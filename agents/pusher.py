"""Push agent: the ONLY module that writes to the repo or touches git.

Consumes the extractor's payload, writes solution files (versioned as
solution_<submission_id>.<ext> so nothing is ever overwritten), maintains
state.json / PENDING.md, then commits and pushes.

Safety: the orchestrator snapshots git state before calling push_to_git();
on unrecoverable failure it rolls the working tree back so a half-finished
run never leaves the repo dirty.
"""

import os
import subprocess
from dataclasses import dataclass

from .state import REPO_ROOT, load_state, save_state, log

PENDING_MD = os.path.join(REPO_ROOT, "PENDING.md")
SOLUTIONS = os.path.join(REPO_ROOT, "solutions")


@dataclass
class PushResult:
    new_count: int = 0
    upgraded_count: int = 0
    committed: bool = False
    pushed: bool = False
    error: str = ""


def _git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=check,
                          capture_output=True, text=True)


def write_items(items: list, state: dict) -> PushResult:
    """Write solution files + update state/PENDING. No git yet."""
    result = PushResult()
    pending = state["codeforces"]["pending_ids"]
    pending_labels = {}

    for item in sorted(items, key=lambda i: i.timestamp):
        pdir = os.path.join(SOLUTIONS, item.platform, item.dir_name)
        os.makedirs(pdir, exist_ok=True)
        real = os.path.join(pdir, f"solution_{item.submission_id}.{item.ext}")
        placeholder = os.path.join(pdir, f"NEEDS_SOURCE_{item.submission_id}.txt")
        was_pending = item.submission_id in pending

        if item.code is not None:
            with open(real, "w", encoding="utf-8") as f:
                f.write(item.code)
            if was_pending:
                pending.remove(item.submission_id)
                if os.path.exists(placeholder):
                    os.remove(placeholder)
                result.upgraded_count += 1
            else:
                result.new_count += 1
        else:
            with open(placeholder, "w", encoding="utf-8") as f:
                f.write(
                    f"# Solved {item.label} (submission {item.submission_id})\n"
                    f"# No local source found at sync time. Save your solution\n"
                    f"# into CF_LOCAL_SOLUTIONS_DIR and the next run will\n"
                    f"# replace this file automatically.\n"
                )
            if not was_pending:
                pending.append(item.submission_id)
                result.new_count += 1
            pending_labels[item.submission_id] = item.label

        synced = state[item.platform]["synced_ids"]
        if item.submission_id not in synced:
            synced.append(item.submission_id)

    _rewrite_pending_md(pending, pending_labels)
    save_state(state)
    return result


def _rewrite_pending_md(pending: list, labels: dict) -> None:
    lines = ["# Pending Codeforces solutions\n\n",
             "Accepted on Codeforces but no local source found yet. Save the\n",
             "real solution into CF_LOCAL_SOLUTIONS_DIR and it will be\n",
             "upgraded automatically on the next run.\n\n"]
    if not pending:
        lines.append("_Nothing pending right now._\n")
    else:
        for sid in sorted(pending):
            lines.append(f"- `{sid}` — {labels.get(sid, 'see solutions/codeforces')}\n")
    with open(PENDING_MD, "w", encoding="utf-8") as f:
        f.writelines(lines)


def push_to_git(result: PushResult, message: str) -> PushResult:
    """Stage, commit, push. Retry push once after pull --rebase."""
    try:
        _git("add", "-A")
        diff = _git("diff", "--cached", "--quiet", check=False)
        if diff.returncode == 0:
            return result  # nothing to commit
        _git("commit", "-m", message)
        result.committed = True
        try:
            _git("push")
            result.pushed = True
        except subprocess.CalledProcessError:
            # Remote may have moved on -- rebase and retry once.
            _git("pull", "--rebase")
            _git("push")
            result.pushed = True
    except subprocess.CalledProcessError as e:
        result.error = (e.stderr or str(e)).strip()
        log(f"**Push agent FAILED**: `{result.error}`")
    return result
