"""Run Rita's syntax checks and hardware-independent test suite."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON_FILES = [
    "main.py",
    "local_commands.py",
    "ai_brain.py",
    "system_control.py",
    "voice.py",
    "qa_static_analysis.py",
    "verify.py",
    "tests/test_ai_brain.py",
    "tests/test_system_control.py",
    "tests/test_local_commands.py",
    "tests/test_voice.py",
    "tests/test_integration_smoke.py",
]


def main() -> int:
    print("[1/3] Compiling Python files…")
    subprocess.run(
        [sys.executable, "-m", "py_compile", *PYTHON_FILES],
        cwd=ROOT,
        check=True,
    )
    print("Syntax check passed.")

    print("[2/3] Running static source/dependency audit…")
    subprocess.run([sys.executable, "qa_static_analysis.py"], cwd=ROOT, check=True)

    print("[3/3] Running unit and integration tests…")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"\n{result.testsRun} tests run; failures={len(result.failures)}, errors={len(result.errors)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
