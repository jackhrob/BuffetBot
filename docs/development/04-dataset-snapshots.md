# BB-004 — Dataset snapshots, quality checks, and offline fixtures

**Status:** Not started  
**Depends on:** [BB-003](03-contracts-and-experiments.md)  
**North Star:** Data and research integrity; offline demonstration

## User outcome

As a researcher, I can inspect the exact data used by an experiment and run the offline demonstration without an account or network connection.

## Scope and simplest approach

Store immutable datasets in Parquet with a small manifest and use DuckDB for local inspection. Keep original records and derived views identifiable. Implement a few reusable quality checks and small fixtures with independently calculated outcomes.

## Acceptance criteria

1. Publish a dataset only after files and a manifest are complete and validated. A crash during writing cannot expose a partial snapshot as usable; a later import creates a new version instead of overwriting one referenced by a run.
2. The manifest records schema, provider/fixture origin, feed, universe, interval, coverage, retrieval and availability conventions, adjustment policy, corporate actions, checksum, and quality findings.
3. Validate ordered unique observations, OHLC consistency, finite/valid prices, nonnegative volume, known sessions, listing/warmup coverage, missing records, and timezone conventions. Zero volume is handled by policy rather than universally rejected.
4. Distinguish expected market closures from unexplained gaps using one selected calendar source. Do not forward-fill missing bars into tradable observations or manufacture pre-listing history.
5. Maintain executable raw prices and explicitly derived research views. Store split/dividend events with timing needed for later quantity/cash accounting. Reject data combinations that cannot support the declared experiment.
6. Provide small synthetic fixtures covering ordinary sessions, warmup, a holiday/shortened session, a missing bar, split, dividend, and a gap. Document expected ledgers for the accounting fixtures outside the implementation logic.
7. Offline fixtures and every resulting report carry a synthetic designation. A normal production-data report cannot silently inherit this designation's absence.
8. Reading a snapshot verifies its manifest/checksums and rejects missing, corrupted, or unsupported files with a recoverable error.

## Verification

- Publish, reload, and compare a fixture snapshot; interrupt publication and verify it is unavailable for execution.
- Check duplicate records, wrong sessions, changed file contents, and missing action data.
- Query coverage and quality findings through the same read path used by later reports.

## Completion evidence

Retain fixtures, expected accounting notes, publication/read commands, and quality report examples. Do not count these synthetic files as validated market history.

## Handoff and limits

BB-005 fills this storage path from an actual provider. Use local files and manifests rather than a data lake service, distributed catalog, or custom file format.
