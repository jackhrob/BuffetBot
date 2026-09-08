# Local market snapshots

BB-004 implements immutable daily market snapshots, quality checks, local inspection and packaged synthetic fixtures. Actual provider ingestion belongs to BB-005; application backtests and accounting belong to BB-009.

## Offline commands

From the repository root, after `uv sync --locked`:

```bash
uv run --locked --offline buffetbot datasets fixture
uv run --locked --offline buffetbot datasets inspect <dataset_id>
uv run --locked --offline buffetbot datasets fixture --case missing_bar
uv run --locked --offline buffetbot datasets fixture --case gap
uv run --locked --offline buffetbot datasets fixture --case zero_volume
uv run --locked --offline buffetbot datasets fixture --case incomplete_actions
```

Use the 64-character `dataset_id` printed by the first command. Both operations support `--config path/to/config.toml`; storage resolves through the existing configured `paths.data`, relative to that configuration file. Output is JSON, with logs on stderr. Exit 0 means verified, 1 means quality rejected, and 2 means invalid configuration/input or unreadable/corrupt/unsupported storage. Quality rejection includes the report and publishes no snapshot. Unverified read errors explicitly carry `origin: unverified`.

The commands do not load credentials or contact a provider, broker or model service. Fixtures are packaged with the installed application, so they also work outside a source checkout. Initial installation needs the locked packages available locally or from PyPI. `--offline` here instructs uv to use its cache; the commands themselves only perform local operations.

## Storage and identity

```text
<paths.data>/snapshots/<dataset_id>/
    manifest.json
    bars.parquet
    actions.parquet
    sessions.parquet
```

Source prices/actions and the selected exchange schedule are ordinary Parquet tables. The JSON manifest declares storage/record versions, origin, provider/feed, universe/listings, interval, requested coverage, first execution/warmup, retrieval and availability conventions, revision limitations, raw/research adjustment policies, action completeness/source, zero-volume policy, selected calendar version, file sizes/hashes/counts and the complete quality report. Actual per-symbol coverage comes from the saved records.

The dataset ID is SHA-256 of the canonical manifest bytes. The manifest hashes every Parquet file. Source `MarketBar` rows omit the derived `dataset_id`; `Snapshot.observations()` supplies it after verification to create the existing `MarketObservation` contract. This avoids a circular hash without weakening file verification. The price columns use exact `decimal128(24,8)`, volume is unsigned 64-bit, dates are session dates, and timestamps are UTC microseconds. V1 forward split ratios fit signed 64-bit integers. Unsupported units, precision or versions fail rather than being coerced.

Publication validates source records and quality, creates a private `.staging-*` directory on the same filesystem, writes and fsyncs the complete files/manifest, reads them through the verifier, then atomically renames the directory. It fsyncs the parent after rename. A process crash can leave staging files, but no reader accepts a staging name as a dataset ID. After an interrupted write, retry the import. When no publisher is active, abandoned staging directories may be removed manually. There is no background cleanup or retention daemon.

The same exact records and provenance reuse an existing verified identity. Changed records, retrieval metadata or source conventions produce a different version. Concurrent identical publishers converge on the same verified snapshot. Existing snapshots are never overwritten or repaired in place. Byte-level identity is tied to the declared Parquet writer; a future serialization change can produce a new version even for equivalent logical rows.

Readers verify the canonical manifest and all required files, reject extra/missing/symlinked members, check schemas/counts, revalidate typed records and recompute quality against the pinned calendar. They hash and decode the same in-memory bytes. DuckDB queries those verified rows, so it cannot reopen a changed file after verification. Corruption raises `SnapshotError`; restore the original files or publish a corrected new input. Checksums detect changes relative to an experiment's recorded ID; they do not authenticate a data vendor's claims or turn editable local storage into a security boundary.

## Quality and availability

The single calendar source is `pandas_market_calendars` 5.4.0, NYSE, recorded as XNYS on instruments. The saved schedule retains actual opens and closes, including shortened sessions. [Calendar usage](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html) documents the selected schedule API. Reprovision with the pinned environment to read these v1 datasets; upgrading calendar semantics requires an explicit compatibility decision.

Blocking checks cover duplicate/unordered bars and actions, invalid OHLC/price/volume units, missing listed sessions, unknown sessions, incorrect regular-session boundaries/timezones, missing warmup, pre-listing or delisted exposure, mixed origin/feed/provider, ingestion later than retrieval, incomplete action coverage and unsupported actions. The coverage report distinguishes weekends/holidays from missing bars. Missing observations are never forward-filled. The requested range may include expected closures but must contain enough prior exchange sessions for the declared warmup.

Zero volume is an explicit `allow_with_warning` or `reject` policy. A gap of at least 20% between the previous supplied close and the current open, after a declared same-session split, is preserved with a review warning. A large gap is not evidence that a split occurred. Neither zero-volume allowance nor a passing quality report certifies tradable liquidity or vendor accuracy.

Corporate action coverage must be explicitly attested **complete over the entire requested universe and range**, even when the action table is empty. Unknown coverage blocks publication. Each action retains a revision ID, effective/ex session, availability and ingestion; dividends also require a pay date and USD amount, and forward splits require an integer ratio >=2. A pay date may extend beyond the coverage end; do not discard the receivable. The publisher cannot discover omitted events from raw OHLC alone. BB-005 must substantiate this attestation from a documented source, or leave the dataset unsupported. Provider semantics, including extended-hours daily bars, must be qualified against the declared regular-session convention.

`revision_policy: unknown` requires the `unknown_revision_timing` limitation, shown as a warning and carried into experiment references. Current revised history cannot establish a point-in-time dataset simply by supplying an earlier availability timestamp. Historical exploratory use and prospective capture remain distinct under the existing context contracts.

## Python integration

```python
from datetime import datetime
from pathlib import Path
from buffetbot.fixtures import load_fixture
from buffetbot.snapshots import (
    publish_snapshot, read_snapshot, inspect_snapshot,
    research_view, validate_snapshot_for_experiment,
)

root = Path("var/data")
snapshot = publish_snapshot(root, *load_fixture("accounting"))
snapshot = read_snapshot(root, snapshot.dataset_id)
reference = snapshot.reference()       # Exact DatasetReference for a specification.
observations = snapshot.observations() # Raw MarketObservation records with dataset ID.
report = inspect_snapshot(root, snapshot.dataset_id)
view = research_view(snapshot, cutoff=datetime.fromisoformat("2024-07-03T17:15:00+00:00"))
# After constructing a complete ExperimentSpecification:
# validate_snapshot_for_experiment(snapshot, specification)
```

`inspect_snapshot` is the shared verified read/report path for subsequent jobs and UI. It uses [DuckDB's local Python API](https://duckdb.org/docs/stable/clients/python/overview) with automatic extension installation/loading disabled. There is no persistent analytical server or catalog.

The research export is an explicitly labelled `split_as_of_cutoff` view with source ID, origin, cutoff, split IDs, limitations and exact decimal strings. It includes only bars available by the cutoff. Only splits effective at or before that cutoff can adjust older OHLC; an effective split not yet available blocks the view. Prices round to eight decimal places with half-even rounding. Raw prices remain unchanged, and no dividend adjustment or volume adjustment is implied. The cutoff must remain within the declared action coverage. This is a research view, not an engine price series or a replacement for `FeatureObservation`; BB-007 still owns feature formulas and BB-003's context checks still own prospective computation timing.

`validate_snapshot_for_experiment` requires the exact dataset reference, matching instrument/listing metadata, date coverage and enough prior listed warmup sessions. It works alongside the existing specification/context validators. Consumers must use a freshly verified snapshot, preserve the reference in their experiment and retain `origin` on every resulting report. Synthetic origin is required in both source rows and the manifest; a missing origin is rejected. [Fixture notes and independent ledger](../src/buffetbot/fixtures/README.md) describe the authored outcomes and negative cases.

This implementation intentionally covers small daily US ETF datasets in local memory. It provides no data lake, distributed catalog, provider download, general adjustment engine, trading strategy or order lifecycle.
