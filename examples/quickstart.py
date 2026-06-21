#!/usr/bin/env python3
from __future__ import annotations

"""
DreamHouse Benchmark — Quick Start Example

This script demonstrates the full evaluation loop:
  1. Fetch a task spec and reference images from the eval server
  2. Generate Blender Python code (placeholder — swap in your model)
  3. Execute code in Blender
  4. Export geometry from the .blend file
  5. Submit geometry to the eval server
  6. Poll for validation results
  7. Print pass/fail feedback

Requirements:
  pip install requests
  Blender installed and accessible via command line

Usage:
  python examples/quickstart.py --task AF_01_0018
  python examples/quickstart.py --server http://localhost:8000 --task AF_01_0018

The default server URL is read from the DREAMHOUSE_SERVER env var and falls
back to http://localhost:8000, which matches the local server shipped in this
repo (see `server/` and README "Running the server locally").
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BLENDER_PATH = os.environ.get(
    "BLENDER_PATH", "/Applications/Blender.app/Contents/MacOS/Blender"
)
BLENDER_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 1. Fetch task from eval server
# ---------------------------------------------------------------------------

def fetch_task(server: str, task_id: str) -> dict:
    r = requests.get(f"{server}/v1/tasks/{task_id}")
    r.raise_for_status()
    return r.json()


def download_images(server: str, task: dict, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for url in task.get("reference_images", []):
        view = url.rsplit("/", 1)[-1]
        r = requests.get(f"{server}{url}")
        r.raise_for_status()
        ext = ".png"
        p = dest_dir / f"{view}{ext}"
        p.write_bytes(r.content)
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# 2. Generate code (YOUR MODEL GOES HERE)
# ---------------------------------------------------------------------------

def call_your_model(prompt: str, images: list[Path] | None = None) -> str:
    """
    Replace this function with your own model call.

    It should return Blender Python code as a string.
    The code should:
      - Create timber-frame members using bpy.ops.mesh.primitive_cube_add()
      - Name each member following conventions (Sill_01, Stud_01, Rafter_01, etc.)
      - Link all objects to a collection with the given name
      - Use standard IRC lumber dimensions (meters)

    For now, this returns a minimal placeholder that creates 4 sill plates.
    """
    return '''
import bpy
from mathutils import Vector

collection_name = "COLLECTION_NAME"

# Get or create collection
if collection_name not in bpy.data.collections:
    col = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(col)
else:
    col = bpy.data.collections[collection_name]

def add_member(name, location, scale):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    for c in obj.users_collection:
        c.objects.unlink(obj)
    col.objects.link(obj)
    return obj

W, D = 6.0, 10.0  # footprint
SILL = (0.038, 0.14)  # 2x6 sill plate

add_member("Sill_01", (W/2, 0, SILL[0]/2), (W, SILL[1], SILL[0]))
add_member("Sill_02", (W/2, D, SILL[0]/2), (W, SILL[1], SILL[0]))
add_member("Sill_03", (0, D/2, SILL[0]/2), (SILL[1], D, SILL[0]))
add_member("Sill_04", (W, D/2, SILL[0]/2), (SILL[1], D, SILL[0]))
'''


# ---------------------------------------------------------------------------
# 3 & 4. Execute in Blender and export geometry
# ---------------------------------------------------------------------------

def run_blender(code: str, blend_file: Path, collection_name: str) -> dict:
    """Run the generated code AND save the scene in a single Blender invocation.

    The generated code and the save must happen in the same bpy session;
    otherwise the in-memory scene created by the code is lost when Blender
    exits, and the subsequent save writes an empty .blend.
    """
    save_stub = (
        "\n\n# --- auto-appended by quickstart: persist the scene ---\n"
        "import bpy as _bpy\n"
        f'_bpy.ops.wm.save_as_mainfile(filepath=r"{blend_file}")\n'
    )

    script = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
    script.write(code + save_stub)
    script.close()

    cmd = [BLENDER_PATH, "--background"]
    if blend_file.exists():
        cmd.append(str(blend_file))
    cmd += ["--python", script.name]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=BLENDER_TIMEOUT)
    os.unlink(script.name)

    if result.returncode != 0:
        return {"success": False, "error": result.stderr[-1500:]}
    if not blend_file.exists():
        return {"success": False, "error": f"Blender exited 0 but {blend_file} was not written"}
    return {"success": True}


def export_geometry(blend_file: Path, collection_name: str) -> dict | None:
    """Run the Blender export script to extract members as JSON."""
    output_path = blend_file.parent / "submission.json"

    export_script = f'''
import bpy, json, sys
from mathutils import Vector

collection_name = "{collection_name}"
collection = bpy.data.collections.get(collection_name)
if collection is None:
    best, best_count = None, 0
    for c in bpy.data.collections:
        n = sum(1 for o in c.objects if o.type == "MESH")
        if n > best_count:
            best, best_count = c, n
    collection = best

members = []
if collection:
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        corners = [list(obj.matrix_world @ Vector(c)) for c in obj.bound_box]
        members.append({{
            "name": obj.name,
            "location": [round(v, 6) for v in obj.location],
            "dimensions": [round(v, 6) for v in obj.dimensions],
            "bbox_world_corners": [[round(v, 6) for v in c] for c in corners],
            "matrix_world": [[round(v, 6) for v in row] for row in obj.matrix_world],
        }})

with open(r"{output_path}", "w") as f:
    json.dump({{"members": members}}, f, indent=2)
print(f"Exported {{len(members)}} members")
'''
    script_file = blend_file.parent / "_export.py"
    script_file.write_text(export_script)

    result = subprocess.run(
        [BLENDER_PATH, "--background", str(blend_file), "--python", str(script_file)],
        capture_output=True, text=True, timeout=60,
    )
    script_file.unlink()

    if output_path.exists():
        with open(output_path) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------------
# 5 & 6. Submit to eval server and poll results
# ---------------------------------------------------------------------------

def create_session(server: str, task_id: str, model_id: str = "quickstart") -> str:
    r = requests.post(f"{server}/v1/sessions", json={
        "task_id": task_id,
        "model_id": model_id,
        "protocol": "stepwise",
    })
    r.raise_for_status()
    return r.json()["session_id"]


def submit_and_poll(server: str, session_id: str, members: list[dict],
                    timeout: int = 60) -> dict | None:
    r = requests.post(
        f"{server}/v1/sessions/{session_id}/submit",
        json={"members": members},
    )
    r.raise_for_status()
    job_id = r.json()["job_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        r = requests.get(f"{server}/v1/sessions/{session_id}/results/{job_id}")
        data = r.json()
        if data["status"] == "complete":
            return data["results"]
        if data["status"] == "failed":
            print(f"  Validation error: {data.get('error', 'unknown')}")
            return None
    print("  Timed out waiting for results")
    return None


# ---------------------------------------------------------------------------
# 7. Format feedback
# ---------------------------------------------------------------------------

def format_feedback(results: dict) -> str:
    tests = results["tests"]
    failures = [t for t, v in tests.items() if not v]
    if not failures:
        return "[SUCCESS] All 10 structural tests passed."

    lines = ["[VALIDATION FAILED]"]
    lines.append(f"  Passed: {sum(tests.values())}/10")
    lines.append(f"  Failed tests:")
    for t in failures:
        lines.append(f"    - {t}")

    sd = results.get("stability_details", {})
    if not tests.get("stability_score", True):
        lines.append(
            f"  Stability: {sd.get('grounded_members',0)}/{sd.get('total_members',0)} "
            f"members connected to ground"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global BLENDER_PATH

    parser = argparse.ArgumentParser(description="DreamHouse Benchmark — Quick Start")
    parser.add_argument(
        "--server",
        default=os.environ.get("DREAMHOUSE_SERVER", "http://localhost:8000"),
    )
    parser.add_argument("--task", default="AF_01_0018")
    parser.add_argument("--blender", default=BLENDER_PATH)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    BLENDER_PATH = args.blender

    work_dir = Path(args.output_dir or tempfile.mkdtemp(prefix="dreamhouse_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    attempts_dir = work_dir / "attempts"
    attempts_dir.mkdir(exist_ok=True)
    print(f"Working directory: {work_dir}")

    # Step 1: Fetch task
    print(f"\n[1] Fetching task {args.task}...")
    task = fetch_task(args.server, args.task)
    print(f"    Style: {task['style']}")
    print(f"    Description: {task['description']}")
    print(f"    Constraints: {task['constraints']}")

    print(f"    Downloading reference images...")
    images = download_images(args.server, task, work_dir / "images")
    print(f"    Got {len(images)} images")
    (work_dir / "task.json").write_text(json.dumps(task, indent=2))

    # Step 2: Create session
    print(f"\n[2] Creating eval session...")
    session_id = create_session(args.server, args.task)
    print(f"    Session: {session_id}")

    collection_name = args.task
    blend_file = work_dir / "structure.blend"

    # History of every attempt; dumped to summary.json at the end so the
    # feedback loop across retries is reproducible and inspectable.
    history: list[dict] = []
    final_results: dict | None = None
    final_status = "no_submission"

    # Step 3-7: Generate, execute, submit, iterate
    for attempt in range(1, args.max_retries + 1):
        attempt_dir = attempts_dir / f"attempt_{attempt}"
        attempt_dir.mkdir(exist_ok=True)
        attempt_entry: dict = {
            "attempt": attempt,
            "status": "pending",
        }
        history.append(attempt_entry)

        print(f"\n[3] Generating code (attempt {attempt})...")
        prompt = f"Build a {task['description']}"
        code = call_your_model(prompt, images)
        code = code.replace("COLLECTION_NAME", collection_name)
        code_path = attempt_dir / "code.py"
        code_path.write_text(code)
        attempt_entry["code_path"] = str(code_path.relative_to(work_dir))

        print(f"[4] Executing in Blender...")
        result = run_blender(code, blend_file, collection_name)
        if not result["success"]:
            err = result.get("error", "")[:200]
            print(f"    Blender error: {err}")
            attempt_entry["status"] = "blender_error"
            attempt_entry["error"] = err
            continue

        print(f"[5] Exporting geometry...")
        submission = export_geometry(blend_file, collection_name)
        if not submission or not submission.get("members"):
            print(f"    No members exported")
            attempt_entry["status"] = "export_empty"
            continue
        member_count = len(submission["members"])
        print(f"    {member_count} members")

        submission_path = attempt_dir / "submission.json"
        submission_path.write_text(json.dumps(submission, indent=2))
        attempt_entry["submission_path"] = str(submission_path.relative_to(work_dir))
        attempt_entry["member_count"] = member_count

        print(f"[6] Submitting to eval server...")
        results = submit_and_poll(args.server, session_id, submission["members"])
        if results is None:
            print(f"    No results from server")
            attempt_entry["status"] = "submit_failed"
            continue

        result_path = attempt_dir / "result.json"
        result_path.write_text(json.dumps(results, indent=2))
        attempt_entry["result_path"] = str(result_path.relative_to(work_dir))
        attempt_entry["all_passed"] = bool(results.get("all_passed"))
        attempt_entry["pass_rate"] = results.get("pass_rate")
        attempt_entry["tests"] = results.get("tests", {})
        attempt_entry["failed_tests"] = [
            t for t, v in (results.get("tests") or {}).items() if not v
        ]
        attempt_entry["status"] = "passed" if results.get("all_passed") else "failed"

        feedback = format_feedback(results)
        attempt_entry["feedback"] = feedback
        print(f"[7] Results:")
        print(f"    {feedback}")

        final_results = results
        final_status = attempt_entry["status"]

        if results["all_passed"]:
            print(f"\n    All tests passed on attempt {attempt}!")
            break
        else:
            print(f"\n    Retrying with feedback...")
    else:
        print(f"\n    Exhausted {args.max_retries} retries")

    # Persist the latest validation results and the full feedback history.
    if final_results is not None:
        (work_dir / "results.json").write_text(json.dumps(final_results, indent=2))

    summary = {
        "task_id": args.task,
        "server": args.server,
        "session_id": session_id,
        "status": final_status,
        "attempts_made": len(history),
        "max_retries": args.max_retries,
        "all_passed": bool(final_results and final_results.get("all_passed")),
        "final_results": final_results,
        "history": history,
    }
    (work_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\nArtifacts:")
    print(f"  {work_dir}/task.json         - task spec")
    print(f"  {work_dir}/images/           - reference images")
    print(f"  {work_dir}/structure.blend   - last Blender scene")
    print(f"  {work_dir}/attempts/         - per-attempt code, submission, result")
    if final_results is not None:
        print(f"  {work_dir}/results.json      - latest validation results")
    print(f"  {work_dir}/summary.json      - full feedback history")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
