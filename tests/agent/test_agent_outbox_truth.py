"""Tests for agent runtime truth: project-local outbox + archive lifecycle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.agent.runner import _ensure_git_exclude, archive_project_outbox


class TestProjectLocalOutbox:
    """CODEARTS_OUTBOX must be inside projectRoot so CodeArts write/edit works."""

    def test_outbox_is_inside_project_root(self, tmp_path):
        """The outbox path must resolve inside projectRoot."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        job_id = "job-test-001"

        project_outbox = project_root / ".codeartsbridge" / "outbox" / job_id
        project_outbox.mkdir(parents=True)

        assert str(project_outbox).startswith(str(project_root))
        assert project_outbox.is_relative_to(project_root)

    def test_git_exclude_added(self, tmp_path):
        """_ensure_git_exclude adds .codeartsbridge/ to .git/info/exclude."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        (project_root / ".git" / "info").mkdir()

        _ensure_git_exclude(project_root)

        exclude = (project_root / ".git" / "info" / "exclude").read_text()
        assert ".codeartsbridge/" in exclude

    def test_git_exclude_idempotent(self, tmp_path):
        """Running _ensure_git_exclude twice does not duplicate the entry."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        (project_root / ".git" / "info").mkdir()

        _ensure_git_exclude(project_root)
        _ensure_git_exclude(project_root)

        exclude = (project_root / ".git" / "info" / "exclude").read_text()
        assert exclude.count(".codeartsbridge/") == 1

    def test_git_exclude_no_git_dir_no_error(self, tmp_path):
        """Non-git project does not raise."""
        project_root = tmp_path / "nogit"
        project_root.mkdir()
        _ensure_git_exclude(project_root)

    def test_archive_copies_files_to_agent_outbox(self, tmp_path):
        """archive_project_outbox copies all files from project-local to agent."""
        project_root = tmp_path / "project"
        job_id = "job-001"
        project_outbox = project_root / ".codeartsbridge" / "outbox" / job_id
        project_outbox.mkdir(parents=True)
        (project_outbox / "RESULT.md").write_text("result content")
        (project_outbox / "TESTS.md").write_text("tests content")

        agent_outbox = tmp_path / "agent" / "artifacts" / "outbox"
        agent_outbox.mkdir(parents=True)

        count = archive_project_outbox(project_root, job_id, agent_outbox)

        assert count == 2
        assert (agent_outbox / "RESULT.md").read_text() == "result content"
        assert (agent_outbox / "TESTS.md").read_text() == "tests content"

    def test_archive_cleanup_after_copy(self, tmp_path):
        """Project-local outbox is removed after successful archive."""
        project_root = tmp_path / "project"
        job_id = "job-001"
        project_outbox = project_root / ".codeartsbridge" / "outbox" / job_id
        project_outbox.mkdir(parents=True)
        (project_outbox / "RESULT.md").write_text("content")

        agent_outbox = tmp_path / "agent_outbox"
        agent_outbox.mkdir()

        archive_project_outbox(project_root, job_id, agent_outbox)

        assert not project_outbox.exists()

    def test_archive_no_project_outbox_returns_zero(self, tmp_path):
        """If project-local outbox doesn't exist, return 0."""
        agent_outbox = tmp_path / "agent_outbox"
        agent_outbox.mkdir()
        count = archive_project_outbox(tmp_path, "nonexistent", agent_outbox)
        assert count == 0

    def test_archive_preserves_file_metadata(self, tmp_path):
        """shutil.copy2 preserves mtime."""
        project_root = tmp_path / "project"
        job_id = "job-001"
        project_outbox = project_root / ".codeartsbridge" / "outbox" / job_id
        project_outbox.mkdir(parents=True)
        src = project_outbox / "RESULT.md"
        src.write_text("content")
        src_mtime = src.stat().st_mtime

        agent_outbox = tmp_path / "agent_outbox"
        agent_outbox.mkdir()

        archive_project_outbox(project_root, job_id, agent_outbox)

        dest = agent_outbox / "RESULT.md"
        assert dest.stat().st_mtime == src_mtime