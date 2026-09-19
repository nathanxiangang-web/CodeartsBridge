"""CLI entry point for bridge-worker-agent."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import AgentConfig
from .server import AgentServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge Worker Runtime Agent")
    parser.add_argument("--listen", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=8765, help="Listen port")
    parser.add_argument("--root", default="~/.codex-glm-bridge/agent", help="Data root")
    parser.add_argument("--config", default=None, help="Config JSON path")
    parser.add_argument("--token", default=None, help="Auth token (or set BRIDGE_AGENT_TOKEN)")
    args = parser.parse_args(argv)

    config = AgentConfig()
    if args.config:
        config.load(args.config)

    token = args.token or os.environ.get("BRIDGE_AGENT_TOKEN", "")

    server = AgentServer(
        host=args.listen,
        port=args.port,
        data_root=args.root,
        config=config,
        token=token,
    )

    print(f"Bridge Worker Agent v{config.agent_version}")
    print(f"  Listen: {args.listen}:{args.port}")
    print(f"  Data root: {os.path.expanduser(args.root)}")
    print(f"  Token: {'***' + server.token[-4:] if server.token else '(auth off — trusted LAN)'}")
    print(f"  Capacity: {config.capacity}")

    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())