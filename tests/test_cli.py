import json
import os
import subprocess
import sys

from buffetbot.config import CREDENTIAL_ENV


def test_offline_doctor_succeeds_without_credentials_and_does_not_write(run_cli, project):
    result = run_cli("--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ready"
    assert report["mode"] == "offline"
    assert report["required_integrations"] == []
    assert report["broker"]["credentials"] == "missing"
    assert report["broker"]["connectivity"] == "not_checked"
    assert not (project / "var").exists()
    assert "INFO buffetbot.doctor run=" in result.stderr


def test_paper_inspection_vs_explicit_required_credentials(run_cli, project):
    (project / "config/paper.toml").write_text('mode = "paper"\n')
    inspect = run_cli("--config", "config/paper.toml", "--json")
    required = run_cli("--config", "config/paper.toml", "--require-broker", "--json")
    assert inspect.returncode == 0
    assert required.returncode == 1
    report = json.loads(required.stdout)
    assert report["status"] == "prerequisites_missing"
    assert report["required_integrations"] == ["paper_broker"]
    assert report["broker"]["missing_fields"] == ["api_key", "api_secret"]


def test_complete_paper_credentials_are_only_locally_checked(run_cli, project):
    (project / "config/paper.toml").write_text('mode = "paper"\n')
    result = run_cli(
        "--config",
        "config/paper.toml",
        "--require-broker",
        "--json",
        env={
            "BUFFETBOT_ALPACA_API_KEY": "DUMMY_KEY",
            "BUFFETBOT_ALPACA_API_SECRET": "DUMMY_SECRET",
        },
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["broker"]["credentials"] == "configured"
    assert report["broker"]["connectivity"] == "not_checked"
    assert "DUMMY_KEY" not in result.stdout + result.stderr
    assert "DUMMY_SECRET" not in result.stdout + result.stderr


def test_offline_cannot_require_broker(run_cli):
    result = run_cli("--require-broker", "--json")
    assert result.returncode == 2
    assert "paper configuration" in json.loads(result.stdout)["error"]


def test_missing_and_malformed_config_have_actionable_errors(run_cli, project):
    missing = run_cli("--config", "missing.toml", "--json")
    assert missing.returncode == 2
    assert "Cannot read" in json.loads(missing.stdout)["error"]
    (project / "config/offline.toml").write_text('[paths]\nstate = ".."\n')
    malformed = run_cli("--json")
    assert malformed.returncode == 2
    assert "paths.state" in json.loads(malformed.stdout)["error"]


def test_configuration_and_error_output_redact_file_credentials(run_cli, project):
    secret = "DUMMY_FILE_SECRET_9812"
    (project / "config/secrets.local.toml").write_text(
        f'[alpaca]\napi_key = "dummy-key"\napi_secret = "{secret}"\n'
    )
    config = project / "config/offline.toml"
    config.write_text(f'[paths]\nstate = "../var/{secret}"\n')
    result = run_cli("--secrets", "config/secrets.local.toml", "--json")
    assert result.returncode == 0
    assert secret not in result.stdout + result.stderr
    assert "[REDACTED]" in result.stdout
    config.write_text(f'mode = "{secret}"\n')
    error = run_cli("--secrets", "config/secrets.local.toml", "--json")
    assert error.returncode == 2
    assert secret not in error.stdout + error.stderr
    assert "Traceback" not in error.stderr


def test_argument_errors_never_echo_pasted_credentials(run_cli):
    result = run_cli("--api-key", "DUMMY_PASTED_SECRET")
    assert result.returncode == 2
    assert "DUMMY_PASTED_SECRET" not in result.stdout + result.stderr
    assert "--help" in result.stderr


def test_doctor_has_no_network_side_effects(project):
    environment = {
        key: value for key, value in os.environ.items() if key not in CREDENTIAL_ENV.values()
    }
    code = """
import socket
def deny_network(*args, **kwargs):
    raise AssertionError('Network access is forbidden in the doctor command')
socket.socket = deny_network
socket.create_connection = deny_network
from buffetbot.cli import main
raise SystemExit(main(['doctor', '--json']))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
