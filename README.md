# cf-streak-sync (Codeforces agent architecture, personal use)

Turns your Accepted Codeforces submissions into git commits automatically.
Built as three single-responsibility agents coordinated by an orchestrator,
so any failure is detected, isolated, and recovered from without corrupting
the repository.

## Architecture

```
                    ┌──────────────────┐
   cron / Task      │  orchestrator.py │   the ONLY entry point
   Scheduler    ─▶  └───────┬──────────┘
                            │
               ┌────────────┼─────────────────┐
               ▼            ▼                 ▼
       ┌──────────────┐ ┌─────────────┐ ┌────────────┐
       │ preflight.py │ │ extractor.py│ │ pusher.py  │
       │ env + auth   │ │ CF API      │ │ files, state,│
       │ checks only  │ │ fetch only  │ │ git commit  │
       └──────────────┘ └─────────────┘ └────────────┘
```

- **Preflight agent** (`agents/preflight.py`) — validates env vars, checks
  the CF key/secret pair is complete, and confirms the local solutions folder
  exists. Read-only.
- **Extraction agent** (`agents/extractor.py`) — all API traffic. Signs CF
  requests with your key/secret when set (codeforces.com/apiHelp scheme).
  Outputs structured payloads only; never touches disk state or git.
- **Push agent** (`agents/pusher.py`) — the only module that writes to the
  repo: solution files (versioned `solution_<id>.<ext>`, never overwritten),
  `state.json`, `PENDING.md`, then commit + push (with one pull-rebase retry).
- **Orchestrator** (`orchestrator.py`) — sequences the three, owns the
  failure policy, snapshots git state before the push stage and rolls the
  tree back on unrecoverable failure so a half-finished run never leaves
  the repo dirty. Appends to `data/sync_log.md`.

## Setup

1. Copy `.env.example` → `.env`, fill in your values (CF handle, optional
   CF API key/secret from codeforces.com/settings/api, local solutions dir).
2. `pip install -r requirements.txt`
3. Push this repo to GitHub (private recommended).
4. Automate local runs:
   - **Windows**: Use Task Scheduler to run `local_sync.bat` every 30 minutes.
   - **Linux / macOS**: Add a cron entry:
     `*/30 * * * * /path/to/repo/local_sync.sh >> /tmp/streak-sync.log 2>&1`

## Self-correcting placeholders

If a CF solve has no matching local file at sync time, a clearly-labeled
`NEEDS_SOURCE_<id>.txt` is committed and the problem is listed in
`PENDING.md`. Once you save the real solution into `CF_LOCAL_SOLUTIONS_DIR`,
the next run replaces the placeholder automatically and clears the entry.

## Troubleshooting (check `data/sync_log.md` first)

| Log message | Meaning | Fix |
|---|---|---|
| `Preflight dropped / failed` | missing handle or mismatched API key | verify values in `.env` |
| `Codeforces extraction FAILED` | CF API down or rate-limited | usually transient; check next run |
| `Push agent FAILED` / `rolled back` | git conflict or network | run `git pull --rebase` manually, rerun |
| No log lines for days | scheduler not running | check Windows Task Scheduler or cron |

## Testing

`python tests/test_pipeline.py` — runs end-to-end tests covering preflight checks,
the placeholder→real-source upgrade loop, API failure isolation, Windows title sanitization,
and versioned-file behavior, all in an isolated sandbox with mocked APIs.
