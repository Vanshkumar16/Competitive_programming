#!/usr/bin/env bash
# Cron / Task Scheduler entry point for your own machine (handles BOTH
# platforms -- this is where Codeforces gets real source code from your
# local solutions folder).
#
# Example crontab (every 30 min):
#   */30 * * * * /path/to/repo/local_sync.sh >> /tmp/streak-sync.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
python3 orchestrator.py
