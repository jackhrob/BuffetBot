# Historical market-data ingestion

BB-005 implements the Alpaca import, source-response cache and offline replay path. **Actual provider verification is blocked until Alpaca credentials and the required endpoint/feed access are available.** Synthetic tests do not establish real-data coverage, entitlement or provider correctness.

## Run a small import

From the repository root:

```bash
uv run --locked buffetbot datasets ingest \
  --request config/history-spy.json \
  --secrets config/secrets.local.toml
```

Use the existing ignored secrets-file convention in [the setup guide](../README.md#configuration-and-credentials). The environment variables `BUFFETBOT_ALPACA_API_KEY` and `BUFFETBOT_ALPACA_API_SECRET` can supply or override the two fields instead. Secrets files are loaded only when explicitly selected. Keep credentials out of the request JSON and source control.

The checked-in [request](../config/history-spy.json) selects SPY, July 1–9, 2024, one prior warmup session, SIP, raw prices, daily output and regular-session minute aggregation. The synthetic fixtures are separate. SPY's listing date is January 29, 1993, according to the [listing exchange's anniversary record](https://ir.theice.com/press/news-details/2013/NYSE-Euronext-Celebrates-20-Years-of-Exchange-Traded-Product-ETP-Listing-and-Trading/default.aspx). This is a small ingestion sample, not a strategy or investment recommendation.

A successful command prints the normal verified snapshot/quality report plus an `ingestion` receipt containing the request, capture and dataset IDs, origin, adapter version and cache-hit flag. Logs go to stderr. Exit 0 means verified; exit 1 means a blocked prerequisite/provider request or rejected import, with a stable error code; exit 2 means invalid configuration/request or snapshot storage.

Repeat the same request to reuse a verified cache entry without downloading again. To require local reuse or explicitly download a new version:

```bash
uv run --locked --offline buffetbot datasets ingest \
  --request config/history-spy.json --cache-only

uv run --locked buffetbot datasets ingest \
  --request config/history-spy.json \
  --secrets config/secrets.local.toml --refresh

uv run --locked --offline buffetbot datasets inspect <dataset_id>
uv run --locked --offline buffetbot datasets replay <capture_id>
```

All operations accept `--config path/to/config.toml` for the existing storage paths. `--refresh` and `--cache-only` are mutually exclusive. **uv's `--offline` controls package resolution only; use `--cache-only` to prohibit an ingestion connection.** Inspection and capture replay are always local. A cache hit needs no credentials; explicitly selecting a missing or malformed secrets file still reports that configuration error.

## Request and price conventions

`HistoricalRequest` requires a declared universe with listing metadata, inclusive start/end dates, first execution date/warmup, `interval: 1d`, `feed: sip|iex`, `adjustment: raw`, `aggregation: regular_session_from_1min` and a zero-volume policy. There is no automatic feed selection. This first adapter bounds an import to five ETFs, 366 calendar days, dates from 2016 onward, and 2,000 response pages; it does not assert that the provider covers every allowed request. Larger research histories can be acquired in separate snapshots. No screening or historical index-membership reconstruction is performed.

For each exchange session, the adapter requests `1Min` source bars at timestamps in **[scheduled open, scheduled close)** with `asof=-`, explicit USD, ascending order and the selected feed. Symbol remapping is disabled. It follows every pagination token even when a page is shorter than the requested limit. Duplicate/nonadvancing pages, repeated tokens, overlapping/unordered records, malformed JSON, foreign symbols, timestamps outside the requested session and incomplete minute coverage are rejected. Empty or truncated results never become successful snapshots. The [historical bars API](https://docs.alpaca.markets/us/reference/stockbars) documents these parameters and pagination across symbols.

The output open/close are the first minute's open and last minute's close, high/low are extrema over supplied minutes, and volume is their exact sum. Prices are parsed as decimals directly from JSON; they never pass through a binary float. A regular day requires 390 supplied minutes and the July 3 shortened session requires 210. Missing minutes can reflect thin trading or absent data; this MVP rejects both rather than inventing trades or zero-volume bars. This conservative requirement can make some IEX histories unusable.

**These are explicitly derived daily bars, not Alpaca's `1Day` bars or official auction prices.** Alpaca applies different trade-condition rules to minute and daily aggregates; daily volume can include extended-hours trades. [Aggregation rules](https://docs.alpaca.markets/us/docs/market-data-faq). A trade timestamped exactly at the scheduled close lies outside this adapter's final complete minute. Closing-auction prints at that boundary are excluded, and the last minute's close need not equal the official close. `regular_minutes_aggregation` and `closing_boundary_auction_excluded` remain attached to the dataset and experiment reference. The original minute responses are retained for inspection. Comparing this series to vendor daily bars requires acknowledging those differences.

SIP represents consolidated US-exchange data; IEX represents a single exchange. Alpaca's FAQ documents historical SIP requests with an end at least 15 minutes old and subscription-dependent access to recent data. Actual account access still needs a successful read. The adapter requests completed sessions at least 15 minutes old and never substitutes IEX after a SIP rejection. IEX snapshots carry `single_exchange_iex`, and feed/origin are part of the cache identity. [Feed and access documentation](https://docs.alpaca.markets/us/docs/market-data-faq).

## Corporate actions and historical limitations

The adapter calls `https://data.alpaca.markets/v1/corporate-actions` for all action types, `region=us` and `data_quality=all`. It scans available process dates from 1970 through the request date and selects economic ex/effective dates locally. The broader scan matters because the endpoint filters by **process date**, which can lie outside the bar range for an action inside it. Selecting only supported types or the bar dates would silently hide relevant events. The [corporate-actions reference](https://docs.alpaca.markets/us/reference/corporateactions-1) documents the date filter, pagination, incomplete-record handling and uncertain publication timing.

Supported events are whole-number forward splits and regular domestic cash dividends with explicit ex-date, pay date and amount. Missing dates, nonintegral/reverse splits, special or foreign dividends, due bills and other relevant action types block publication. Pay dates beyond the snapshot end are preserved for later receivable accounting. Corporate-action IDs are deduplicated across pages. Missing action entitlement or unsupported records leave the dataset unusable; the importer does not invent a supplementary source or assume an empty response after a failed request.

After a complete successful response scan, the snapshot's action completeness statement is explicitly **relative to the provider response**. It is not independently authenticated completeness. The `provider_action_completeness_unverified` limitation is retained. Real verification must establish endpoint access and compare records to their source before this story can pass; if Alpaca cannot support the required convention, the affected dataset remains unsupported until a documented supplementary source is implemented.

Historical bars and actions are not vintage-aware records. This adapter uses explicit retrospective modeling assumptions: a completed bar becomes eligible at close plus 15 minutes, and a split/dividend is known at its ex/effective-session open. Those are not observed announcement timestamps. Actual page-receipt timestamps become first ingestion times for these captured records. `unknown_revision_timing`, `historical_availability_assumed` and `historical_action_timing_assumed` are retained on every reference. Historical corrections can contain hindsight; these datasets support **historical exploratory** work, not a claim that their exact content was available then. Existing paper/shadow context checks still require actual ingestion by the decision time. Prospective capture is later work.

## Cache, refresh and recovery

```text
<paths.data>/market-captures/<capture_id>.json  # immutable original response capture
<paths.data>/market-imports/<request_id>.json  # replaceable successful-import receipt
<paths.data>/snapshots/<dataset_id>/          # existing immutable BB-004 Parquet snapshot
```

A capture contains the versioned request, origin, start/completion times, exact successful response bodies, per-page receipt time/request ID, endpoint path and query parameters. It contains no authentication headers, provider error bodies or secrets. SHA-256 of its canonical bytes is its identity. The snapshot manifest names this capture hash in its existing retrieval convention; no BB-004 snapshot schema or existing identity changes.

Captures are written with a temporary file, fsync and a publication operation that cannot overwrite an existing identity. The adapter replays and verifies complete query/page chains before normalizing and invoking the BB-004 publisher. Only a verified snapshot permits atomic publication of the request's successful receipt. Source captures that fail normalization/quality remain available for investigation and offline replay, with their ID in the error report. A download interrupted before all pages arrive publishes no capture, snapshot or success receipt; retry starts a complete read.

A cached read verifies the receipt schema, exact request/origin, capture checksum and snapshot checksum/quality/provenance. A corrupt cache fails explicitly instead of silently downloading replacement data. An explicit refresh downloads the selected range again and publishes a complete new version, preserving previous snapshots and captures. Extending a range is a new request. This intentionally avoids an in-place incremental merge and a partially updated dataset; per-row incremental-fetch optimization is not implemented. A failed refresh leaves the previous successful receipt intact.

If a process stops after snapshot publication but before the receipt update, the old receipt stays valid (or no receipt exists), and the completed capture can be replayed offline. There is no claim of a durable job state machine; BB-006 owns that work. Abandoned `.staging-*` files are never valid capture IDs and may be removed manually when no import is active.

The transport uses Python's standard HTTPS client, a fixed data host and two allowed GET paths. It does not import a broker SDK or contact account/order endpoints, and it follows no redirects. Each client spaces requests by at least 0.35 seconds. It retries timeouts, truncated HTTP bodies, rate limits and selected server failures at most three times, honoring `Retry-After` and rate-reset hints. A provider wait beyond 30 seconds causes an actionable stop rather than an early retry. Authentication, entitlement and parameter errors are not retried; error bodies and raw transport exception text are never logged. Each request has a 20-second timeout and a 4 MB response cap. These bounds keep a failed read finite; simultaneous clients still share provider account limits.

## Offline demonstration and verification

```bash
uv run --locked --offline python examples/ingestion/validate.py
uv run --locked --offline --group qualification pytest -q
```

The example disables Python socket/DNS access and exercises synthetic pagination, Parquet publication, cache reuse, changed-record refresh and original-capture replay in a temporary directory. It reports explicit synthetic origin. [Fixture source](../src/buffetbot/fixtures/alpaca.py), [authored source bars](../src/buffetbot/fixtures/alpaca-bars.csv), and [action responses](../src/buffetbot/fixtures/alpaca-actions.json) are packaged with the app. The fabricated process dates intentionally straddle the requested interval to test date filtering.

[BB-005 evidence](development/evidence/BB-005.md) records actual local results and the outstanding real-provider gate. No dependency versions, broker permissions, trading policies or model workflows change in this story.
