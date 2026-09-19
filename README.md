# CodeartsBridge

Lightweight task control plane for multi-AI software development. Dispatch coding tasks to Worker nodes running CodeArts CLI, stream Agent thinking in real time, review and integrate results.

> **Quick mental model**: A Python service runs on the bridge host. You configure `projects.json` (project paths) and `workers.json` (Worker Agent endpoints), then `bridge serve` starts the HTTP API + read-only Web UI. Tasks are created via CLI and dispatched manually with `bridge dispatch`. Each Worker runs a `bridge-worker-agent` daemon that executes CodeArts CLI and streams events back. The UI is read-only monitoring only.

## Architecture

```
┌──────────────────────────────────────────────┐
│          Read-only Web UI (:8080)             │
│   overview / tasks / thinking (+ task-detail)  │
└──────────────────┬───────────────────────────┘
                   │ HTTP API + SSE
┌──────────────────┴───────────────────────────┐
│                 Bridge Server                 │
│  dispatch / state / EventStore / AgentTransport│
└──┬──────────┬──────────┬──────────┬─────────┘
   │ Agent    │ Agent    │ Agent    │ Agent
┌──┴──┐    ┌──┴──┐    ┌──┴──┐    ┌──┴──┐
│w01  │    │w02  │    │w03  │    │w04  │
│:8765│    │:8765│    │:8765│    │:8765│
│codearts│ │codearts│ │codearts│ │codearts│
└─────┘    └─────┘    └─────┘    └─────┘
```

**Core components**:

| Component | Description |
|-----------|-------------|
| **Bridge Server** | HTTP API + read-only Web UI on the bridge host, task dispatch and state management |
| **Agent Server** | Worker daemon (:8765), receives jobs, runs CodeArts CLI, streams events back |
| **EventStore** | Event store with fcntl.flock concurrency safety and 10MB auto-rotation |
| **Web UI** | 3 read-only pages (overview / tasks / thinking) plus task-detail, SSE real-time push |

**Workflow**:
1. `bridge serve` starts HTTP API + Web UI (+ MCP on by default) on the bridge host
2. Each Worker runs `bridge-worker-agent` (daemon on :8765)
3. `bridge create` creates a task (Markdown file describing the work)
4. `bridge dispatch` assigns the task to an enabled Worker and sends it over agent transport
5. Worker Agent invokes CodeArts CLI to execute the task
6. Events (reasoning, tool_use, step) stream back to Bridge in real time
7. Web UI renders the thinking stream live via SSE
8. `bridge integrate` cherry-picks DONE tasks into the main branch

## Quick start

### Install

```bash
git clone https://github.com/nathanxiangang-web/CodeartsBridge.git
cd CodeartsBridge
pip install -e .
```

### Start services

```bash
# 1. Bridge host: start HTTP API + Web UI
bridge serve --host 0.0.0.0 --port 8080

# 2. Each Worker: start Agent Server (trusted LAN, no token needed)
bridge-worker-agent --listen 0.0.0.0 --port 8765

# 3. Open the read-only UI
open http://<bridge-host>:8080
```

### Dispatch a task

```bash
# Create a task from a Markdown instruction file
bridge create -p bridge -t my-task -f task.md

# Dispatch it to an enabled Worker (manual — serve does not auto-dispatch)
bridge dispatch

# Watch status
bridge status
```

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| Python >= 3.10 | On bridge host and all Worker nodes |
| CodeArts CLI | Installed and AK/SK configured on each Worker |
| Network reachability | Bridge host can reach each Worker Agent endpoint |

**CodeArts CLI setup** (on each Worker):
```bash
codearts config set-access-key YOUR_AK
codearts config set-secret-key YOUR_SK
```

## Configuration

Two JSON files in the project root (or `--config-dir`).

### projects.json — projects

Minimal form:

```json
{
  "projects": [
    {"id": "bridge", "projectRoot": "/home/nathan/bridge-python"}
  ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Project unique identifier |
| `projectRoot` | Project repository path on the Worker |

### workers.json — Worker endpoints

Minimal form (4 Workers on 178.50/51/52/53):

```json
{
  "workers": [
    {"id": "w01", "endpoint": "http://192.168.178.52:8765", "enabled": true},
    {"id": "w02", "endpoint": "http://192.168.178.50:8765", "enabled": true},
    {"id": "w03", "endpoint": "http://192.168.178.53:8765", "enabled": true},
    {"id": "w04", "endpoint": "http://192.168.178.51:8765", "enabled": true}
  ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Worker unique identifier |
| `endpoint` | Agent Server HTTP endpoint |
| `enabled` | Whether this Worker receives dispatches |

### Authentication

No token auth. The Agent Server runs on a trusted LAN. When no token is configured, the Agent prints `auth off — trusted LAN` and accepts all requests. Token auth is available via `--token` or `BRIDGE_AGENT_TOKEN` if needed, but the normal deployment does not use it.

## Transport

Agent transport only. The Bridge talks to each Worker over HTTP (`http://<worker-ip>:8765`). There is no SSH, local, or remote-worktree transport in normal use.

## CLI commands

| Command | Description |
|---------|-------------|
| `bridge serve` | Start HTTP API + Web UI (+ MCP on by default) |
| `bridge create -p <project> -t <task-id> -f <file>` | Create a task |
| `bridge dispatch` | Dispatch ready tasks to enabled Workers (manual) |
| `bridge status` | Show all task states |
| `bridge review-pass -t <task-id>` | Mark a task review-passed |
| `bridge review-fix -t <task-id> --task-file <file>` | Return a task for fix |
| `bridge integrate` | Cherry-pick DONE tasks into main |
| `bridge cancel -t <task-id>` | Cancel a task |
| `bridge projects` | List registered projects |
| `bridge workers` | List registered Workers |
| `bridge doctor` | Environment and config health check |

`bridge serve` does **not** auto-dispatch. You must run `bridge dispatch` (or an external loop) to move tasks from READY to a Worker.

## Web UI

Read-only monitoring. Open `http://<bridge-host>:8080` in a browser.

| Page | URL hash | Description |
|------|----------|-------------|
| Overview | `#overview` | Worker status, task counts |
| Tasks | `#tasks` | Task list with status filters; click for task-detail |
| Thinking | `#thinking` | Real-time Agent thinking stream (SSE) |

The UI is read-only — it does not create, cancel, retry, or review tasks. Control happens via CLI or the Bridge internal loop.

**Tech stack**: browser-native ES Modules (no build tool, no framework), single `app.css`, SSE real-time events with polling fallback.

## HTTP API

### Bridge Server API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/tasks` | List all tasks |
| GET | `/api/tasks/<id>` | Task detail |
| GET | `/api/tasks/<id>/log` | Task log (event stream) |
| POST | `/api/tasks/<id>/cancel` | Cancel a task |
| GET | `/api/workers` | List Workers |
| GET | `/api/projects` | List projects |
| GET | `/api/events` | SSE event stream (real-time push) |

### Agent Server API (Worker :8765)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/health` | Agent health |
| POST | `/v1/jobs` | Create and start a job |
| GET | `/v1/jobs/<id>` | Job status |
| GET | `/v1/jobs/<id>/events?cursor=N` | Event stream (incremental cursor) |
| POST | `/v1/jobs/<id>/cancel` | Cancel a job |
| GET | `/v1/jobs/<id>/artifacts` | List artifacts |
| GET | `/v1/jobs/<id>/files/<category>/<name>` | Download a file |

## Project structure

```
src/bridge/
├── cli.py                    # CLI entry
├── dispatch.py               # Task dispatch
├── state.py                  # Task state machine
├── worker.py                 # Worker execution
├── integration.py            # Cherry-pick integration
├── config.py                 # Config loading
├── agent/                    # Worker Agent (daemon)
│   ├── cli.py                # Agent CLI entry
│   ├── server.py             # HTTP Server (:8765)
│   ├── runner.py             # CodeArts runner
│   ├── watchdog.py           # Process watchdog
│   ├── recovery.py           # Inflight recovery
│   └── store.py              # Job store
├── transport/
│   └── agent.py              # Agent transport (HTTP API)
├── core/
│   ├── events.py             # EventStore (flock + rotation)
│   └── state.py              # State machine
├── api/server.py             # HTTP API server
└── web/                      # Read-only Web UI
    ├── index.html
    ├── styles/app.css
    └── js/
        ├── api.js
        ├── events.js
        ├── app.js
        └── pages/
            ├── overview.js
            ├── tasks.js
            ├── task-detail.js
            └── thinking.js
```

## Deployment

### systemd — Bridge Server (bridge host)

```bash
sudo cat > /etc/systemd/system/bridge.service << 'EOF'
[Unit]
Description=CodeartsBridge Server
After=network.target

[Service]
Type=simple
User=nathan
WorkingDirectory=/home/nathan/bridge-python
Environment=PYTHONPATH=/home/nathan/bridge-python/src
ExecStart=/usr/bin/python3 -m bridge.cli serve --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now bridge
```

### systemd — Worker Agent (each Worker)

```bash
sudo cp deploy/bridge-worker-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bridge-worker-agent
```

### Worker Agent install script

```bash
./deploy/install-worker-agent.sh
```

This creates the `~/.codex-glm-bridge/agent` data directory and installs the systemd service. No token is generated — the Agent runs with `auth off` on a trusted LAN.

## Development

```bash
pip install -e ".[dev]"
pytest
export PYTHONPATH=src     # if not pip install
```

## Closeout docs

- `docs/ai-closeout/` — runtime truth audit, closeout roadmap, delete-or-wire matrix, AI execution rules, real acceptance scenarios. Read these first when working on the bridge.

## License

MIT
