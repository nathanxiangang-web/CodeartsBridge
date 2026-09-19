# AI生成
"""Tests for static file serving (UI-00-01)."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def api_server(tmp_path):
    from bridge.api.server import BridgeAPIServer
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
    server.start()
    time.sleep(0.2)
    yield server
    server.stop()


def _get_raw(server, path):
    url = server.url(path)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


class TestStaticServe:
    def test_root_returns_index_html(self, api_server):
        code, ctype, body = _get_raw(api_server, "/")
        assert code == 200
        assert "text/html" in ctype

    def test_spa_fallback_returns_index(self, api_server):
        code, ctype, body = _get_raw(api_server, "/dashboard")
        assert code == 200
        assert "text/html" in ctype

    def test_spa_fallback_deep_route(self, api_server):
        code, ctype, body = _get_raw(api_server, "/tasks/some-task-id")
        assert code == 200
        assert "text/html" in ctype

    def test_js_file_served(self, api_server):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        js_dir = web_dir / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        test_js = js_dir / "test_app.js"
        test_js.write_text("console.log('test');", encoding="utf-8")
        try:
            code, ctype, body = _get_raw(api_server, "/js/test_app.js")
            assert code == 200
            assert "javascript" in ctype
            assert b"console.log" in body
        finally:
            test_js.unlink(missing_ok=True)

    def test_css_file_served(self, api_server):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        styles_dir = web_dir / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        test_css = styles_dir / "test_tokens.css"
        test_css.write_text(":root { --color: #fff; }", encoding="utf-8")
        try:
            code, ctype, body = _get_raw(api_server, "/styles/test_tokens.css")
            assert code == 200
            assert "text/css" in ctype
            assert b"--color" in body
        finally:
            test_css.unlink(missing_ok=True)

    def test_css_alias_maps_to_styles(self, api_server):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        styles_dir = web_dir / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        test_css = styles_dir / "base.css"
        test_css.write_text("body { margin: 0; }", encoding="utf-8")
        try:
            code, ctype, body = _get_raw(api_server, "/css/base.css")
            assert code == 200
            assert "text/css" in ctype
            assert b"margin" in body
        finally:
            test_css.unlink(missing_ok=True)

    def test_nonexistent_js_returns_404(self, api_server):
        code, ctype, body = _get_raw(api_server, "/js/nonexistent.js")
        assert code == 404

    def test_path_traversal_blocked(self, api_server):
        code, ctype, body = _get_raw(api_server, "/js/../../etc/passwd")
        assert code in (403, 404)

    def test_path_traversal_explicit_dotdot(self, api_server):
        code, ctype, body = _get_raw(api_server, "/js/../web/index.html")
        assert code in (403, 404)

    def test_hashed_file_gets_long_cache(self, api_server):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        js_dir = web_dir / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        hashed = js_dir / "app.a1b2c3d4.js"
        hashed.write_text("console.log('hashed');", encoding="utf-8")
        try:
            url = api_server.url("/js/app.a1b2c3d4.js")
            with urllib.request.urlopen(url, timeout=5) as resp:
                cache = resp.headers.get("Cache-Control", "")
            assert "max-age=31536000" in cache
        finally:
            hashed.unlink(missing_ok=True)

    def test_unhashed_file_gets_no_cache(self, api_server):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        js_dir = web_dir / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        plain = js_dir / "test_unhashed_plain.js"
        plain.write_text("console.log('plain');", encoding="utf-8")
        try:
            url = api_server.url("/js/test_unhashed_plain.js")
            with urllib.request.urlopen(url, timeout=5) as resp:
                cache = resp.headers.get("Cache-Control", "")
            assert "no-cache" in cache
        finally:
            plain.unlink(missing_ok=True)