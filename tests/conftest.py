import os
import subprocess
import sys

import pytest

from buffetbot.config import CREDENTIAL_ENV


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\n')
    (tmp_path / "config").mkdir()
    config = tmp_path / "config/offline.toml"
    config.write_text('mode = "offline"\n')
    return tmp_path


@pytest.fixture
def run_cli(project):
    def run(*arguments, env=None, cwd=None):
        environment = os.environ.copy()
        for variable in CREDENTIAL_ENV.values():
            environment.pop(variable, None)
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, "-m", "buffetbot", "doctor", *map(str, arguments)],
            cwd=cwd or project,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )

    return run
