# cf-leetcode-streak-sync (agent architecture, personal use)

Turns your Accepted Codeforces and LeetCode submissions into git commits
automatically. Built as four single-responsibility agents coordinated by an
orchestrator, so any one failure is detected, isolated, and recovered from
without taking down the rest of the pipeline.

## Architecture

```
                    ┌──────────────────┐
   cron / Actions ─▶│  orchestrator.py │   the ONLY entry point
                    └───────┬──────────┘
              ┌─────────────┼─────────────────┐
              ▼             ▼                 ▼
      ┌──────────────┐ ┌─────────────┐ ┌────────────┐
      │ preflight.py │ │ extractor.py│ │ pusher.py  │
      │ env + auth   │ │ CF + LC API │ │ files, state,│
      │ checks only  │ │ fetch only  │ │ git commit  │
      └──────────────┘ └─────────────┘ └────────────┘
```

- **Preflight agent** (`agents/preflight.py`) — validates env vars, checks
  the CF key/secret pair is complete, confirms the local solutions folder
  exists, and does a live LeetCode auth ping. Read-only. A platform that
  fails preflight is dropped from the run (and logged) instead of crashing it.
- **Extraction agent** (`agents/extractor.py`) — all API traffic. Signs CF
  requests with your key/secret when set (codeforces.com/apiHelp scheme).
  Outputs structured payloads only; never touches disk state or git, so an
  API bug can't corrupt the repo. Per-platform errors are captured — one
  platform failing never discards the other's results.
- **Push agent** (`agents/pusher.py`) — the only module that writes to the
  repo: solution files (versioned `solution_<id>.<ext>`, never overwritten),
  `state.json`, `PENDING.md`, then commit + push (with one pull-rebase retry).
- **Orchestrator** (`orchestrator.py`) — sequences the three, owns the
  failure policy, snapshots git state before the push stage and rolls the
  tree back on unrecoverable failure so a half-finished run never leaves
  the repo dirty. Every run appends one line to `data/sync_log.md`.

## The two run paths

**LeetCode → cloud, fully automatic.** `.github/workflows/sync-leetcode.yml`
runs `orchestrator.py --platforms leetcode` hourly on GitHub Actions.
LeetCode's API returns real source code, so no local files are needed.

**Codeforces → your machine.** The CF API never returns source code, and a
cloud runner can't see your laptop's files — so `local_sync.sh` runs the
full orchestrator locally via cron/Task Scheduler, matching solutions from
`CF_LOCAL_SOLUTIONS_DIR`.

## Setup

1. Copy `.env.example` → `.env`, fill in your values (CF handle, optional
   CF API key/secret from codeforces.com/settings/api, local solutions dir,
   LeetCode cookies from browser DevTools).
2. `pip install -r requirements.txt`
3. Push this repo to GitHub (private recommended); add `LEETCODE_SESSION`
   and `LEETCODE_CSRF_TOKEN` as Actions secrets.
4. Add a cron entry on your machine:
   `*/30 * * * * /path/to/repo/local_sync.sh >> /tmp/streak-sync.log 2>&1`

## Self-correcting placeholders

If a CF solve has no matching local file at sync time, a clearly-labeled
`NEEDS_SOURCE_<id>.txt` is committed and the problem is listed in
`PENDING.md`. Once you save the real solution into `CF_LOCAL_SOLUTIONS_DIR`,
the next run replaces the placeholder automatically and clears the entry.

## Troubleshooting (check `data/sync_log.md` first)

| Log message | Meaning | Fix |
|---|---|---|
| `Preflight dropped leetcode` | cookie expired/missing | refresh cookies in `.env` + GitHub secrets |
| `Codeforces extraction FAILED` | CF API down or rate-limited | usually transient; check next run |
| `Push agent FAILED` / `rolled back` | git conflict or network | run `git pull --rebase` manually, rerun |
| No log lines for days | local cron not running | check your OS scheduler |

## Testing

`python3 tests/test_pipeline.py` — 22 checks covering preflight failures,
the placeholder→real-source upgrade loop, per-platform failure isolation,
and versioned-file behavior, all with mocked APIs (no network needed).

## Honest limits (unchanged, by nature)

LeetCode's GraphQL API is unofficial and can change without notice; its
cookie is a full account credential (keep this repo private); its "recent
submissions" window is capped, so long outages can lose old solves; and CF
will never hand over source code via API. The architecture makes these
visible and recoverable — it cannot make them disappear.
