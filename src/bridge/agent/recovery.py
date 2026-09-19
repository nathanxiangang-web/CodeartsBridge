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
                # After an Agent restart the child process may still exist, but
                # its stdout/stderr pipe handles belonged to the old Agent
                # process and cannot be re-attached. Pretending this is RUNNING
                # creates exactly the "busy CodeArts + zero UI echo" failure.
                self.runner.terminate(job, grace_seconds=2)
                self.runner.release(job.jobId)
                job.state = JobState.ASSISTANCE_REQUIRED.value
                job.exitCode = -1
                job.lastEventAt = time.time()
                self.store.save_job(job)
                self.store.append_event(job.jobId, LogEvent(
                    id=f"evt-{time.time_ns()}",
                    time=time.time(),
                    type="reconciled",
                    text=(
                        "Agent restarted while CodeArts was still alive; "
                        "terminated orphan because its output stream cannot be re-attached"
                    ),
                    status="converged",
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
                    id=f"evt-{time.time_ns()}",
                    time=time.time(),
                    type="reconciled",
                    text=f"Process gone, converged to {job.state}",
                    status="converged",
                ))
                reconciled.append(job)

        return reconciled