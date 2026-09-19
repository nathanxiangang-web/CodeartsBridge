"""Regression guards for Web UI configuration semantics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "src" / "bridge" / "web"


def _html() -> str:
    """Return merged content of all frontend files in index.html load order."""
    import re
    parts = []
    index = WEB_DIR / "index.html"
    if not index.exists():
        return ""
    html = index.read_text(encoding="utf-8")
    parts.append(html)
    for m in re.finditer(r'<link[^>]+href="([^"]+)"', html):
        path = m.group(1).lstrip("/")
        f = WEB_DIR / path
        if f.exists() and f.suffix == ".css":
            parts.append(f.read_text(encoding="utf-8"))
    for m in re.finditer(r'<script\s+src="([^"]+)"', html):
        path = m.group(1).lstrip("/")
        f = WEB_DIR / path
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


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


def test_task_form_selects_registered_projects_and_workers():
    html = _html()
    start = html.index("async function loadTasks(){")
    end = html.index("async function cancelTask(id){", start)
    tasks = html[start:end]

    assert "Promise.all([api('/tasks'),api('/projects'),api('/workers')])" in tasks
    assert '<select id="tk-project">' in tasks
    assert '<select id="tk-worker">' in tasks
    assert "workers.filter(w=>w.enabled!==false)" in tasks
    assert "body.worker_id=w" in tasks
    assert "if(result.error){alert(result.error);return}" in tasks


def test_review_queue_only_contains_review_required_and_has_actions():
    html = _html()
    start = html.index("async function loadReview(){")
    end = html.index("async function viewOutboxFile", start)
    review = html[start:end]

    assert "toUpperCase()==='REVIEW_REQUIRED'" in review
    assert "mapState(task.state||'')==='done'" not in review
    assert "reviewPass(" in review
    assert "reviewFix(" in review
    assert "/review/pass" in review
    assert "/review/fix" in review
    assert "comment" in review


def test_dashboard_does_not_call_enabled_workers_online():
    html = _html()
    start = html.index("async function loadDashboard(){")
    end = html.index("async function loadProjects(){", start)
    dashboard = html[start:end]

    assert "w.enabled!==false" in dashboard
    assert "w.enabled===false" in dashboard
    assert "t('enabled')" in dashboard
    assert "t('disabled')" in dashboard
    assert "t('online')" not in dashboard
    assert "t('offline')" not in dashboard
    assert "h.daemon" in dashboard
    assert "h.pipeline" in dashboard


def test_settings_are_readonly_runtime_truth_not_fake_controls():
    html = _html()
    start = html.index("async function loadSettings(){")
    end = html.index("const pages=", start)
    settings = html[start:end]

    assert "h.daemon" in settings
    assert "h.pipeline" in settings
    assert "settings_readonly" in settings
    assert "cfg-max-workers" not in settings
    assert "cfg-soft-timeout" not in settings
    assert "cfg-hard-timeout" not in settings
    assert "saved_demo" not in settings
    assert "onclick=" not in settings



def test_thinking_echo_uses_dynamic_enabled_worker_slots():
    html = _html()
    start = html.index("async function loadThinking(){")
    end = html.index("async function loadMetrics(){", start)
    thinking = html[start:end]

    assert ".filter(w=>w.enabled!==false)" in thinking
    assert "localeCompare(String(b.id||''))" in thinking
    assert ".slice(0,4)" not in thinking
    assert "includes('178.50')" not in thinking
    assert "const slotCount=document.querySelectorAll('.monitor-window').length;" in thinking
    assert "i<4" not in thinking
    assert "i<slotCount" in thinking


def test_thinking_echo_preserves_reliability_guards_with_dynamic_slots():
    html = _html()
    start = html.index("function initThinking(){")
    end = html.index("async function loadMetrics(){", start)
    thinking = html[start:end]

    assert "const seenEventIds={};" in thinking
    assert "const activityRank={RUNNING:3,STARTING:2,QUEUED:1};" in thinking
    assert "while(seen.size>300)" in thinking
    assert "loadHistory();" in thinking
    assert "if(slotData[i]){" in thinking
    assert "logEl.innerHTML='';" in thinking
    assert "document.querySelectorAll('.monitor-log').forEach" in thinking
