"""Regression guards for the Web UI thinking-echo contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = ROOT / "src" / "bridge" / "web" / "index.html"


def test_thinking_echo_uses_stable_event_cursor():
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "const seenEventIds={};" in html
    assert "const shownCount={};" not in html
    assert "e.id||" in html
    assert "loadHistory();" in html


def test_thinking_echo_uses_effective_runtime_worker():
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "wid=st.workerId||(st.meta&&st.meta.workerId)||'';" in html
    assert "let wid=task.workerId||(task.meta&&task.meta.workerId)||'';" in html


def test_p3_metrics_dashboard_survives_echo_fix():
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "async function loadMetrics()" in html
    assert "metrics:loadMetrics" in html
