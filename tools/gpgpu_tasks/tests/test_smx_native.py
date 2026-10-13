"""Opt-in regression against an actually compiled native SMX bench."""
import os
from pathlib import Path
import subprocess

import pytest


def test_native_bench_stops_without_reading_a_phantom_case():
    executable = os.environ.get("SMX_BINARY")
    if not executable:
        pytest.skip("set SMX_BINARY to run the compiled-bench regression")
    repo = Path(__file__).resolve().parents[3]
    result = subprocess.run([executable], cwd=repo / "tests/hardware/rtl", capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[SUCCESS] Test 25" in result.stdout
    assert "Starting test 26" not in result.stdout
    assert "$readmem file not found" not in result.stdout
