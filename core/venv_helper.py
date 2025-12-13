"""
venv_helper.py

Responsibilities:
- Create a Python virtual environment programmatically.
- Detect OS-specific python executable paths inside the venv.
- Install requirements from a given requirements.txt path.
- Run arbitrary pip commands inside the venv.
- Provide clear success/failure results without hiding errors.

Design principles:
- Fail loudly.
- Stream output live for installers.
- Return structured results.
- Never activate venvs in-process.
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

def _pfx(tag: str) -> str:
    """Prefix helper for readable installer output."""
    return f"[{tag}]"


def venv_python(venv_dir: Path) -> Path:
    """Return the python executable inside a venv directory."""
    if platform.system().lower() == "windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_venv(venv_dir: Path) -> Tuple[bool, str]:
    """Create a venv. Return (success, message)."""
    try:
        print(f"{_pfx('venv')} Creating virtual environment at {venv_dir}")
        builder = venv.EnvBuilder(with_pip=True, clear=False)
        builder.create(str(venv_dir))
        print(f"{_pfx('venv')} Virtual environment created")
        return True, f"venv created at {venv_dir}"
    except Exception as e:
        print(f"{_pfx('error')} venv creation failed")
        return False, f"venv creation failed: {e}"


def pip_install(python_exe: Path, requirements: Path) -> Tuple[bool, str]:
    """Install dependencies via pip in the venv (LIVE output)."""
    if not python_exe.exists():
        return False, f"python not found in venv: {python_exe}"
    if not requirements.exists():
        return False, f"requirements.txt not found: {requirements}"

    cmd = [str(python_exe), "-m", "pip", "install", "-r", str(requirements)]

    print(f"{_pfx('pip')} Installing packages from {requirements}")
    try:
        proc = subprocess.run(cmd)  # 🔥 LIVE OUTPUT
        if proc.returncode == 0:
            print(f"{_pfx('pip')} Packages installed successfully")
            return True, "requirements installed"
        else:
            return False, f"pip install failed with code {proc.returncode}"
    except Exception as e:
        return False, f"pip install error: {e}"


def pip_run(python_exe: Path, args: list[str]) -> Tuple[bool, str]:
    """Run an arbitrary pip command inside the venv (LIVE)."""
    if not python_exe.exists():
        return False, f"python not found: {python_exe}"

    cmd = [str(python_exe), "-m", "pip"] + args
    print(f"{_pfx('pip')} Running: pip {' '.join(args)}")
    try:
        proc = subprocess.run(cmd)
        if proc.returncode == 0:
            return True, "pip command successful"
        return False, f"pip command failed with code {proc.returncode}"
    except Exception as e:
        return False, f"pip run error: {e}"


# -------------------------------------------------------------
# High-level orchestrator
# -------------------------------------------------------------

def ensure_venv(
    venv_dir: Path,
    *,
    requirements: Optional[Path] = None
) -> Tuple[bool, str, Optional[Path]]:
    """
    Ensure a fully-initialized venv exists.

    Returns (success, message, python_executable).
    """
    venv_dir = Path(venv_dir).expanduser().resolve()
    py = venv_python(venv_dir)

    # Existing venv
    if py.exists():
        print(f"{_pfx('venv')} Existing venv detected")
        if requirements:
            ok, msg = pip_install(py, requirements)
            return ok, msg, py
        return True, "venv already exists", py

    # Create venv
    ok, msg = create_venv(venv_dir)
    if not ok:
        return False, msg, None

    py = venv_python(venv_dir)
    if not py.exists():
        return False, "venv python missing after creation", None

    # Upgrade pip (important)
    print(f"{_pfx('pip')} Upgrading pip")
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"])

    # Install requirements
    if requirements:
        ok, msg = pip_install(py, requirements)
        return ok, msg, py

    return True, "venv created", py


# -------------------------------------------------------------
# Smoke test
# -------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    import shutil

    tmp = Path(tempfile.gettempdir()) / "ds_test_venv"
    if tmp.exists():
        shutil.rmtree(tmp)

    ok, msg, py = ensure_venv(tmp)
    print("Result:", ok, msg, py)
