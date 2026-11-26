"""Preflight agent: validates everything the pipeline needs BEFORE any
fetching or writing happens. Read-only -- never touches disk state or git.

Returns a PreflightReport; the orchestrator stops the run if .cf_ok is False.
"""

import os
from dataclasses import dataclass, field


@dataclass
class PreflightReport:
    cf_ok: bool = False
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


def run(platforms: set = None) -> PreflightReport:
    report = PreflightReport()
    check_codeforces(report)
    return report
