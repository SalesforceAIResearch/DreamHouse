#!/usr/bin/env python3
"""Build a DreamHouse task pack from rendered task folders.

The pack is a SQLite database with a `.dhpack` extension. It stores the public
task metadata and rendered PNG views needed by the local eval server, without
shipping the original `.blend` source files or a browsable task folder tree.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


RAW_VIEW_FILES = {
    "front": "front.png",
    "back": "back.png",
    "left": "left.png",
    "right": "right.png",
    "top": "front_right.png",
}


def _constraints_from_structure(task_id: str, structure: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not structure:
        return _infer_style(task_id), {}

    style = (
        structure.get("style_display_name")
        or structure.get("style")
        or _infer_style(task_id)
    )
    main_body = structure.get("main_body") or {}
    roof = structure.get("roof") or {}
    constraints = {
        "footprint_x": main_body.get("width"),
        "footprint_y": main_body.get("depth"),
        "stories": main_body.get("stories"),
        "roof_type": roof.get("type"),
        "config": structure.get("config"),
        "config_id": structure.get("config_id"),
        "complexity": structure.get("params", {}).get("complexity"),
    }
    return style, {k: v for k, v in constraints.items() if v is not None}


def _infer_style(task_id: str) -> str:
    prefix = task_id.split("_", 1)[0]
    return {
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
    }.get(prefix, prefix)


def _description(style: str, constraints: dict[str, Any]) -> str:
    stories = constraints.get("stories", 1)
    fx = constraints.get("footprint_x", "unknown")
    fy = constraints.get("footprint_y", "unknown")
    roof = constraints.get("roof_type", "unknown")
    return (
        f"Generate a {stories}-story {style} timber-frame structure. "
        f"Footprint: {fx}m x {fy}m. Roof type: {roof}."
    )


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;

        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            style TEXT NOT NULL,
            description TEXT NOT NULL,
            constraints_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS images (
            task_id TEXT NOT NULL,
            view TEXT NOT NULL,
            content BLOB NOT NULL,
            PRIMARY KEY (task_id, view),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        );
        """
    )


def build_pack(
    source_dir: Path,
    output: Path,
    limit: int | None = None,
    force: bool = False,
    vacuum: bool = False,
) -> None:
    if not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")
    if output.exists() and not force:
        raise SystemExit(f"Output already exists: {output} (use --force to overwrite)")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    task_dirs = sorted(p for p in source_dir.iterdir() if p.is_dir())
    if limit is not None:
        task_dirs = task_dirs[:limit]
    if not task_dirs:
        raise SystemExit(f"No task folders found in {source_dir}")

    conn = sqlite3.connect(output)
    try:
        _create_schema(conn)
        conn.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("format", "dreamhouse-dhpack-v1"))
        conn.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("source", str(source_dir)))

        packed = 0
        skipped: list[str] = []
        for task_dir in task_dirs:
            task_id = task_dir.name
            missing = [name for name in RAW_VIEW_FILES.values() if not (task_dir / name).is_file()]
            if missing:
                skipped.append(f"{task_id}: missing {', '.join(missing)}")
                continue

            structure_path = task_dir / "structure.json"
            structure = None
            if structure_path.is_file():
                try:
                    structure = json.loads(structure_path.read_text())
                except json.JSONDecodeError:
                    structure = None

            style, constraints = _constraints_from_structure(task_id, structure)
            conn.execute(
                """
                INSERT INTO tasks(task_id, style, description, constraints_json)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, style, _description(style, constraints), json.dumps(constraints, sort_keys=True)),
            )
            for view, filename in RAW_VIEW_FILES.items():
                conn.execute(
                    "INSERT INTO images(task_id, view, content) VALUES (?, ?, ?)",
                    (task_id, view, (task_dir / filename).read_bytes()),
                )
            packed += 1
            if packed % 100 == 0:
                print(f"Packed {packed} tasks...", file=sys.stderr)

        conn.commit()
        if vacuum:
            # VACUUM can require roughly another copy of the database as
            # temporary disk space, so keep it opt-in for multi-GB task packs.
            conn.execute("VACUUM")
    finally:
        conn.close()

    print(f"Packed {packed} tasks into {output}")
    if skipped:
        print(f"Skipped {len(skipped)} tasks:")
        for item in skipped[:20]:
            print(f"  - {item}")
        if len(skipped) > 20:
            print(f"  ... {len(skipped) - 20} more")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a DreamHouse .dhpack dataset")
    parser.add_argument("source_dir", type=Path, help="Path to timber_raw task folders")
    parser.add_argument("output", type=Path, help="Output .dhpack file")
    parser.add_argument("--limit", type=int, default=None, help="Pack only the first N tasks")
    parser.add_argument("--force", action="store_true", help="Overwrite output if it exists")
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Compact the database after writing (requires extra temporary disk space)",
    )
    args = parser.parse_args()

    build_pack(args.source_dir, args.output, limit=args.limit, force=args.force, vacuum=args.vacuum)


if __name__ == "__main__":
    main()
