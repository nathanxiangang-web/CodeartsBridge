"""Browser E2E tests for the Local-First read-only monitor UI.

Run with: python -m pytest tests/ui/ -v
Requires Bridge running on localhost:8080 and Playwright installed.
"""
from __future__ import annotations

import pytest

try:
    from playwright.sync_api import sync_playwright, Page
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


def test_overview_loads(page: Page):
    page.goto(f"{BASE_URL}/#overview")
    page.wait_for_selector(".card", timeout=10000)
    content = page.text_content("#content") or ""
    assert "Bridge" in content
    assert "Workers" in content


def test_overview_shows_status_stats(page: Page):
    page.goto(f"{BASE_URL}/#overview")
    page.wait_for_selector(".stat", timeout=10000)
    assert len(page.query_selector_all(".stat")) >= 3


def test_tasks_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#tasks")
    page.wait_for_selector("#tasks-table", timeout=10000)


def test_tasks_filters_exist(page: Page):
    page.goto(f"{BASE_URL}/#tasks")
    page.wait_for_selector("#task-search", timeout=10000)
    assert page.query_selector("#task-state-sel") is not None


def test_thinking_page_loads(page: Page):
    page.goto(f"{BASE_URL}/#thinking")
    page.wait_for_selector(".monitor-grid", timeout=10000)


def test_only_monitor_navigation_is_exposed(page: Page):
    page.goto(f"{BASE_URL}/#overview")
    links = page.locator(".nav-link")
    labels = [links.nth(i).get_attribute("data-page") for i in range(links.count())]
    assert labels == ["overview", "tasks", "thinking"]


def test_task_detail_invalid_id_does_not_break_shell(page: Page):
    page.goto(f"{BASE_URL}/#task-detail/nonexistent-task-xyz")
    page.wait_for_selector("#content", timeout=10000)
    assert page.text_content("#content") is not None
