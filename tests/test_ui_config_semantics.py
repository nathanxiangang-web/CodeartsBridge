"""Regression guards for the Local-First read-only Web UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "src" / "bridge" / "web"


def _read(rel: str) -> str:
    return (WEB_DIR / rel).read_text(encoding="utf-8")


def test_navigation_is_monitor_only():
    html = _read("index.html")
    assert 'data-page="overview"' in html
    assert 'data-page="tasks"' in html
    assert 'data-page="thinking"' in html
    for removed in ("projects", "workers", "review", "metrics", "settings", "dag"):
        assert f'data-page="{removed}"' not in html


def test_api_client_allows_delete_only():
    source = _read("js/api.js")
    assert "fetch('/api/' + path)" in source
    assert "POST" not in source
    assert "PUT" not in source
    assert "DELETE" in source
    assert "deleteTask" in source


def test_tasks_page_is_observation_only():
    source = _read("js/pages/tasks.js")
    assert "task-search" in source
    assert "task-state-sel" in source
    assert "#task-detail/" in source
    assert "createTask" not in source
    assert "cancelTask" not in source
    assert "worker_id" not in source


def test_tasks_clear_is_local_display_only():
    source = _read("js/pages/tasks.js")
    api = _read("js/api.js")
    assert "一键删除已结束" in source
    assert "清除已结束" not in source
    assert "恢复隐藏" not in source
    assert "TASK_HIDDEN_KEY" not in source
    assert "TERMINAL_TASK_STATES" in source
    assert "deleteTask" in source
    assert "_batchDeleteFinished" in source
    assert "API.cancel" not in source
    assert "POST" not in api


def test_task_detail_has_no_control_actions():
    source = _read("js/pages/task-detail.js")
    assert "最近事件" in source
    assert "Worker" in source
    assert "项目" in source
    for action in ("reviewPass", "reviewFix", "retryTask", "reassign", "cancelTask"):
        assert action not in source


def test_overview_reads_current_tasks_shape():
    source = _read("js/pages/overview.js")
    assert "w.currentTasks" in source
    assert "currentTasks" in source
    assert "BUSY" in source
    assert "OFFLINE" in source
    assert "IDLE" in source


def test_thinking_echo_uses_dynamic_enabled_worker_slots():
    source = _read("js/pages/thinking.js")
    assert ".filter(function(w){return w.enabled!==false;})" in source
    assert "localeCompare(String(b.id||''))" in source
    assert ".slice(0,4)" not in source
    assert "var slotCount=document.querySelectorAll('.monitor-window').length;" in source
    assert "i<slotCount" in source


def test_thinking_echo_preserves_reliability_guards():
    source = _read("js/pages/thinking.js")
    assert "var seenEventIds={};" in source
    assert "var activityRank={RUNNING:3,STARTING:2,QUEUED:1};" in source
    assert "while(seen.size>300)" in source
    assert "等待 Worker 事件..." in source
    assert "回显读取失败：" in source
    assert "thinkingPoll=setTimeout(schedulePoll,2000)" in source


def test_thinking_monitor_is_viewport_bounded():
    source = _read("js/pages/thinking.js")
    css = _read("styles/app.css")
    assert "var MAX_MONITOR_LINES=120;" in source
    assert "while(logEl.childElementCount>MAX_MONITOR_LINES)" in source
    assert "grid-auto-rows:minmax(0,1fr)" in css
    assert "height:calc(100dvh - 88px)" in css
    assert ".monitor-grid" in css and "overflow:hidden" in css
    assert ".monitor-log" in css and "overflow-y:auto" in css


def test_sse_points_at_real_bridge_endpoint():
    source = _read("js/events.js")
    assert "EventSource('/api/events')" in source
    assert "/api/events/stream" not in source
    assert "addEventListener" in source
