#!/usr/bin/env python3
"""
DreamHouse Benchmark — Reusable Pipeline Scaffold

A configurable, model-agnostic pipeline runner for evaluating AI models on the
DreamHouse timber-frame benchmark. Plug in your own model by subclassing
``ModelBackend`` and implementing ``generate()``.

Usage:
  python examples/pipeline_scaffold.py --config my_config.yaml

Config (YAML):
  server_url: http://localhost:8000     # or set env var DREAMHOUSE_SERVER
  task_id: AF_01_0018
  model_id: my-model-v1
  blender_path: /Applications/Blender.app/Contents/MacOS/Blender
  output_dir: ./output/AF_01_0018
  max_retries_per_step: 5
  max_global_retries: 30
  max_steps: 15

Requirements:
  pip install requests pyyaml
"""

from __future__ import annotations

import abc
import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: pip install pyyaml")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dreamhouse_pipeline")

EARLY_TESTS = {"stability_score", "load_path"}
FINAL_TESTS = {
    "stability_score", "load_path", "span_limits", "deflection",
    "point_load", "cantilever", "dual_end_connection",
    "completeness", "roof_coverage", "gap_detection",
}


# ============================================================================
# Model Backend (abstract — implement this)
# ============================================================================

class ModelBackend(abc.ABC):
    """
    Abstract base class for model backends.

    Subclass this and implement ``generate()`` to plug in your model.
    The pipeline calls ``generate()`` for every prompt, maintaining
    conversation history via ``start_session()`` / the backend's own state.
    """

    @abc.abstractmethod
    def start_session(self, system_prompt: str) -> None:
        """Begin a new conversation session with the given system prompt."""
        ...

    @abc.abstractmethod
    def generate(self, prompt: str, images: list[Path] | None = None) -> str:
        """
        Send a prompt (and optionally images) to the model.

        Must return a string containing Blender Python code in a
        ```python ... ``` block (or raw code).
        """
        ...


class DummyBackend(ModelBackend):
    """Placeholder backend that returns a fixed sill-plate script."""

    def start_session(self, system_prompt: str) -> None:
        logger.info("DummyBackend: session started")

    def generate(self, prompt: str, images: list[Path] | None = None) -> str:
        return '''```python
import bpy

collection_name = "__COLLECTION__"
if collection_name not in bpy.data.collections:
    col = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(col)
else:
    col = bpy.data.collections[collection_name]

def add(name, loc, scale):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    for c in obj.users_collection:
        c.objects.unlink(obj)
    col.objects.link(obj)

add("Sill_01", (3, 0, 0.019), (6, 0.14, 0.038))
add("Sill_02", (3, 10, 0.019), (6, 0.14, 0.038))
add("Sill_03", (0, 5, 0.019), (0.14, 10, 0.038))
add("Sill_04", (6, 5, 0.019), (0.14, 10, 0.038))
```'''


# ============================================================================
# Eval Server Client
# ============================================================================

class EvalClient:
    """Thin wrapper around the DreamHouse eval server HTTP API."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def health(self) -> bool:
        try:
            r = requests.get(f"{self.base}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def get_task(self, task_id: str) -> dict:
        r = requests.get(f"{self.base}/v1/tasks/{task_id}")
        r.raise_for_status()
        return r.json()

    def download_image(self, url_path: str) -> bytes:
        r = requests.get(f"{self.base}{url_path}")
        r.raise_for_status()
        return r.content

    def create_session(self, task_id: str, model_id: str = "unknown") -> str:
        r = requests.post(f"{self.base}/v1/sessions", json={
            "task_id": task_id, "model_id": model_id, "protocol": "stepwise",
        })
        r.raise_for_status()
        return r.json()["session_id"]

    def submit(self, session_id: str, members: list[dict]) -> str:
        r = requests.post(
            f"{self.base}/v1/sessions/{session_id}/submit",
            json={"members": members},
        )
        r.raise_for_status()
        return r.json()["job_id"]

    def poll(self, session_id: str, job_id: str, timeout: int = 60) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1)
            r = requests.get(f"{self.base}/v1/sessions/{session_id}/results/{job_id}")
            data = r.json()
            if data["status"] == "complete":
                return data["results"]
            if data["status"] == "failed":
                logger.error("Validation failed: %s", data.get("error", ""))
                return None
        return None

    def get_export_script(self) -> str:
        r = requests.get(f"{self.base}/v1/docs/export-script")
        r.raise_for_status()
        return r.text


# ============================================================================
# Blender Executor
# ============================================================================

class BlenderExecutor:
    def __init__(self, blender_path: str, timeout: int = 120):
        self.blender = blender_path
        self.timeout = timeout

    def run_code(self, code: str, blend_file: Path) -> dict:
        script = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        script.write(code)
        script.close()

        cmd = [self.blender, "--background"]
        if blend_file.exists():
            cmd.append(str(blend_file))
        cmd += ["--python", script.name]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            os.unlink(script.name)
            return {"success": False, "error": "Blender timed out"}
        finally:
            if os.path.exists(script.name):
                os.unlink(script.name)

        if result.returncode != 0:
            return {"success": False, "error": result.stderr[-1500:]}
        return {"success": True, "stdout": result.stdout}

    def export_geometry(self, blend_file: Path, collection_name: str) -> list[dict] | None:
        output_path = blend_file.parent / "submission.json"
        export_code = f'''
import bpy, json
from mathutils import Vector

collection = bpy.data.collections.get("{collection_name}")
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
    json.dump({{"members": members}}, f)
print(f"Exported {{len(members)}} members")
'''
        result = self.run_code(export_code, blend_file)
        if not result["success"]:
            return None
        if output_path.exists():
            with open(output_path) as f:
                data = json.load(f)
            return data.get("members", [])
        return None


# ============================================================================
# Pipeline Runner
# ============================================================================

class PipelineRunner:
    def __init__(
        self,
        backend: ModelBackend,
        client: EvalClient,
        blender: BlenderExecutor,
        config: dict,
    ):
        self.backend = backend
        self.client = client
        self.blender = blender
        self.config = config
        self.task_id = config["task_id"]
        self.collection_name = config.get("collection_name", self.task_id)
        self.output_dir = Path(config.get("output_dir", f"./output/{self.task_id}"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries_per_step = config.get("max_retries_per_step", 5)
        self.max_global_retries = config.get("max_global_retries", 30)
        self.max_steps = config.get("max_steps", 15)
        self.global_retries = 0
        self.session_id: str | None = None

    def run(self) -> dict:
        """Run the full pipeline. Returns a summary dict."""
        logger.info("Fetching task %s...", self.task_id)
        task = self.client.get_task(self.task_id)
        images = self._download_images(task)

        logger.info("Creating eval session...")
        self.session_id = self.client.create_session(
            self.task_id, self.config.get("model_id", "unknown")
        )

        self.backend.start_session(
            "You are an expert timber-frame structural engineer. "
            "You build structures step-by-step in Blender using Python/bpy. "
            "Use standard IRC lumber dimensions in meters."
        )

        # Phase 0: generate construction plan
        logger.info("Phase 0: generating plan...")
        plan = self._run_phase0(task, images)
        if plan is None:
            return {"success": False, "reason": "phase0_failed"}

        steps = plan.get("construction_order", [])
        total_steps = len(steps)
        logger.info("Plan: %d steps", total_steps)

        # Construction steps
        results = []
        blend_file = self.output_dir / "structure.blend"

        for i, step in enumerate(steps[:self.max_steps]):
            is_final = (i == len(steps) - 1) or (i == self.max_steps - 1)
            step_result = self._run_step(i, step, blend_file, is_final)
            results.append(step_result)
            if not step_result["success"]:
                logger.error("Step %d failed, stopping.", i + 1)
                break

        succeeded = sum(1 for r in results if r["success"])
        summary = {
            "task_id": self.task_id,
            "model_id": self.config.get("model_id", "unknown"),
            "total_steps": total_steps,
            "succeeded": succeeded,
            "global_retries": self.global_retries,
            "step_results": results,
        }

        summary_path = self.output_dir / "results.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("Done: %d/%d steps, %d retries. Saved to %s",
                     succeeded, total_steps, self.global_retries, summary_path)
        return summary

    def _download_images(self, task: dict) -> list[Path]:
        img_dir = self.output_dir / "images"
        img_dir.mkdir(exist_ok=True)
        paths = []
        for url in task.get("reference_images", []):
            view = url.rsplit("/", 1)[-1]
            data = self.client.download_image(url)
            p = img_dir / f"{view}.png"
            p.write_bytes(data)
            paths.append(p)
        return paths

    def _run_phase0(self, task: dict, images: list[Path]) -> dict | None:
        prompt = (
            f"Analyze these reference images of a {task['style']} timber-frame structure.\n"
            f"Constraints: {json.dumps(task['constraints'])}\n\n"
            f"Create a step-by-step construction plan as JSON with a "
            f"'construction_order' array. Each step should have: "
            f"'step' (number), 'description' (string), 'section' (string).\n\n"
            f"The collection name in Blender must be: {self.collection_name}"
        )
        response = self.backend.generate(prompt, images)
        (self.output_dir / "phase0_response.txt").write_text(response)
        return self._extract_json(response)

    def _run_step(self, step_idx: int, step_info: dict, blend_file: Path,
                  is_final: bool) -> dict:
        step_num = step_idx + 1
        description = step_info.get("description", f"Step {step_num}")
        logger.info("Step %d/%s: %s", step_num,
                     "FINAL" if is_final else "...", description)

        checks = FINAL_TESTS if is_final else EARLY_TESTS
        check_label = "all 10 tests" if is_final else "stability + load_path"

        for retry in range(self.max_retries_per_step):
            if self.global_retries >= self.max_global_retries:
                return {"step": step_num, "success": False, "reason": "global_limit"}

            prompt = (
                f"Step {step_num}: {description}\n"
                f"Collection: {self.collection_name}\n"
                f"Generate complete Blender Python code."
            )
            if retry > 0:
                prompt += f"\n\nThis is retry {retry + 1}. Fix the issues."

            logger.info("  Attempt %d/%d", retry + 1, self.max_retries_per_step)

            response = self.backend.generate(prompt)
            code = self._extract_code(response)
            if not code:
                self.global_retries += 1
                continue

            # Execute
            exec_result = self.blender.run_code(code, blend_file)
            if not exec_result["success"]:
                self.backend.generate(
                    f"[ERROR] Blender failed:\n{exec_result['error'][:1000]}"
                )
                self.global_retries += 1
                continue

            # Export
            members = self.blender.export_geometry(blend_file, self.collection_name)
            if not members:
                self.backend.generate("[ERROR] No members exported from Blender.")
                self.global_retries += 1
                continue

            # Submit
            job_id = self.client.submit(self.session_id, members)
            results = self.client.poll(self.session_id, job_id)
            if results is None:
                self.global_retries += 1
                continue

            tests = results["tests"]
            failures = {t for t in checks if not tests.get(t, True)}

            if not failures:
                logger.info("  PASSED (%s)", check_label)
                self.backend.generate(
                    f"[SUCCESS] Step {step_num} passed {check_label}."
                )
                return {
                    "step": step_num,
                    "success": True,
                    "retries": retry,
                    "tests": tests,
                    "members": len(members),
                }

            feedback = self._format_feedback(results, checks, failures, step_num)
            logger.info("  FAILED %d/%d — retrying", len(checks) - len(failures), len(checks))
            self.backend.generate(feedback)
            self.global_retries += 1

        return {"step": step_num, "success": False, "reason": "max_retries"}

    @staticmethod
    def _format_feedback(results: dict, checks: set, failures: set,
                         step_num: int) -> str:
        lines = [f"[VALIDATION FAILED — step {step_num}]"]
        lines.append(f"Passed: {len(checks) - len(failures)}/{len(checks)}")
        lines.append("Failed tests:")
        for t in sorted(failures):
            lines.append(f"  - {t}")

        sd = results.get("stability_details", {})
        if "stability_score" in failures:
            lines.append(
                f"Stability: {sd.get('grounded_members',0)}/{sd.get('total_members',0)} "
                f"connected to ground"
            )
        dd = results.get("dual_end_details", {})
        if "dual_end_connection" in failures:
            lines.append(
                f"Dual-end: rafters {dd.get('rafters_failed',0)}/{dd.get('rafters_checked',0)} "
                f"failed, studs {dd.get('studs_failed',0)}/{dd.get('studs_checked',0)} failed"
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_code(response: str) -> str | None:
        import re
        m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*\n(.*?)```", response, re.DOTALL)
        if m:
            return m.group(1).strip()
        if "import bpy" in response:
            return response.strip()
        return None

    @staticmethod
    def _extract_json(response: str) -> dict | None:
        import re
        for pattern in [r"```json\s*\n(.*?)```", r"```\s*\n(.*?)```"]:
            m = re.search(pattern, response, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue
        try:
            start = response.index("{")
            end = response.rindex("}") + 1
            return json.loads(response[start:end])
        except (ValueError, json.JSONDecodeError):
            return None


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="DreamHouse Pipeline Scaffold")
    parser.add_argument("--config", required=True, help="YAML config file")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Resolution order: DREAMHOUSE_SERVER env var (explicit) > YAML server_url > default.
    # The env var wins so you can point one YAML config at any running server
    # (e.g. when local port 8000 is taken and the server runs on 8765) without
    # editing the config file.
    env_server = os.environ.get("DREAMHOUSE_SERVER")
    server_url = env_server or config.get("server_url") or "http://localhost:8000"
    client = EvalClient(server_url)
    if not client.health():
        sys.exit("Eval server not reachable")

    blender = BlenderExecutor(
        config.get("blender_path", "/Applications/Blender.app/Contents/MacOS/Blender"),
        timeout=config.get("blender_timeout", 120),
    )

    # Replace DummyBackend with your own ModelBackend subclass
    backend = DummyBackend()

    runner = PipelineRunner(backend, client, blender, config)
    summary = runner.run()

    succeeded = summary.get("succeeded", 0)
    total = summary.get("total_steps", 0)
    print(f"\nResult: {succeeded}/{total} steps completed, "
          f"{summary.get('global_retries', 0)} retries")


if __name__ == "__main__":
    main()
