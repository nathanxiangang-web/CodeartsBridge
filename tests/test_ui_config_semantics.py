"""Regression guards for Web UI configuration semantics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "bridge" / "web" / "index.html"


def _html() -> str:
    return WEB.read_text(encoding="utf-8")


def test_projects_ui_uses_runtime_project_config_fields():
    html = _html()
    assert 'id="pj-root"' in html
    assert 'id="pj-transport"' in html
    assert 'id="pj-host"' in html
    assert 'id="pj-remote-root"' in html
    assert 'id="pj-workspace-root"' in html
    assert 'id="pj-cli"' in html
    assert "projectRoot," in html
    assert "sshHost:" in html
    assert "remoteBridgeRoot:" in html
    assert "remoteWorkspaceRoot:" in html


def test_task_role_options_match_valid_roles():
    html = _html()
    start = html.index('<select id="tk-role">')
    end = html.index('</select>', start)
    select = html[start:end]

    assert 'value="architect"' in select
    assert 'value="implement"' in select
    assert 'value="review"' in select
    assert 'value="test"' in select
    assert 'value="integration"' not in select
    assert 'value="ops"' not in select


def test_workers_ui_uses_worker_registry_fields():
    html = _html()
    start = html.index("async function loadWorkers(){")
    end = html.index("async function loadReview(){", start)
    workers = html[start:end]

    assert "w.capabilities" in workers
    assert "w.concurrencyLimit" in workers
    assert "w.transport" in workers
    assert "w.cliPath" in workers
    assert "w.roles" not in workers
    assert "w.skills" not in workers
    assert "w.agent_type" not in workers


def test_project_form_no_longer_posts_repo_branch_as_runtime_config():
    html = _html()
    start = html.index("async function addProject(){")
    end = html.index("async function loadTasks(){", start)
    add_project = html[start:end]

    assert "projectRoot" in add_project
    assert "transport:" in add_project
    assert "runMode:" in add_project
    assert "repo_url" not in add_project
    assert "branch:" not in add_project
