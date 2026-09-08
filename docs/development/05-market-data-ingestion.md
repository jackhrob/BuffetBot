# BB-005 — Historical market data ingestion

**Status:** In progress — offline implementation verified; real-provider check blocked by missing credentials. [Evidence](evidence/BB-005.md)

**Depends on:** [BB-004](04-dataset-snapshots.md)  
**North Star:** Historical data; feed consistency; reproducible research

## User outcome

As a researcher, I can obtain a small real ETF dataset, understand its limitations, and reuse it without repeatedly downloading history.

## Scope and simplest approach

Implement one Alpaca historical adapter using the provider's supported client or a small explicit HTTP client. Qualify actual endpoint behavior and entitlements during implementation. Connect the result to the snapshot publisher; do not hide downloading inside strategy calculations.

## Acceptance criteria

1. A command/job requests a declared universe, date range, interval, feed, and adjustment policy. The completed snapshot records those exact choices and actual coverage.
2. Complete pagination for all symbols. Detect partial/truncated responses, empty ranges, duplicate pages, and symbols that have insufficient history.
3. Use bounded retries/backoff for transient read failures, honoring applicable limits. Authentication and entitlement failures are actionable and do not trigger endless retries or a silent feed change.
4. Cache original responses or sufficient immutable source records. An incremental refresh produces a new snapshot; prior experiments remain tied to their original files.
5. Apply BB-004 validation and obtain the action metadata necessary for the supported split/dividend convention. If the provider cannot supply it, use one documented supplementary source or mark the affected dataset unsupported. Do not fabricate actions or ignore their accounting.
6. Explicitly distinguish historical consolidated data from any current single-exchange feed. Feature calculations and execution validation must know which they receive; no default feed selection may silently alter a run.
7. A real small download passes coverage/quality checks and is usable by the shared snapshot reader. Missing credentials or entitlements leave this external check blocked while recorded-response tests can continue.
8. Data updates are read-only with respect to the broker account, and logs never expose credentials.

## Verification

- Use recorded or synthetic paginated responses to exercise pagination, throttling, missing symbols, and interrupted downloads without repeated external requests.
- Perform one small actual provider download and compare selected fields/counts with its source response.
- Rerun with caching and verify an existing snapshot has not changed; demonstrate a revised record creates a distinct snapshot.

## Completion evidence

Record the integration version, declared feed/entitlements, redacted request metadata, snapshot hash, coverage report, and actual download result. Mark the real-provider portion incomplete if only fixtures have run.

## Handoff and limits

Keep the universe small and fixed for the MVP. Stock screening, historical index reconstruction, tick data, and additional commercial vendors are separate future work.
