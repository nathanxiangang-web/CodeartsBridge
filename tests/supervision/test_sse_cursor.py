# AI generated
# Tests for SSE seq cursor fix (EV-03).

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.core.events import Event, EventStore


@pytest.fixture
def api_server(tmp_path):
    from bridge.api.server import BridgeAPIServer
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    server = BridgeAPIServer(bridge_root=tmp_path, host="localhost", port=port)
    server.start()
    time.sleep(0.2)
    yield server
    server.stop()


def _connect_sse(server, timeout=5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((server.host, server.port))
    sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: localhost\r\n\r\n")
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
    header_end = data.index(b"\r\n\r\n") + 4
    leftover = data[header_end:]
    return sock, leftover


def _read_sse_messages(sock, leftover=b"", max_messages=1, timeout=5):
    sock.settimeout(timeout)
    messages = []
    buf = leftover
    deadline = time.time() + timeout
    while len(messages) < max_messages and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            break
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            raw_str = raw.decode("utf-8", errors="replace")
            if raw_str.startswith(":"):
                messages.append((True, None, None))
            elif raw_str.strip():
                event_type = None
                data_line = None
                for line in raw_str.split("\n"):
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data_line = line[6:]
                if data_line:
                    try:
                        data = json.loads(data_line)
                    except json.JSONDecodeError:
                        data = {}
                else:
                    data = {}
                messages.append((False, event_type, data))
    return messages


class TestSSESeqCursor:
    def test_sse_uses_seq_cursor(self):
        server_py = (
            Path(__file__).resolve().parent.parent.parent
            / "src" / "bridge" / "api" / "server.py"
        )
        source = server_py.read_text(encoding="utf-8")
        start = source.index("def _handle_event_stream")
        end = source.index("def create_handler")
        method_src = source[start:end]
        assert "recent_after" in method_src, "SSE handler must use recent_after()"
        assert "recent(100)" not in method_src, "SSE handler must not use recent(100)"
        assert "last_seq" in method_src, "SSE handler must track last_seq"
        assert "last_count" not in method_src, "SSE handler must not use last_count"

    def test_sse_works_past_100_events(self, tmp_path):
        store = EventStore(tmp_path / "events")
        for i in range(100):
            store.append(Event(
                event_id="", type="task.created",
                task_id=f"t{i}", payload={"n": i},
            ))

        from bridge.api.server import BridgeAPIServer

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            port = s.getsockname()[1]
        server = BridgeAPIServer(bridge_root=tmp_path, host="localhost", port=port)
        server.start()
        time.sleep(0.2)
        try:
            sock, leftover = _connect_sse(server, timeout=5)
            messages = _read_sse_messages(
                sock, leftover=leftover, max_messages=100, timeout=5
            )
            assert len(messages) == 100, f"Expected 100 initial events, got {len(messages)}"

            for i in range(50):
                store.append(Event(
                    event_id="", type="task.created",
                    task_id=f"t{100 + i}", payload={"n": 100 + i},
                ))

            new_messages = _read_sse_messages(
                sock, max_messages=50, timeout=5
            )
            assert len(new_messages) == 50, (
                f"Expected 50 new events past 100, got {len(new_messages)}"
            )
            sock.close()
        finally:
            server.stop()

    def test_sse_heartbeat_when_idle(self, tmp_path):
        from bridge.api.server import BridgeAPIHandler, BridgeAPIServer

        original = BridgeAPIHandler._SSE_HEARTBEAT_SECONDS
        BridgeAPIHandler._SSE_HEARTBEAT_SECONDS = 0.3
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", 0))
                port = s.getsockname()[1]
            server = BridgeAPIServer(bridge_root=tmp_path, host="localhost", port=port)
            server.start()
            time.sleep(0.2)
            try:
                sock, leftover = _connect_sse(server, timeout=5)
                messages = _read_sse_messages(
                    sock, leftover=leftover, max_messages=1, timeout=3
                )
                assert len(messages) >= 1, "No heartbeat comment received"
                assert messages[0][0] is True, (
                    f"Expected comment heartbeat, got event: {messages[0]}"
                )
                sock.close()
            finally:
                server.stop()
        finally:
            BridgeAPIHandler._SSE_HEARTBEAT_SECONDS = original
