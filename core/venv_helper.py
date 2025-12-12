"""
venv_helper.py

Responsibilities:
- Create a Python virtual environment programmatically.
- Detect OS-specific python executable paths inside the venv.
- Install requirements from a given requirements.txt path.
- Run arbitrary pip commands inside the venv.
- Provide clear success/failure results without hiding errors.

Design principles:
- Fail loudly. Do not guess silently.
- Keep return values structured: (success: bool, output: str)
- Do *not* activate venvs in-process — always call the venv's python executable.

Example:
    from venv_helper import ensure_venv
    ok, msg, py = ensure_venv(Path("/path/.venv"), requirements=Path("requirements.txt"))
    if ok:
        print("Venv ready at", py)

"""
from __future__ import annotations
import subprocess
import platform
import venv
from pathlib import Path
from typing import Optional, Tuple


# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------

def venv_python(venv_dir: Path) -> Path:
    """Return the python executable inside a venv directory.

    Windows: <venv>/Scripts/python.exe
    Unix:    <venv>/bin/python
    """
    if platform.system().lower() == "windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_venv(venv_dir: Path) -> Tuple[bool, str]:
    """Create a venv. Return (success, message)."""
    try:
        builder = venv.EnvBuilder(with_pip=True, clear=False)
        builder.create(str(venv_dir))
        return True, f"venv created at {venv_dir}"
    except Exception as e:
        return False, f"venv creation failed: {e}" 


def pip_install(python_exe: Path, requirements: Path) -> Tuple[bool, str]:
    """Install dependencies via pip in the venv.

    Returns (success, combined_output).
    """
    if not python_exe.exists():
        return False, f"python not found in venv: {python_exe}"
    if not requirements.exists():
        return False, f"requirements.txt not found: {requirements}"

    cmd = [str(python_exe), "-m", "pip", "install", "-r", str(requirements)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        return proc.returncode == 0, out
    except Exception as e:
        return False, f"pip install error: {e}"


def pip_run(python_exe: Path, args: list[str]) -> Tuple[bool, str]:
    """Run an arbitrary pip command inside the venv.

    Example:
        pip_run(py, ["install", "opencv-python"])
    """
    if not python_exe.exists():
        return False, f"python not found: {python_exe}"

    cmd = [str(python_exe), "-m", "pip"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        return proc.returncode == 0, out
    except Exception as e:
        return False, f"pip run error: {e}"


# -------------------------------------------------------------
# High-level orchestrator
# -------------------------------------------------------------

def ensure_venv(venv_dir: Path, *, requirements: Optional[Path] = None) -> Tuple[bool, str, Optional[Path]]:
    """Ensure a fully-initialized venv exists.

    Returns (success, message, python_executable).

    - If venv already exists and has a python executable, we consider it valid.
    - If missing, create it.
    - If requirements provided, install them.
    """
    py = venv_python(venv_dir)

    # If the python executable already exists, assume it's a valid venv.
    if py.exists():
        if requirements:
            ok, out = pip_install(py, requirements)
            msg = "requirements installed" if ok else out
            return ok, msg, py
        return True, "venv already exists", py

    # Create venv
    ok, msg = create_venv(venv_dir)
    if not ok:
        return False, msg, None

    py = venv_python(venv_dir)
    if not py.exists():
        return False, "venv python missing after creation", None

    # Install requirements
    if requirements:
        ok, out = pip_install(py, requirements)
        msg = out if not ok else "requirements installed"
        return ok, msg, py

    return True, "venv created", py


if __name__ == "__main__":
    # Local smoke test
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "ds_test_venv"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)

    ok, msg, py = ensure_venv(tmp)
    print("Created:", ok, msg, py)
