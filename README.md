# BuffetBot

BuffetBot is a local application being built for trading research, numerical machine learning, macro document analysis, and eventual paper operation.

**Start with the [North Star](NORTHSTAR.md).** It defines the reviewed product direction, technical stack, architecture, MVP scope, operating boundaries, and completion criteria.

The [development backlog](docs/development/README.md) contains 24 MVP stories. The initial Python package, typed configuration, local doctor command, redacted logging, and configuration tests are implemented in BB-001. Trading, backtesting, data ingestion, model inference, and the browser dashboard are later stories and are not implemented yet.

[BB-001 verification evidence](docs/development/evidence/BB-001.md) records the clean-environment installation and passing checks.

## Setup

Use Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/) on Linux. Run these commands from the repository root:

```bash
uv sync --locked
uv run --locked buffetbot doctor
```

The environment is isolated in `.venv`; system Python packages are not modified. Runtime/dev dependencies are recorded in `uv.lock`, and the build backend version is pinned in `pyproject.toml`. The first setup needs access to package downloads; after provisioning, the doctor needs no network, account, or model. `uv` was installed at `/home/jack/.local/bin/uv` on the current development machine. If it is not on your shell's PATH, use that absolute path or add your local binary directory to PATH.

## Available commands

```bash
uv run --locked buffetbot --version
uv run --locked buffetbot doctor --help
uv run --locked buffetbot doctor --json
uv run --locked buffetbot doctor --config config/paper.toml
uv run --locked buffetbot doctor --config config/paper.toml --require-broker
```

`doctor` resolves and inspects configuration and storage paths, reports missing credential fields, and emits logs with UTC timestamps, component, and run identity. It does not create runtime directories, authenticate with a broker, place orders, download data, or start models. A `ready` result means local configuration checks passed; it does not certify credentials or trading readiness.

Paper configuration can be inspected without credentials. `--require-broker` makes the presence of both local paper credential fields mandatory and requires paper mode. The last command above exits with status 1 until those fields are configured; it still does not connect to a broker.

| Exit code | Meaning |
| --- | --- |
| 0 | Requested local checks passed; optional integrations may be unconfigured |
| 1 | Requested local prerequisites are missing, such as credentials or directory permissions |
| 2 | Invalid command/configuration, unreadable file, unsafe path, or unsupported live mode/endpoint |

JSON reports go to stdout; redacted diagnostic logs go to stderr.

## Configuration and credentials

The default file is [config/offline.toml](config/offline.toml). Supported TOML fields are:

| Field | Default | Meaning |
| --- | --- | --- |
| `mode` | `offline` | `offline` or `paper`; all other values are rejected |
| `paths.state` | `../var/state` | Future operational state |
| `paths.data` | `../var/data` | Future downloaded datasets |
| `paths.artifacts` | `../var/artifacts` | Future experiment/model artifacts |
| `broker.endpoint` | `https://paper-api.alpaca.markets` | Only this exact paper endpoint is accepted |

Paths resolve relative to the selected configuration file, including when invoked from another working directory. `~` expansion is supported; shell environment interpolation is not. Runtime paths must not overlap each other, contain an existing file in place of a directory, or resolve into source/configuration files through a symlink. Inside a detected project, they belong under `var/`; external directories are also supported. Missing directories are allowed when their nearest existing parent is writable/searchable. These permission checks describe the current filesystem; later writes must still handle failures.

To supply credentials locally, copy [config/secrets.example.toml](config/secrets.example.toml) to `config/secrets.local.toml` if that private file does not already exist. Replace its blank placeholders in your editor, then explicitly select it:

```bash
uv run --locked buffetbot doctor --config config/paper.toml --secrets config/secrets.local.toml --require-broker
```

Alternatively, use `BUFFETBOT_ALPACA_API_KEY` and `BUFFETBOT_ALPACA_API_SECRET` in the process environment. Each environment field overrides the corresponding field from the selected secrets file; an empty/whitespace value counts as missing. No `.env` or secrets file is loaded implicitly. Unknown fields are rejected, and credentials do not belong in the public configuration or command-line arguments.

Private `*.local.toml` files, `.env` files, virtual environments, runtime directories, logs, database files, and model/data artifacts are ignored by Git. Known credential values and recognized secret fields are redacted from normal application logs and configuration/error output. Keep real credentials out of source files, examples, and chat.

## Development checks

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

The tests exercise offline/paper credential boundaries, rejected live configuration, invalid and overlapping paths, symlink protection, secret-safe errors/logging, and the doctor's lack of network access. They use temporary files and dummy secrets; no broker account or model is required.

The project has one package in `src/buffetbot`, example files in `config`, tests in `tests`, and ignored runtime locations described in [var/README.md](var/README.md). No trading-engine or model libraries have been added for later stories.

Supporting documents:

- [MVP technical design](docs/mvp-technical-design.md): module contracts, local model setup, and engineering detail.
- [Build proposal and wargame](docs/build-proposal.md): research, failure scenarios, and earlier alternatives.
