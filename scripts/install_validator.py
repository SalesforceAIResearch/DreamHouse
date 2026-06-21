#!/usr/bin/env python3
"""Install a validator artifact at `server/_private/validation.pyc`.

The installer accepts either a precompiled `.pyc` release artifact or a local
`.py` source file. Source files are compiled to bytecode; source is never
copied into this repo. The installed `.pyc` is ignored by git.

Note: `.pyc` bytecode can still be decompiled; this is obfuscation, not
encryption. If you need stronger protection, compile the validator to a
native extension (e.g. with Cython or Nuitka) and point
`DREAMHOUSE_VALIDATOR` at the produced `.so`.

Usage:
    python scripts/install_validator.py /path/to/validation.pyc
    python scripts/install_validator.py /path/to/validation.py
    python scripts/install_validator.py --check
    python scripts/install_validator.py --clean
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = REPO_ROOT / "server" / "_private"
TARGET = PRIVATE_DIR / "validation.pyc"

DEFAULT_BLENDER = os.environ.get(
    "BLENDER_PATH", "/Applications/Blender.app/Contents/MacOS/Blender"
)


def _find_blender_python(blender: str) -> Path | None:
    """Locate the Python interpreter bundled with Blender.app.

    On macOS the layout is:
        /Applications/Blender.app/Contents/MacOS/Blender                    # executable
        /Applications/Blender.app/Contents/Resources/<ver>/python/bin/pythonX.Y
    """
    blender_path = Path(blender)
    if not blender_path.exists():
        return None

    # .../Contents/MacOS/Blender -> .../Contents/Resources
    resources = blender_path.parent.parent / "Resources"
    if not resources.is_dir():
        return None

    for version_dir in sorted(resources.iterdir(), reverse=True):
        bin_dir = version_dir / "python" / "bin"
        if not bin_dir.is_dir():
            continue
        for p in sorted(bin_dir.iterdir()):
            if p.name.startswith("python3.") and os.access(p, os.X_OK):
                return p
    return None


def _compile_with_blender(source: Path, target: Path, blender: str) -> None:
    """Compile the source file to a .pyc using Blender's bundled Python.

    This ensures the bytecode magic number matches what the validator runner
    will encounter when it loads the file inside Blender at evaluation time.

    We prefer invoking the bundled `python3.x` binary directly (fast, clean
    exit codes). If it cannot be located we fall back to driving Blender
    itself with `--python-expr`, which is slower and noisier.
    """
    blender_python = _find_blender_python(blender)

    if blender_python is not None:
        cmd = [
            str(blender_python),
            "-c",
            (
                "import sys, py_compile\n"
                "src, dst = sys.argv[1], sys.argv[2]\n"
                "py_compile.compile(src, cfile=dst, dfile='validation.py', doraise=True)\n"
            ),
            str(source),
            str(target),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and target.exists():
            return
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        sys.exit(
            f"error: Blender's Python failed to compile the validator.\n"
            f"python: {blender_python}\nexit: {proc.returncode}\ntail:\n{tail}"
        )

    # Fallback: drive Blender itself.
    if not Path(blender).exists():
        sys.exit(
            f"error: Blender not found at {blender}. "
            "Set BLENDER_PATH or pass --no-blender (only safe if the host "
            "Python minor version matches Blender's)."
        )

    driver = (
        "import sys, py_compile\n"
        "src, dst = sys.argv[-2], sys.argv[-1]\n"
        "py_compile.compile(src, cfile=dst, dfile='validation.py', doraise=True)\n"
    )
    cmd = [
        blender,
        "--background",
        "--factory-startup",
        "--python-expr",
        driver,
        "--",
        str(source),
        str(target),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not target.exists():
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        sys.exit(
            "error: Blender failed to compile the validator.\n"
            f"exit code: {proc.returncode}\noutput tail:\n{tail}"
        )


def _compile_with_host(source: Path, target: Path) -> None:
    """Compile with the host Python. Only safe when its minor version matches
    Blender's bundled Python."""
    import py_compile

    py_compile.compile(
        str(source),
        cfile=str(target),
        dfile="validation.py",
        doraise=True,
    )


def install(source: Path, use_blender: bool, blender: str) -> Path:
    if not source.exists():
        sys.exit(f"error: source not found: {source}")
    if source.suffix not in {".py", ".pyc"}:
        sys.exit(f"error: expected a .py or .pyc file, got: {source}")

    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)

    if source.suffix == ".pyc":
        shutil.copy2(source, TARGET)
    elif use_blender:
        _compile_with_blender(source, TARGET, blender)
    else:
        _compile_with_host(source, TARGET)

    return TARGET


def check() -> int:
    if not TARGET.exists():
        print(f"not installed: {TARGET}")
        return 1
    size = TARGET.stat().st_size
    print(f"installed: {TARGET} ({size} bytes)")
    return 0


def clean() -> None:
    if TARGET.exists():
        TARGET.unlink()
        print(f"removed: {TARGET}")
    if PRIVATE_DIR.exists() and not any(PRIVATE_DIR.iterdir()):
        shutil.rmtree(PRIVATE_DIR)
        print(f"removed empty dir: {PRIVATE_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        help="path to validation.pyc or validation.py",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print whether the validator is installed and exit.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the installed validator bytecode.",
    )
    parser.add_argument(
        "--blender",
        default=DEFAULT_BLENDER,
        help=(
            "Blender executable used to compile the validator so its bytecode "
            f"magic matches the runtime. Default: {DEFAULT_BLENDER}"
        ),
    )
    parser.add_argument(
        "--no-blender",
        action="store_true",
        help=(
            "Compile with the host Python instead of Blender's bundled Python. "
            "Only safe if the Python minor versions match."
        ),
    )
    args = parser.parse_args()

    if args.check:
        sys.exit(check())
    if args.clean:
        clean()
        return
    if not args.source:
        parser.error("source is required unless --check or --clean is given")

    out = install(
        Path(args.source).expanduser().resolve(),
        use_blender=not args.no_blender,
        blender=args.blender,
    )
    print(f"installed: {out}")


if __name__ == "__main__":
    main()
