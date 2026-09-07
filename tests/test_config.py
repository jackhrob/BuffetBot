from pathlib import Path

import pytest

from buffetbot.config import (
    ConfigurationError,
    Settings,
    StoragePaths,
    inspect_directory,
    load_credentials,
    load_settings,
    resolve_paths,
)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('mode = "live"', "live trading is not supported"),
        ('mode = "LIVE"', "live trading is not supported"),
        ('mode = "paper"\n[broker]\nendpoint = "https://api.alpaca.markets"', "live endpoints"),
        ('[broker]\nendpoint = "https://paper-api.alpaca.markets.evil.test"', "live endpoints"),
        ('mode = "offline"\nunsupported = "value"', "Invalid configuration fields"),
        ("[paths]\nstate = 123", "Invalid configuration fields"),
        ('mode = "unfinished', "not valid TOML"),
    ],
)
def test_invalid_config_does_not_fall_back(project, content, message):
    path = project / "config/offline.toml"
    path.write_text(content)
    with pytest.raises(ConfigurationError, match=message):
        load_settings(path)


def test_paths_resolve_against_config_without_writing_or_using_cwd(project, monkeypatch):
    config = project / "config/offline.toml"
    monkeypatch.chdir(project.parent)
    paths = resolve_paths(load_settings(config), config)
    assert paths == {name: project / "var" / name for name in ("state", "data", "artifacts")}
    assert not (project / "var").exists()
    assert all(inspect_directory(path)["ready"] for path in paths.values())


@pytest.mark.parametrize("target", ["", " ", "bad\x00path", "bad\npath", "https://example.test"])
def test_invalid_directory_syntax(project, target):
    settings = Settings(paths=StoragePaths(state=target))
    with pytest.raises(ConfigurationError, match="nonempty local directory"):
        resolve_paths(settings, project / "config/offline.toml")


@pytest.mark.parametrize("target", ["..", "../src", "../docs/generated", "../.git", "../config"])
def test_runtime_cannot_overlap_source(project, target):
    settings = Settings(paths=StoragePaths(state=target))
    with pytest.raises(ConfigurationError, match="under project var"):
        resolve_paths(settings, project / "config/offline.toml")


def test_symlink_cannot_redirect_runtime_into_source(project):
    (project / "src").mkdir()
    (project / "var").symlink_to(project / "src", target_is_directory=True)
    with pytest.raises(ConfigurationError, match="under project var"):
        resolve_paths(Settings(), project / "config/offline.toml")


@pytest.mark.parametrize("target", ["../var/state", "../var/state/nested", "../var"])
def test_runtime_directories_cannot_overlap(project, target):
    settings = Settings(paths=StoragePaths(data=target))
    with pytest.raises(ConfigurationError, match="must not overlap"):
        resolve_paths(settings, project / "config/offline.toml")


def test_existing_file_in_directory_path_is_rejected(project):
    (project / "var").write_text("a file, not a directory")
    with pytest.raises(ConfigurationError, match="existing file"):
        resolve_paths(Settings(), project / "config/offline.toml")


def test_custom_external_paths_are_supported(project, tmp_path_factory):
    external = tmp_path_factory.mktemp("external")
    settings = Settings(paths=StoragePaths(state=str(external / "state")))
    assert resolve_paths(settings, project / "config/offline.toml")["state"] == external / "state"


def test_permission_failure_is_a_missing_prerequisite(project, monkeypatch):
    monkeypatch.setattr("buffetbot.config.os.access", lambda *args: False)
    check = inspect_directory(project / "var/state")
    assert not check["ready"]
    assert "permission" in check["detail"]


def test_credentials_require_explicit_file_and_env_overrides_file(project):
    path = project / "config/secrets.local.toml"
    path.write_text('[alpaca]\napi_key = "file-key"\napi_secret = "file-secret"\n')
    assert load_credentials(environ={}).missing_fields() == ["api_key", "api_secret"]
    credentials = load_credentials(path, environ={"BUFFETBOT_ALPACA_API_KEY": "env-key"})
    assert credentials.api_key.get_secret_value() == "env-key"
    assert credentials.api_secret.get_secret_value() == "file-secret"
    assert credentials.missing_fields() == []
    assert "env-key" not in repr(credentials)
    assert "file-secret" not in credentials.model_dump_json()
    assert load_credentials(path, environ={"BUFFETBOT_ALPACA_API_KEY": " "}).missing_fields() == [
        "api_key"
    ]


def test_invalid_secret_schema_never_echoes_its_values(project):
    path = project / "config/secrets.local.toml"
    path.write_text('[alpaca]\napi_secret = ["DUMMY_SECRET_IN_INVALID_FIELD"]\n')
    with pytest.raises(ConfigurationError) as error:
        load_credentials(path, environ={})
    assert "DUMMY_SECRET" not in str(error.value)


def test_example_secrets_are_blank_placeholders():
    example = Path(__file__).resolve().parents[1] / "config/secrets.example.toml"
    assert load_credentials(example, environ={}).missing_fields() == ["api_key", "api_secret"]
