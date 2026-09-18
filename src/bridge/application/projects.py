# AI生成
"""ProjectService — manage project registration without corrupting registry metadata.

Phase 8: Application Layer service for projects.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..atomic import atomic_write_json


def _load_registry(path: Path) -> tuple[dict | list, list[dict]]:
    """Load canonical or legacy project registry while preserving its container."""
    if not path.exists():
        data = {"schemaVersion": 1, "defaults": {}, "projects": []}
        return data, data["projects"]

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        projects = data.setdefault("projects", [])
        if not isinstance(projects, list):
            raise ValueError("projects registry field must be a list")
        return data, projects
    if isinstance(data, list):
        return data, data
    raise ValueError("projects.json must contain an object or list")


def list_projects(bridge_root: str | Path) -> list[dict]:
    """List all registered projects."""
    pf = Path(bridge_root) / "projects.json"
    if not pf.exists():
        return []
    _, projects = _load_registry(pf)
    return list(projects)


def get_project(bridge_root: str | Path, project_id: str) -> dict | None:
    """Get a single project by ID."""
    for p in list_projects(bridge_root):
        if p.get("projectId") == project_id or p.get("id") == project_id:
            return p
    return None


def register_project(bridge_root: str | Path, project: dict) -> dict:
    """Register a project while preserving schemaVersion/defaults."""
    bridge_root = Path(bridge_root)
    pf = bridge_root / "projects.json"
    data, projects = _load_registry(pf)

    project_id = project.get("id") or project.get("projectId")
    if project_id and any(
        p.get("id") == project_id or p.get("projectId") == project_id
        for p in projects
    ):
        raise ValueError(f"Project already registered: {project_id}")

    projects.append(project)
    atomic_write_json(pf, data)
    return project


def unregister_project(bridge_root: str | Path, project_id: str) -> bool:
    """Remove a project by ID while preserving registry metadata."""
    bridge_root = Path(bridge_root)
    pf = bridge_root / "projects.json"
    if not pf.exists():
        return False

    data, projects = _load_registry(pf)
    kept = [
        p for p in projects
        if p.get("projectId") != project_id and p.get("id") != project_id
    ]
    if len(kept) == len(projects):
        return False

    if isinstance(data, dict):
        data["projects"] = kept
    else:
        data[:] = kept
    atomic_write_json(pf, data)
    return True
