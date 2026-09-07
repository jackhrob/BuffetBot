"""Opt-in engine regressions run outside the application's configuration/logging process."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec("lumibot") is None,
    reason="Install the qualification group to run BB-002 engine checks",
)
def test_offline_engine_qualification(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "report.json"
    marker = "inherited-secret-must-not-enter-qualification"
    env = dict(os.environ)
    env.update(
        ALPACA_API_KEY=marker,
        ALPACA_API_SECRET=marker,
        BUFFETBOT_ALPACA_API_KEY=marker,
        BACKTESTING_DATA_SOURCE="not-a-real-provider",
        LUMIBOT_DISABLE_DOTENV="0",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "qualification", "--output", str(output)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=210,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text())
    assert report["repeated_ledgers_equal"]
    assert (
        report["corrected"]["events"]
        == json.loads((root / "qualification/fixtures/expected.json").read_text())["events"]
    )
    assert report["network_attempts"] == 0
    assert report["paper"]["actual_paper"] == "Not run"
    assert marker not in output.read_text() + completed.stdout + completed.stderr
    assert not list(tmp_path.glob("*.joblib")), "Model must remain in isolated temporary storage"
