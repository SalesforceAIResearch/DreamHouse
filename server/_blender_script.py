"""Runs INSIDE Blender (headless) as the driver for the local evaluator.

Responsibilities:
  1. Parse the submission JSON (list of members: name, dimensions, matrix_world).
  2. Build a fresh Blender collection containing one mesh per member whose
     bounds and world transform match the submission.
  3. Load the compiled validator module from the given path.
  4. Call `run_all_tests(collection)` and write the results to the output path.

This file intentionally contains NO validation logic. All engineering rules
live in the compiled validator, which is loaded at runtime.

Invocation:
  blender --background --factory-startup --python server/_blender_script.py -- \
      --submission /path/submission.json \
      --output /path/result.json \
      --validator /path/validation.pyc \
      --task-id AF_01_0018
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import sys
import traceback
from pathlib import Path

try:
    import bpy  # type: ignore
    from mathutils import Matrix  # type: ignore
except ImportError:
    print("ERROR: this script must be run inside Blender", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Argument parsing (args come after the "--" separator in Blender invocation)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--submission", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--validator", required=True)
    p.add_argument("--task-id", default="")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

def _wipe_scene() -> None:
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def _axis_aligned_box_verts(dim):
    dx, dy, dz = dim[0] / 2.0, dim[1] / 2.0, dim[2] / 2.0
    return [
        (-dx, -dy, -dz), (-dx, -dy,  dz),
        (-dx,  dy, -dz), (-dx,  dy,  dz),
        ( dx, -dy, -dz), ( dx, -dy,  dz),
        ( dx,  dy, -dz), ( dx,  dy,  dz),
    ]


_BOX_FACES = [
    (0, 1, 3, 2), (4, 6, 7, 5),
    (0, 2, 6, 4), (1, 5, 7, 3),
    (0, 4, 5, 1), (2, 3, 7, 6),
]


def _build_collection(submission: dict, task_id: str) -> "bpy.types.Collection":
    name = task_id or "Submission"
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)

    for m in submission.get("members", []):
        mesh = bpy.data.meshes.new(m["name"])
        verts = _axis_aligned_box_verts(m.get("dimensions", [1.0, 1.0, 1.0]))
        mesh.from_pydata(verts, [], _BOX_FACES)
        mesh.update()

        obj = bpy.data.objects.new(m["name"], mesh)
        mw = m.get("matrix_world")
        if mw is not None:
            obj.matrix_world = Matrix(mw)
        else:
            loc = m.get("location", [0.0, 0.0, 0.0])
            obj.location = loc

        collection.objects.link(obj)

    bpy.context.view_layer.update()
    return collection


# ---------------------------------------------------------------------------
# Validator loading
# ---------------------------------------------------------------------------

def _load_validator(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Validator not found: {path}")

    # importlib supports both .py and .pyc via source/bytecode loaders.
    suffix = path.suffix.lower()
    spec = None
    if suffix == ".py":
        spec = importlib.util.spec_from_file_location("dreamhouse_validator", str(path))
    elif suffix == ".pyc":
        loader = importlib.machinery.SourcelessFileLoader(
            "dreamhouse_validator", str(path)
        )
        spec = importlib.util.spec_from_loader("dreamhouse_validator", loader)
    else:
        # Fallback: attempt source loading
        spec = importlib.util.spec_from_file_location("dreamhouse_validator", str(path))

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load validator from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["dreamhouse_validator"] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------

# The public API advertises these 10 tests. The validator returns a superset;
# we project down for the client response and also pass through extra details.
PUBLIC_TESTS = [
    "completeness",
    "load_path",
    "span_limits",
    "deflection",
    "roof_coverage",
    "gap_detection",
    "point_load",
    "cantilever",
    "stability_score",
    "dual_end_connection",
]


def _shape_results(task_id: str, raw: dict) -> dict:
    tests = {name: bool(raw.get(name, True)) for name in PUBLIC_TESTS}
    passed_count = sum(1 for v in tests.values() if v)
    return {
        "task_id": task_id,
        "all_passed": bool(raw.get("all_passed", all(tests.values()))),
        "pass_rate": passed_count / len(tests) if tests else 0.0,
        "tests": tests,
        "stability_details": raw.get("stability_details", {}),
        "dual_end_details": raw.get("dual_end_details", {}),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)

    try:
        submission = json.loads(Path(args.submission).read_text())
        _wipe_scene()
        collection = _build_collection(submission, args.task_id)
        validator = _load_validator(Path(args.validator))
        raw = validator.run_all_tests(collection)
        shaped = _shape_results(args.task_id, raw if isinstance(raw, dict) else {})
        output_path.write_text(json.dumps(shaped))
    except Exception as exc:  # noqa: BLE001
        err = {
            "task_id": args.task_id,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        try:
            output_path.write_text(json.dumps(err))
        except Exception:
            pass
        print(err["traceback"], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
