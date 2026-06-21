"""Spawn Blender headless and run the (hidden) validator on a submission.

The validator itself (compiled bytecode) is never imported directly by the
server process. Instead we pass its path to a small Blender-side driver
(`_blender_script.py`) which reconstructs a Blender collection from the
submission JSON and invokes `run_all_tests(collection)` on it.

Env vars:
  BLENDER_PATH           Path to the Blender executable.
                         Default: /Applications/Blender.app/Contents/MacOS/Blender
  DREAMHOUSE_VALIDATOR   Path to the compiled validator (.pyc or .py).
                         Default: <repo>/server/_private/validation.pyc
  DREAMHOUSE_BLENDER_TIMEOUT   seconds, default 180
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_SCRIPT = Path(__file__).resolve().parent / "_blender_script.py"
DEFAULT_VALIDATOR = REPO_ROOT / "server" / "_private" / "validation.pyc"
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


class ValidatorError(RuntimeError):
    pass


def _blender_path() -> str:
    return os.environ.get("BLENDER_PATH", DEFAULT_BLENDER)


def _validator_path() -> Path:
    return Path(os.environ.get("DREAMHOUSE_VALIDATOR", str(DEFAULT_VALIDATOR)))


def _timeout() -> int:
    return int(os.environ.get("DREAMHOUSE_BLENDER_TIMEOUT", "180"))


def run_validation(submission: dict, task_id: str) -> dict:
    """Run the validator on a submission dict. Returns the results dict.

    Raises ValidatorError with a clean message if Blender or the validator
    cannot be invoked.
    """
    blender = _blender_path()
    if not Path(blender).exists():
        raise ValidatorError(
            f"Blender not found at {blender}. Set BLENDER_PATH to your Blender executable."
        )

    validator = _validator_path()
    if not validator.exists():
        raise ValidatorError(
            f"Validator not found at {validator}. "
            "Run `python scripts/install_validator.py <path-to-validation.py>` first."
        )

    with tempfile.TemporaryDirectory(prefix="dh_validate_") as tmp:
        tmp_path = Path(tmp)
        submission_file = tmp_path / "submission.json"
        submission_file.write_text(json.dumps(submission))
        result_file = tmp_path / "result.json"

        cmd = [
            blender,
            "--background",
            "--factory-startup",
            "--python",
            str(DRIVER_SCRIPT),
            "--",
            "--submission",
            str(submission_file),
            "--output",
            str(result_file),
            "--validator",
            str(validator),
            "--task-id",
            task_id,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_timeout(),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidatorError(f"Blender validation timed out after {_timeout()}s") from exc

        if not result_file.exists():
            tail = (proc.stderr or proc.stdout or "")[-1500:]
            raise ValidatorError(
                "Validator did not produce a result file. "
                f"Blender exit={proc.returncode}. Output tail:\n{tail}"
            )

        try:
            return json.loads(result_file.read_text())
        except json.JSONDecodeError as exc:
            raise ValidatorError(f"Validator produced invalid JSON: {exc}") from exc
