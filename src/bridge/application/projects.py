# AI生成
"""ProjectService — manage project registration.

Phase 8: Application Layer service for projects.
"""
from __future__ import annotations

import json
from pathlib import Path


def list_projects(bridge_root: str | Path) -> list[dict]:
    """List all registered projects."""
    pf = Path(bridge_root) / "projects.json"
    if not pf.exists():
        return []
    data = json.loads(pf.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.values())
    return data


def get_project(bridge_root: str | Path, project_id: str) -> dict | None:
    """Get a single project by ID."""
    for p in list_projects(bridge_root):
        if p.get("projectId") == project_id or p.get("id") == project_id:
            return p
    return None


def register_project(bridge_root: str | Path, project: dict) -> dict:
    """Register a new project."""
    bridge_root = Path(bridge_root)
    pf = bridge_root / "projects.json"
    projects = list_projects(bridge_root)
    projects.append(project)
    pf.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
    return project


def unregister_project(bridge_root: str | Path, project_id: str) -> bool:
    """Remove a project by ID."""
    bridge_root = Path(bridge_root)
    pf = bridge_root / "projects.json"
    projects = list_projects(bridge_root)
    before = len(projects)
    projects = [p for p in projects if p.get("projectId") != project_id and p.get("id") != project_id]
    if len(projects) < before:
        pf.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    return False