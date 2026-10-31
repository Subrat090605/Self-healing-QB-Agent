"""sandbox.py — Sandboxed Python code execution (subprocess, 5s timeout, no network).

Implements SPEC §8 run_python tool and SPEC §7 code verification.
"""

import os
import subprocess
import sys
import tempfile
from typing import Any


def run_python(code: str, timeout: int = 5) -> str:
    """Execute Python code in an isolated subprocess with a strict timeout.

    Args:
        code: Python script string to execute.
        timeout: Timeout in seconds (default 5s).

    Returns:
        Combined stdout or error string, truncated to 1500 chars.
    """
    # Prepend safety checks to disable socket creation (no network)
    preamble = (
        "import socket\n"
        "def _blocked(*a, **k): raise RuntimeError('Network access is disabled in sandbox')\n"
        "socket.socket = _blocked\n"
    )
    full_code = preamble + code

    # Minimal safe environment
    safe_env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            res = subprocess.run(
                [sys.executable, "-c", full_code],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )
            out = res.stdout.strip()
            err = res.stderr.strip()

            if res.returncode == 0:
                result = out if out else "(Executed successfully with no output)"
            else:
                result = f"Error (exit {res.returncode}): {err if err else out}"

        except subprocess.TimeoutExpired:
            result = f"Execution timed out after {timeout} seconds."
        except Exception as exc:
            result = f"Execution failed: {exc}"

    # Truncate to ~1500 chars per SPEC §8
    if len(result) > 1500:
        result = result[:1450] + "\n... [output truncated]"

    return result
