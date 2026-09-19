"""Recovery for daemon restart — re-attach or converge orphan jobs."""
from __future__ import annotations

import time
from pathlib import Path

from .models import JobInfo, JobState, LogEvent
from .store import JobStore
from .runner import Runner


class Recovery:
    def __init__(self, store: JobStore, runner: Runner):
        self.store = store
        self.runner = runner

    def reconcile(self) -> list[JobInfo]:
        reconciled = []
        for job in self.store.list_jobs():
            if JobState(job.state).is_terminal:
                continue

            if self.runner.check_process(job):
                job.state = JobState.RUNNING.value
                job.lastEventAt = time.time()
                self.store.save_job(job)
                self.store.append_event(job.jobId, LogEvent(
                    id=f"evt-{int(time.time()*1000)}",
                    time=time.time(),
                    type="reconciled",
                    text="Re-attached to running process",
                    status="running",
                ))
                reconciled.append(job)
            else:
                exit_code = self.runner.get_exit_code(job)
                if exit_code is not None:
                    job.state = JobState.COMPLETED.value if exit_code == 0 else JobState.ASSISTANCE_REQUIRED.value
                else:
                    job.state = JobState.ASSISTANCE_REQUIRED.value

                job.exitCode = exit_code
                job.lastEventAt = time.time()
                self.store.save_job(job)
                self.store.append_event(job.jobId, LogEvent(
                    id=f"evt-{int(time.time()*1000)}",
                    time=time.time(),
                    type="reconciled",
                    text=f"Process gone, converged to {job.state}",
                    status="converged",
                ))
                reconciled.append(job)

        return reconciled