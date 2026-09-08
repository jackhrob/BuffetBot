"""Local tooling and explicit historical data imports; no trading operations."""

import argparse
import json
import logging
import os
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from buffetbot.config import (
    CREDENTIAL_ENV,
    ConfigurationError,
    inspect_directory,
    load_credentials,
    load_settings,
    resolve_paths,
)
from buffetbot.logging import Redactor, configure_logging

logger = logging.getLogger("buffetbot.doctor")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes invalid arguments, which could contain pasted credentials.
        self.exit(2, "Invalid command line. Run 'buffetbot --help' for supported options.\n")


def parser() -> argparse.ArgumentParser:
    command = Parser(description="BuffetBot local research tooling.")
    command.add_argument("--version", action="version", version=f"BuffetBot {version('buffetbot')}")
    subcommands = command.add_subparsers(dest="command", required=True, parser_class=Parser)
    doctor = subcommands.add_parser(
        "doctor", help="Inspect local configuration without network calls."
    )
    doctor.add_argument("--config", type=Path, default=Path("config/offline.toml"))
    doctor.add_argument(
        "--secrets", type=Path, help="Explicit local secrets TOML; never loaded implicitly."
    )
    doctor.add_argument(
        "--require-broker",
        action="store_true",
        help="Require locally configured paper credentials.",
    )
    doctor.add_argument(
        "--json", action="store_true", help="Write a machine-readable report to stdout."
    )
    datasets = subcommands.add_parser(
        "datasets", help="Publish, import or inspect datasets (JSON)."
    )
    operations = datasets.add_subparsers(dest="dataset_command", required=True, parser_class=Parser)
    fixture = operations.add_parser(
        "fixture", help="Publish the packaged synthetic offline fixture."
    )
    fixture.add_argument(
        "--case",
        choices=("accounting", "missing_bar", "gap", "zero_volume", "incomplete_actions"),
        default="accounting",
    )
    inspect = operations.add_parser(
        "inspect", help="Verify a snapshot and report its coverage/quality."
    )
    inspect.add_argument("dataset_id")
    ingest = operations.add_parser(
        "ingest", help="Import Alpaca history or reuse its verified cache (JSON)."
    )
    ingest.add_argument(
        "--request", type=Path, required=True, help="Explicit historical request JSON."
    )
    ingest.add_argument("--secrets", type=Path, help="Explicit local Alpaca secrets TOML.")
    caching = ingest.add_mutually_exclusive_group()
    caching.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch a new complete version; preserve previous snapshots.",
    )
    caching.add_argument(
        "--cache-only", action="store_true", help="Require a verified cached result; never connect."
    )
    replay = operations.add_parser(
        "replay", help="Publish a retained original response capture without network access."
    )
    replay.add_argument("capture_id")
    for operation in (fixture, inspect, ingest, replay):
        operation.add_argument("--config", type=Path, default=Path("config/offline.toml"))
    jobs = subcommands.add_parser(
        "jobs", help="Submit and inspect durable local research jobs (JSON)."
    )
    job_operations = jobs.add_subparsers(dest="jobs_command", required=True, parser_class=Parser)
    submit = job_operations.add_parser("submit", help="Persist one validated research job request.")
    submit.add_argument("--request", type=Path, required=True)
    show = job_operations.add_parser("show", help="Show one durable job and its event history.")
    show.add_argument("request_id")
    listing = job_operations.add_parser("list", help="List recent jobs.")
    listing.add_argument("--limit", type=int, default=20)
    cancel = job_operations.add_parser(
        "cancel", help="Cancel queued work or request active cancellation."
    )
    cancel.add_argument("request_id")
    worker = subcommands.add_parser(
        "worker", help="Run or inspect the single local research worker (JSON)."
    )
    worker_operations = worker.add_subparsers(
        dest="worker_command", required=True, parser_class=Parser
    )
    worker_operations.add_parser("status", help="Show durable work and shutdown state.")
    worker_operations.add_parser("once", help="Claim and run at most one research job.")
    serve = worker_operations.add_parser(
        "serve", help="Run until stopped or shutdown is requested."
    )
    serve.add_argument("--poll-seconds", type=float, default=0.25)
    worker_operations.add_parser("shutdown", help="Persist a request to stop starting new jobs.")
    worker_operations.add_parser("resume", help="Clear a persisted shutdown request explicitly.")
    for operation in (submit, show, listing, cancel, *worker_operations.choices.values()):
        operation.add_argument("--config", type=Path, default=Path("config/offline.toml"))
    return command


def emit(report: dict, *, as_json: bool, redactor: Redactor) -> None:
    if as_json:
        # Redact string values before encoding, so escaped secret text cannot leak in JSON.
        def clean(value):
            if isinstance(value, str):
                return redactor(value)
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value

        print(json.dumps(clean(report), indent=2))
        return
    if "error" in report:
        print(redactor(f"Configuration invalid: {report['error']}"))
        return
    lines = [
        f"Configuration: {report['status']} (local checks only)",
        f"Mode: {report['mode']}",
        f"Config file: {report['config_file']}",
        f"Python: {report['python']}",
        "Required integrations: " + (", ".join(report["required_integrations"]) or "none"),
    ]
    for name, check in report["paths"].items():
        lines.append(f"{name}: {check['path']} — {check['detail']}")
    broker = report["broker"]
    lines.append(f"Paper broker credentials: {broker['credentials']}")
    if broker["missing_fields"]:
        lines.append("Missing credential fields: " + ", ".join(broker["missing_fields"]))
    lines.append(
        "Broker connectivity: not checked. Trading, data downloads, and models are not run."
    )
    print(redactor("\n".join(lines)))


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    run_id = uuid4().hex
    known_secrets = [os.environ.get(name, "") for name in CREDENTIAL_ENV.values()]
    redactor = Redactor(known_secrets)
    configure_logging(redactor, run_id)
    if arguments.command == "datasets":
        # Keep heavy storage dependencies and filesystem writes out of the doctor path.
        from buffetbot.datasets_cli import run

        credentials = None
        if arguments.dataset_command == "ingest":
            try:
                credentials = load_credentials(arguments.secrets)
            except ConfigurationError as error:
                emit(
                    {"status": "invalid", "origin": "unverified", "error": str(error)},
                    as_json=True,
                    redactor=redactor,
                )
                return 2
            redactor = Redactor([*known_secrets, *credentials.secret_values()])
            configure_logging(redactor, run_id)
        report, status = run(arguments, credentials=credentials)
        emit(report, as_json=True, redactor=redactor)
        logging.getLogger("buffetbot.datasets").info(
            "Dataset operation completed: %s", report["status"]
        )
        return status
    if arguments.command in ("jobs", "worker"):
        # Job children receive an allowlisted environment; this boundary never loads secrets.
        from buffetbot.jobs_cli import run

        report, status = run(arguments)
        emit(report, as_json=True, redactor=redactor)
        logging.getLogger("buffetbot.jobs").info("Job command completed: %s", report["status"])
        return status
    try:
        credentials = load_credentials(arguments.secrets)
        redactor = Redactor([*known_secrets, *credentials.secret_values()])
        configure_logging(redactor, run_id)
        settings = load_settings(arguments.config)
        if arguments.require_broker and settings.mode != "paper":
            raise ConfigurationError(
                "Select a paper configuration before requiring broker credentials."
            )
        paths = resolve_paths(settings, arguments.config)
        checks = {name: inspect_directory(path) for name, path in paths.items()}
        missing = credentials.missing_fields()
        ready = all(check["ready"] for check in checks.values()) and not (
            arguments.require_broker and missing
        )
        report = {
            "status": "ready" if ready else "prerequisites_missing",
            "scope": "local_configuration_only",
            "run_id": run_id,
            "mode": settings.mode,
            "config_file": str(arguments.config.resolve()),
            "python": platform.python_version(),
            "paths": checks,
            "required_integrations": ["paper_broker"] if arguments.require_broker else [],
            "broker": {
                "endpoint": settings.broker.endpoint,
                "credentials": "configured" if not missing else "missing",
                "missing_fields": missing,
                "connectivity": "not_checked",
            },
        }
        emit(report, as_json=arguments.json, redactor=redactor)
        logger.info("Local configuration inspection completed: %s", report["status"])
        return 0 if ready else 1
    except ConfigurationError as error:
        emit({"status": "invalid", "error": str(error)}, as_json=arguments.json, redactor=redactor)
        logger.error("Configuration inspection failed: %s", error)
        return 2
    except (OSError, RuntimeError, ValueError):
        message = "Cannot inspect local paths; check the configuration and filesystem permissions."
        emit({"status": "invalid", "error": message}, as_json=arguments.json, redactor=redactor)
        logger.error(message)
        return 2


if __name__ == "__main__":
    sys.exit(main())
