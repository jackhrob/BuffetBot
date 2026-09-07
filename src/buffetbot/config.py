"""Explicit local configuration; loading it never connects to an external service."""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
CREDENTIAL_ENV = {
    "api_key": "BUFFETBOT_ALPACA_API_KEY",
    "api_secret": "BUFFETBOT_ALPACA_API_SECRET",
}


class ConfigurationError(ValueError):
    """An actionable error that deliberately excludes raw configuration values."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class StoragePaths(StrictModel):
    state: str = "../var/state"
    data: str = "../var/data"
    artifacts: str = "../var/artifacts"


class BrokerSettings(StrictModel):
    endpoint: Literal["https://paper-api.alpaca.markets"] = PAPER_ENDPOINT


class Settings(StrictModel):
    mode: Literal["offline", "paper"] = "offline"
    paths: StoragePaths = Field(default_factory=StoragePaths)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)


class AlpacaCredentials(StrictModel):
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    api_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))

    def missing_fields(self) -> list[str]:
        return [
            name for name in CREDENTIAL_ENV if not getattr(self, name).get_secret_value().strip()
        ]

    def secret_values(self) -> tuple[str, ...]:
        return tuple(getattr(self, name).get_secret_value() for name in CREDENTIAL_ENV)


class Secrets(StrictModel):
    alpaca: AlpacaCredentials = Field(default_factory=AlpacaCredentials)


def read_toml(path: Path, *, description: str) -> dict:
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except tomllib.TOMLDecodeError:
        raise ConfigurationError(f"{description} is not valid TOML; check its syntax.") from None
    except (OSError, ValueError):
        raise ConfigurationError(
            f"Cannot read {description}; check the path and permissions."
        ) from None


def load_settings(path: Path) -> Settings:
    data = read_toml(path, description="configuration file")
    try:
        return Settings.model_validate(data)
    except ValidationError as error:
        locations = {issue["loc"] for issue in error.errors(include_input=False)}
        if ("mode",) in locations:
            message = "mode must be 'offline' or 'paper'; live trading is not supported."
        elif ("broker", "endpoint") in locations:
            message = f"broker.endpoint must be {PAPER_ENDPOINT}; live endpoints are not supported."
        else:
            message = (
                "Invalid configuration fields or types; use the schema in config/offline.toml."
            )
        raise ConfigurationError(message) from None


def load_credentials(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> AlpacaCredentials:
    environment = os.environ if environ is None else environ
    data = read_toml(path, description="secrets file") if path is not None else {}
    try:
        secrets = Secrets.model_validate(data)
        values = secrets.alpaca.model_dump()
        for field, variable in CREDENTIAL_ENV.items():
            if variable in environment:
                values[field] = environment[variable]
        return AlpacaCredentials.model_validate(values)
    except ValidationError:
        raise ConfigurationError(
            "Invalid secrets fields or types; use the schema in config/secrets.example.toml."
        ) from None


def project_roots(config_file: Path) -> set[Path]:
    """Protect both a config's project and the installed/editable package's source tree."""
    roots = set()
    for location in (config_file, Path(__file__).resolve()):
        for parent in location.parents:
            if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
                roots.add(parent.resolve())
                break
    return roots


def resolve_paths(settings: Settings, config_file: Path) -> dict[str, Path]:
    config_file = config_file.resolve()
    roots = project_roots(config_file)
    resolved: dict[str, Path] = {}
    for name, value in settings.paths.model_dump().items():
        if not value.strip() or any(ord(char) < 32 for char in value) or "://" in value:
            raise ConfigurationError(f"paths.{name} must be a nonempty local directory path.")
        try:
            path = Path(value).expanduser()
            path = (config_file.parent / path).resolve()
            for root in roots:
                if root.is_relative_to(path) or (
                    path.is_relative_to(root) and not path.is_relative_to(root / "var")
                ):
                    raise ConfigurationError(
                        f"paths.{name} must be under project var/ or outside the project tree."
                    )
            parent = path
            while not parent.exists():
                parent = parent.parent
            if not parent.is_dir():
                raise ConfigurationError(f"paths.{name} or its parent is an existing file.")
        except ConfigurationError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise ConfigurationError(f"Cannot resolve paths.{name}; check its path.") from None
        for other_name, other_path in resolved.items():
            if path.is_relative_to(other_path) or other_path.is_relative_to(path):
                raise ConfigurationError(f"paths.{name} and paths.{other_name} must not overlap.")
        resolved[name] = path
    return resolved


def inspect_directory(path: Path) -> dict:
    parent = path
    while not parent.exists():
        parent = parent.parent
    writable = os.access(parent, os.W_OK | os.X_OK)
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "ready": writable,
        "detail": (
            "Directory is accessible."
            if path.is_dir()
            else "Can create under an accessible parent."
        )
        if writable
        else "Directory or nearest existing parent requires write and search permission.",
    }
