# AI生成
"""Fake runner for E2E tests — simulates worker execution without real CodeArts.

Usage:
    from tests.e2e.fake_runner import FakeRunner
    runner = FakeRunner(behavior="success")
    runner.run(task_dir)  # writes deliverables to outbox
"""

from __future__ import annotations

import shutil
from pathlib import Path


class FakeRunner:
    """Simulates a worker run by writing deliverables to outbox.

    Behaviors:
        success: write RESULT.md, TESTS.md, DIFF.stat, exit 0
        failure: write nothing, exit 1
        assistance: write CHECKPOINT.md + ASSISTANCE_REQUEST.md, exit 0
        blocker: write BLOCKER.md, exit 1
    """

    def __init__(self, behavior: str = "success"):
        self.behavior = behavior
        self.exit_code = 0

    def run(self, task_dir: str | Path) -> int:
        task_dir = Path(task_dir)
        outbox = task_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)

        if self.behavior == "success":
            (outbox / "RESULT.md").write_text("# RESULT\n\nTask completed successfully.\n", encoding="utf-8")
            (outbox / "TESTS.md").write_text("# TESTS\n\nAll tests passed.\n", encoding="utf-8")
            (outbox / "DIFF.stat").write_text("2 files changed, 10 insertions(+), 2 deletions(-)\n", encoding="utf-8")
            (outbox / "DIFF.patch").write_text("--- a/example.py\n+++ b/example.py\n@@ -1,3 +1,5 @@\n+new code\n", encoding="utf-8")
            self.exit_code = 0
        elif self.behavior == "failure":
            self.exit_code = 1
        elif self.behavior == "assistance":
            (outbox / "CHECKPOINT.md").write_text("# CHECKPOINT\n\nPartial work saved.\n", encoding="utf-8")
            (outbox / "ASSISTANCE_REQUEST.md").write_text("# ASSISTANCE REQUEST\n\nNeed help with API design.\n", encoding="utf-8")
            self.exit_code = 0
        elif self.behavior == "blocker":
            (outbox / "BLOCKER.md").write_text("# BLOCKER\n\nArchitectural conflict found.\n", encoding="utf-8")
            self.exit_code = 1
        else:
            self.exit_code = 1

        return self.exit_code