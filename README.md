# BuffetBot

BuffetBot is a local application being built for trading research, numerical machine learning, macro document analysis, and eventual paper operation.

**Start with the [North Star](NORTHSTAR.md).** It defines the reviewed product direction, technical stack, architecture, MVP scope, operating boundaries, and completion criteria.

The [development backlog](docs/development/README.md) contains 24 MVP stories. BB-001 implements the initial Python package, typed configuration, local doctor command, redacted logging, and configuration tests. BB-002 qualifies Lumibot using synthetic offline backtests and local broker transport tests. BB-003 implements shared data/strategy contracts and reproducible experiment specifications. BB-004 adds immutable Parquet snapshots, calendar/quality validation, DuckDB inspection and packaged offline fixtures. BB-005 implements historical import/cache/replay with passing synthetic tests; actual provider verification awaits credentials. Production strategies, model workflows, the broker connection, and browser dashboard remain later work.

[BB-001 verification evidence](docs/development/evidence/BB-001.md) records the clean-environment installation and passing checks.

[BB-002 engine decision](docs/development/evidence/BB-002-engine-decision.md) adopts Lumibot 4.5.91 with demonstrated corrections for feature timing, dividend payments and partial-order restart import. It records the dependency/license findings and unrun actual paper checks.

[BB-003 evidence](docs/development/evidence/BB-003.md) records validated units, data availability, source evidence, pending exposure, immutable specifications and separate run identities. The [contract guide](docs/contracts.md) documents the v1 interfaces and limits.

[BB-004 evidence](docs/development/evidence/BB-004.md) records snapshot publication/reload, crash and corruption checks, explicit synthetic provenance and a fresh installed-package demonstration. The [dataset guide](docs/datasets.md) explains storage, quality policies and the independent accounting fixtures.

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
uv run --locked --offline buffetbot datasets fixture
uv run --locked --offline buffetbot datasets inspect <dataset_id>
uv run --locked buffetbot datasets ingest --request config/history-spy.json --secrets config/secrets.local.toml
uv run --locked --offline buffetbot datasets ingest --request config/history-spy.json --cache-only
uv run --locked --offline buffetbot datasets replay <capture_id>
```

`datasets fixture` publishes a synthetic dataset under the configured data directory and prints its ID, coverage and quality report. Replace `<dataset_id>` with that ID to verify and inspect it. Dataset commands always emit JSON; exit 1 means quality rejection, and exit 2 means invalid input/configuration or storage. See the [dataset guide](docs/datasets.md) for missing-bar, gap, zero-volume and incomplete-action cases.

`datasets ingest` reuses verified cached history or makes an explicit read-only Alpaca download; `--refresh` requests a new complete version. It returns exit 1 for blocked access or rejected data. `--cache-only` prohibits the connection. uv's `--offline` only controls dependency resolution. `datasets replay` rebuilds a snapshot from its retained original responses without network access. The [market-data guide](docs/market-data.md) explains source/feed/availability limitations and the pending real-provider check ([BB-005 evidence](docs/development/evidence/BB-005.md)).

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
| `paths.data` | `../var/data` | Immutable snapshots, original market-response captures and import-cache receipts |
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
uv run --locked ruff check src tests qualification examples/contracts/validate.py
uv run --locked ruff format --check src tests qualification examples/contracts/validate.py
uv run --locked pytest -q
```

The foundation tests exercise offline/paper credential boundaries, rejected live configuration, invalid and overlapping paths, symlink protection, secret-safe errors/logging, and the doctor's lack of network access. They use temporary files and dummy secrets; no broker account or model is required. The engine regression is skipped unless its optional dependencies are installed.

The contract tests check temporal eligibility, exact money/share units, model/source references, target/exposure consistency, version rejection and stable experiment hashes. Run the standalone synthetic example with the foundation dependencies:

```bash
uv run --locked --offline python examples/contracts/validate.py
```

The example validates an observation/context/target/audit flow and prints two different run IDs for the same specification. It contacts no services and submits no orders; example model/dataset references are illustrative rather than published artifacts.

## Engine qualification

Install the optional qualification group and run the supplied-data experiments from the repository root:

```bash
uv sync --locked --group qualification
uv run --locked --offline --group qualification python -m qualification
uv run --locked --offline --group qualification pytest -q
```

The command writes `var/qualification/report.json`. It compares repeat ledgers, costs, splits, dividend entitlement/payment, completed observations, saved-model predictions, and the Alpaca software path with synthetic responses. It uses a temporary process with no inherited credentials or dotenv loading and denies Python networking. No account is contacted. A failed invariant exits nonzero; run without Python's `-O` option. Detailed results and limitations are in [BB-002 evidence](docs/development/evidence/BB-002.md).

The group includes Lumibot's substantial upstream dependencies and a small scikit-learn artifact probe. Plain `uv sync --locked` returns to the default application environment, including local data storage. Always include `--group qualification` when running engine checks so uv retains those dependencies.

The snapshot tests cover publication/reimport, concurrent publishers, abrupt process exits, corrupt files, missing/session/listing/action data, explicit zero-volume handling, research cutoffs, and an offline CLI round trip.

The ingestion tests add pagination, precise minute aggregation, source/capture binding, refresh/replay, interrupted imports, corrupt caches, unsupported actions, bounded HTTP retries, fixed GET endpoints and credential redaction. Run `uv run --locked --offline python examples/ingestion/validate.py` for the synthetic import demonstration. It does not verify provider entitlement or real prices.

The application package remains in `src/buffetbot`, with packaged offline datasets and independent ledger expectations in `src/buffetbot/fixtures`. Disposable engine experiments and their original fixtures live in `qualification`. Configuration examples are in `config`, regressions in `tests`, and ignored runtime locations are described in [var/README.md](var/README.md).

Supporting documents:

- [MVP technical design](docs/mvp-technical-design.md): module contracts, local model setup, and engineering detail.
- [Build proposal and wargame](docs/build-proposal.md): research, failure scenarios, and earlier alternatives.
