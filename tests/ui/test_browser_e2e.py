"""Browser E2E tests for Control Center UI (UI-07).

Run with: python -m pytest tests/ui/ -v

Requires Bridge running on localhost:8080.
Playwright is a dev/test dependency, not part of production runtime.
"""
from __future__ import annotations

import pytest

try:
    from playwright.sync_api import sync_playwright, Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")

BASE_URL = "http://localhost:8080"


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_dashboard_loads(page: Page):
    page.goto(f"{BASE_URL}/#dashboard")
    page.wait_for_selector(".card", timeout=10000)
    content = page.text_content("#content")
    assert content is not None
    assert "Bridge" in content or "bridge" in content


def test_dashboard_shows_health(page: Page):
    page.goto(f"{BASE_URL}/#dashboard")
    page.wait_for_selector(".stat", timeout=10000)
    stats = page.query_selector_all(".stat")
    assert len(stats) >= 3


def test_tasks_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#tasks")
    page.wait_for_selector(".card", timeout=10000)
    content = page.text_content("#content")
    assert content is not None


def test_tasks_filter_exists(page: Page):
    page.goto(f"{BASE_URL}/#tasks")
    page.wait_for_selector("#tk-filter-state", timeout=10000)
    select = page.query_selector("#tk-filter-state")
    assert select is not None


def test_workers_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#workers")
    page.wait_for_selector(".card", timeout=10000)
    cards = page.query_selector_all(".worker-card")
    assert len(cards) >= 1


def test_dag_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#dag")
    page.wait_for_selector(".card", timeout=10000)


def test_review_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#review")
    page.wait_for_selector(".card", timeout=10000)


def test_thinking_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#thinking")
    page.wait_for_selector(".monitor-grid", timeout=10000)


def test_metrics_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#metrics")
    page.wait_for_selector(".card", timeout=10000)


def test_settings_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#settings")
    page.wait_for_selector(".card", timeout=10000)


def test_nav_all_pages(page: Page):
    pages = ["dashboard", "projects", "tasks", "workers", "review", "metrics", "thinking", "settings"]
    for p_name in pages:
        page.goto(f"{BASE_URL}/#{p_name}")
        page.wait_for_selector("#content", timeout=10000)
        content = page.text_content("#content")
        assert content is not None and len(content) > 0


def test_task_detail_invalid_id(page: Page):
    page.goto(f"{BASE_URL}/#task-detail/nonexistent-task-xyz")
    page.wait_for_selector(".card", timeout=10000)
    content = page.text_content("#content")
    assert content is not None


def test_projects_page_groups(page: Page):
    page.goto(f"{BASE_URL}/#projects")
    page.wait_for_selector(".card", timeout=10000)
    cards = page.query_selector_all(".card")
    assert len(cards) >= 1