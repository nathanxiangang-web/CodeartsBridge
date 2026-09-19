"""Watchdog for soft/hard timeout monitoring."""
from __future__ import annotations

import time
from pathlib import Path

from .models import JobInfo, JobState, LogEvent
from .store import JobStore
from .runner import Runner


class Watchdog:
    def __init__(self, store: JobStore, runner: Runner):
        self.store = store
        self.runner = runner

    def check_timeouts(self, job: JobInfo) -> JobState | None:
        if JobState(job.state).is_terminal:
            return None

        elapsed = int(time.time() - job.startedAt) if job.startedAt > 0 else 0

        if elapsed >= job.hardTimeoutSeconds and job.hardTimeoutSeconds > 0:
            return self._handle_hard_timeout(job)

        if elapsed >= job.softTimeoutSeconds and not job.softLimitReached and job.softTimeoutSeconds > 0:
            return self._handle_soft_timeout(job)

        return None

    def _handle_soft_timeout(self, job: JobInfo) -> JobState:
        job.softLimitReached = True
        job.state = JobState.SOFT_LIMIT.value
        job.lastEventAt = time.time()
        self.store.save_job(job)

        self.store.append_event(job.jobId, LogEvent(
            id=f"evt-{int(time.time()*1000)}",
            time=time.time(),
            type="soft_timeout",
            text=f"Soft limit reached at {job.softTimeoutSeconds}s",
            status="soft_limit",
        ))

        self._save_salvage(job)

        return JobState.SOFT_LIMIT

    def _handle_hard_timeout(self, job: JobInfo) -> JobState:
        self.runner.terminate(job)

        has_deliverables = self._check_deliverables(job)
        has_diff = self._check_git_diff(job)

        if has_deliverables:
            new_state = JobState.COMPLETED_WITH_TIMEOUT
        elif has_diff:
            new_state = JobState.ASSISTANCE_REQUIRED
        else:
            new_state = JobState.TIMED_OUT

        job.state = new_state.value
        job.lastEventAt = time.time()
        job.exitCode = -1
        self.store.save_job(job)

        self.store.append_event(job.jobId, LogEvent(
            id=f"evt-{int(time.time()*1000)}",
            time=time.time(),
            type="hard_timeout",
            text=f"Hard timeout at {job.hardTimeoutSeconds}s -> {new_state.value}",
            status="timed_out",
        ))

        self._save_salvage(job)

        return new_state

    def _check_deliverables(self, job: JobInfo) -> bool:
        job_dir = self.store.job_dir(job.jobId)
        outbox = job_dir / "artifacts" / "outbox"
        if not outbox.exists():
            return False
        return any(outbox.iterdir())

    def _check_git_diff(self, job: JobInfo) -> bool:
        import subprocess
        try:
            r = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=job.projectRoot,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(r.stdout.strip())
        except Exception:
            return False

    def _save_salvage(self, job: JobInfo) -> None:
        import subprocess
        salvage_dir = self.store.job_dir(job.jobId) / "artifacts" / "runtime-salvage"
        salvage_dir.mkdir(parents=True, exist_ok=True)

        try:
            r = subprocess.run(
                ["git", "status"],
                cwd=job.projectRoot,
                capture_output=True,
                text=True,
                timeout=10,
            )
            (salvage_dir / "git-status.txt").write_text(r.stdout, encoding="utf-8")
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["git", "diff"],
                cwd=job.projectRoot,
                capture_output=True,
                text=True,
                timeout=10,
            )
            (salvage_dir / "DIFF.patch").write_text(r.stdout, encoding="utf-8")
            (salvage_dir / "DIFF.stat").write_text(
                subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=job.projectRoot,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout,
                encoding="utf-8",
            )
        except Exception:
            pass