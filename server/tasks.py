"""Task loader for the local DreamHouse server.

The server supports two task sources:

1. `DREAMHOUSE_TASKS_PACK=/path/to/tasks.dhpack`
   A packed SQLite database built by `scripts/build_task_pack.py`. This is the
   recommended distribution format because users do not receive a browsable
   folder tree of all task images.

2. `DREAMHOUSE_TASKS_DIR=/path/to/houses`
   A developer-friendly folder tree. Defaults to `<repo>/houses`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_DIR = REPO_ROOT / "houses"

# Minimal style metadata by prefix. Add more as your dataset grows.
_STYLE_BY_PREFIX = {
    "AF": "American Farmhouse",
    "BN": "Barn",
    "CR": "Craftsman",
    "COL": "Colonial",
    "CY": "Courtyard",
    "FH": "Farmhouse",
    "RN": "Ranch",
    "SB": "Saltbox",
    "SH": "Shed Roof",
    "SL": "Split Level",
    "TH": "Townhouse",
    "ZP": "Z-Plan",
}

# Five canonical view names the API exposes.
VIEWS = {
    "front": "_skin_front.png",
    "back": "_skin_back.png",
    "left": "_skin_left.png",
    "right": "_skin_right.png",
    "top": "_skin_front_right.png",
}


@dataclass
class Task:
    id: str
    style: str
    description: str
    constraints: dict
    image_views: list[str]


def tasks_dir() -> Path:
    return Path(os.environ.get("DREAMHOUSE_TASKS_DIR", str(DEFAULT_TASKS_DIR)))


def tasks_pack() -> Optional[Path]:
    value = os.environ.get("DREAMHOUSE_TASKS_PACK")
    return Path(value) if value else None


def _infer_style(task_id: str) -> str:
    prefix = task_id.split("_", 1)[0]
    return _STYLE_BY_PREFIX.get(prefix, prefix)


def _default_constraints(task_id: str) -> dict:
    # Conservative defaults. Real constraints should come from constraints.json.
    return {
        "footprint_x": 6.0,
        "footprint_y": 10.0,
        "stories": 1,
        "roof_type": "gable",
        "lot_width": 8.0,
        "lot_depth": 12.0,
        "wings": 0,
        "complexity": "simple",
    }


def _description(style: str, constraints: dict) -> str:
    stories = constraints.get("stories", 1)
    fx = constraints.get("footprint_x")
    fy = constraints.get("footprint_y")
    roof = constraints.get("roof_type", "gable")
    return (
        f"Generate a {stories}-story {style} timber-frame structure. "
        f"Footprint: {fx}m x {fy}m. Roof type: {roof}."
    )


def _connect_pack(pack_path: Path) -> sqlite3.Connection:
    if not pack_path.is_file():
        raise FileNotFoundError(f"Task pack not found: {pack_path}")
    return sqlite3.connect(f"file:{pack_path}?mode=ro", uri=True)


def _load_task_from_pack(task_id: str, pack_path: Path) -> Optional[Task]:
    try:
        conn = _connect_pack(pack_path)
    except FileNotFoundError:
        return None
    try:
        row = conn.execute(
            """
            SELECT task_id, style, description, constraints_json
            FROM tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        image_rows = conn.execute(
            """
            SELECT view
            FROM images
            WHERE task_id = ?
            ORDER BY CASE view
                WHEN 'front' THEN 1
                WHEN 'back' THEN 2
                WHEN 'left' THEN 3
                WHEN 'right' THEN 4
                WHEN 'top' THEN 5
                ELSE 99
            END
            """,
            (task_id,),
        ).fetchall()
    finally:
        conn.close()

    try:
        constraints = json.loads(row[3])
    except json.JSONDecodeError:
        constraints = _default_constraints(task_id)

    return Task(
        id=row[0],
        style=row[1],
        description=row[2],
        constraints=constraints,
        image_views=[r[0] for r in image_rows],
    )


def _dir_image_path(folder: Path, task_id: str, view: str, suffix: str) -> Optional[Path]:
    # Pack source folders use short names; older server fixtures use task-id
    # prefixes. Supporting both keeps local development flexible.
    candidates = [
        folder / f"{task_id}{suffix}",
        folder / suffix.removeprefix("_skin_"),
    ]
    if view == "top":
        candidates.append(folder / "front_right.png")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_task_from_dir(task_id: str) -> Optional[Task]:
    folder = tasks_dir() / task_id
    if not folder.is_dir():
        return None

    image_views: list[str] = []
    for view, suffix in VIEWS.items():
        p = _dir_image_path(folder, task_id, view, suffix)
        if p is not None:
            image_views.append(view)

    if not image_views:
        return None

    structure_file = folder / "structure.json"
    constraints_file = folder / "constraints.json"
    if structure_file.exists():
        try:
            structure = json.loads(structure_file.read_text())
            main_body = structure.get("main_body", {})
            roof = structure.get("roof", {})
            constraints = {
                "footprint_x": main_body.get("width"),
                "footprint_y": main_body.get("depth"),
                "stories": main_body.get("stories"),
                "roof_type": roof.get("type"),
                "config": structure.get("config"),
                "config_id": structure.get("config_id"),
            }
            constraints = {k: v for k, v in constraints.items() if v is not None}
            style = structure.get("style_display_name") or structure.get("style") or _infer_style(task_id)
        except json.JSONDecodeError:
            constraints = _default_constraints(task_id)
            style = _infer_style(task_id)
    elif constraints_file.exists():
        try:
            constraints = json.loads(constraints_file.read_text())
            style = constraints.pop("style", None) or _infer_style(task_id)
        except json.JSONDecodeError:
            constraints = _default_constraints(task_id)
            style = _infer_style(task_id)
    else:
        constraints = _default_constraints(task_id)
        style = _infer_style(task_id)

    return Task(
        id=task_id,
        style=style,
        description=_description(style, constraints),
        constraints=constraints,
        image_views=image_views,
    )


def load_task(task_id: str) -> Optional[Task]:
    pack = tasks_pack()
    if pack is not None:
        return _load_task_from_pack(task_id, pack)
    return _load_task_from_dir(task_id)


def load_image(task_id: str, view: str) -> Optional[bytes]:
    pack = tasks_pack()
    if pack is not None:
        try:
            conn = _connect_pack(pack)
        except FileNotFoundError:
            return None
        try:
            row = conn.execute(
                "SELECT content FROM images WHERE task_id = ? AND view = ?",
                (task_id, view),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row is not None else None

    folder = tasks_dir() / task_id
    suffix = VIEWS.get(view)
    if suffix is None:
        return None
    path = _dir_image_path(folder, task_id, view, suffix)
    if path is None:
        return None
    return path.read_bytes()


def list_task_ids() -> list[str]:
    pack = tasks_pack()
    if pack is not None:
        try:
            conn = _connect_pack(pack)
        except FileNotFoundError:
            return []
        try:
            rows = conn.execute("SELECT task_id FROM tasks ORDER BY task_id").fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    d = tasks_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())
