"""Persistent job store with atomic writes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .models import JobInfo, JobState, LogEvent


class JobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        d = self.jobs_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_job(self, job: JobInfo) -> None:
        d = self.job_dir(job.jobId)
        state_file = d / "state.json"
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, state_file)

    def load_job(self, job_id: str) -> JobInfo | None:
        state_file = self.jobs_dir / job_id / "state.json"
        if not state_file.exists():
            return None
        return JobInfo.from_dict(json.loads(state_file.read_text(encoding="utf-8")))

    def list_jobs(self) -> list[JobInfo]:
        jobs = []
        for d in self.jobs_dir.iterdir():
            if d.is_dir():
                job = self.load_job(d.name)
                if job:
                    jobs.append(job)
        return jobs

    def list_active_jobs(self) -> list[JobInfo]:
        return [
            j for j in self.list_jobs()
            if not JobState(j.state).is_terminal
        ]

    def append_event(self, job_id: str, event: LogEvent) -> None:
        d = self.job_dir(job_id)
        events_file = d / "events.jsonl"
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def read_events(self, job_id: str, cursor: int = 0) -> tuple[int, list[LogEvent]]:
        events_file = self.jobs_dir / job_id / "events.jsonl"
        if not events_file.exists():
            return (0, [])
        events = []
        line_num = 0
        with open(events_file, "r", encoding="utf-8") as f:
            for line in f:
                line_num += 1
                if line_num <= cursor:
                    continue
                try:
                    d = json.loads(line.strip())
                    events.append(LogEvent(**d))
                except (json.JSONDecodeError, TypeError):
                    pass
        return (line_num, events)

    def save_process_info(self, job_id: str, pid: int, pgid: int) -> None:
        d = self.job_dir(job_id)
        proc_file = d / "process.json"
        tmp = proc_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": pid, "pgid": pgid, "savedAt": time.time()}), encoding="utf-8")
        os.replace(tmp, proc_file)

    def load_process_info(self, job_id: str) -> dict[str, Any] | None:
        proc_file = self.jobs_dir / job_id / "process.json"
        if not proc_file.exists():
            return None
        return json.loads(proc_file.read_text(encoding="utf-8"))

    def write_stdout(self, job_id: str, data: str) -> None:
        d = self.job_dir(job_id)
        with open(d / "stdout.jsonl", "a", encoding="utf-8") as f:
            f.write(data)

    def write_stderr(self, job_id: str, data: str) -> None:
        d = self.job_dir(job_id)
        with open(d / "stderr.log", "a", encoding="utf-8") as f:
            f.write(data)