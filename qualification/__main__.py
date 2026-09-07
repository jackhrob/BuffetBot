"""Run qualification in a credential-free temporary working directory."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("var/qualification/report.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="buffetbot-bb002-") as directory:
        work = Path(directory)
        # Deliberate allowlist: no inherited broker, cloud, model, dotenv or data-provider settings.
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
        env.update(
            PYTHONPATH=str(root),
            LUMIBOT_DISABLE_DOTENV="1",
            LUMIBOT_DISABLE_DOTENV_LOCAL="1",
            LUMIBOT_LOG_LEVEL="ERROR",
            LUMIBOT_CACHE_FOLDER=str(work / "cache"),
            MPLCONFIGDIR=str(work / "matplotlib"),
            IS_BACKTESTING="True",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
        )
        completed = subprocess.run(
            [sys.executable, "-m", "qualification.run", str(work / "report.json")],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode:
            sys.stderr.write(completed.stdout + completed.stderr)
            return completed.returncode
        report = json.loads((work / "report.json").read_text())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"BB-002: {report['decision']}; evidence: {args.output}")
    print("Synthetic offline accounting and local broker transport only; actual paper: Not run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
