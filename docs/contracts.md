# BuffetBot contracts, version 1

BB-004 adds `MarketBar`, the same normalized raw fields before assignment of a dataset ID. `MarketObservation` retains its original v1 serialized contract and now extends that source record with the verified snapshot ID. See the [dataset guide](datasets.md) for immutable storage and experiment binding; the illustrative BB-003 examples below remain independent contract demonstrations.

BB-003 implements the data boundaries needed by the reviewed MVP using the existing Pydantic dependency and the Python standard library. Domain records and the strategy protocol live in [contracts.py](../src/buffetbot/contracts.py); experiment inputs, canonical serialization, run manifests and binding checks live in [experiments.py](../src/buffetbot/experiments.py). Neither module imports a trading engine, broker SDK, dataframe library or model runtime.

## Records and responsibilities

| Record | Meaning |
| --- | --- |
| `Instrument` | Explicit US ETF symbol, USD denomination, listing interval, venue, XNYS session calendar and New York timezone. Delisting is an exclusive boundary. |
| `MarketObservation` | Completed daily **raw** OHLCV, session/open/close times, public availability, first ingestion, dataset hash, provider/feed, revision and synthetic/historical/prospective origin. |
| `FeatureObservation` | Separate ordered numerical feature values and schema identity, with source dataset/session, input availability, actual computation time and the cutoff used for split adjustment. A context requires its matching raw observation. |
| `SourceDocument` | Source URL, publication/availability/first-ingestion times, revision policy, original text and its verified SHA-256. |
| `MacroAssessment` | Current/comparison document IDs, exact evidence spans, explicit direction/concern categories, unknown/ambiguous outcomes, source cutoff, generation/expiry times, model/prompt hashes, generation parameters and raw-response hash. Historical results are explicitly exploratory. |
| `PortfolioState` | Cash, dividend receivables, raw-marked whole-share holdings, and pending buy/sell quantities and cash reservations at a declared snapshot time. |
| `StrategyContext` | Run/specification identity, eligible instruments/data/features/documents, decision/execution/expiry times, fixed strategy definition and current/pending exposure. Optional macro output is checked against its source documents. |
| `PortfolioTargets` | Fractional instrument weights, remaining cash weight, strategy/run/specification identity, cutoff, execution time, expiry and reason codes. These are allocation requests, not orders. |
| `ExecutionAuditEvent` | Local intention, client/engine/broker/native event IDs, native and normalized status, requested/cumulative/delta fill quantities, raw execution price, commission, native occurrence time and later recording time. |
| `ExperimentSpecification` | Fixed universe, dates/warmup, simulated capital, policy parameters, benchmark, execution/cost/cash/action rules, immutable dataset/model/prompt references, code revision/content hash, lock hash, engine version and seed. |
| `ExperimentManifest` | A specification plus its verified content identity, a distinct UUID4 run ID, creation time and optional output artifact hashes. Creating a manifest creates no job or files. |

Supporting records are ordinary typed values: settings, weights, holdings, pending orders, source spans, artifact references and model/dataset references. There is no plugin registry, dynamic schema discovery or configurable execution pipeline. Policy parameter names and formulas belong to BB-007; this story records their fixed values without implementing those policies.

## Strategy boundary

```python
context = validate_context(manifest, context)
targets = strategy.generate_targets(context)
targets = validate_targets(context, targets)
```

`Strategy` is a normal typing protocol for `generate_targets(context) -> PortfolioTargets`. Both binding checks return validated records. `validate_context` checks the run/specification, mode, universe, strategy, dataset provenance and macro model/prompt identities. `validate_targets` binds the returned weights and timestamps to that context and its eligible universe. At a later validation point, pass `at=aware_datetime` to reject a target at or after expiry. Execution eligibility and final risk checks still belong to BB-008/009/018; a structurally valid target does not authorize submission.

Context records contain no broker client, secret, callback, unrestricted storage handle or executable arbitrary object. Extra fields are forbidden. Records are frozen and collections are tuples of frozen records or scalar values, including settings and feature vectors. This prevents ordinary mutation of nested inputs. It is a data boundary, not a sandbox for arbitrary Python code; worker process authority and isolation remain separate responsibilities.

Use `model_validate`/`model_validate_json` to enter these boundaries. Pydantic's deliberately unvalidated `model_construct` and `model_copy(update=...)` are not validation APIs. Public binding/identity helpers revalidate instances so an unvalidated modified copy is not silently trusted. Pydantic documents its [model immutability limitations](https://docs.pydantic.dev/latest/concepts/models/#faux-immutability) and [serialization behavior](https://docs.pydantic.dev/latest/concepts/serialization/).

## Units and numerical policy

| Value | Version 1 rule |
| --- | --- |
| Prices, USD amounts, numerical features | Finite `Decimal` values, at most 24 digits and 8 fractional decimal places. Accept decimal strings, Python `Decimal`, or integers. Reject binary floats, booleans, NaN/infinities and strings containing units. JSON output uses decimal strings. |
| Allocation weights | Fractions in `[0, 1]`, with total instrument weight at most 1. `"0.5"` means 50%; `50`, `"50%"` and a float `0.5` are rejected. Empty weights mean all cash. Omitted instruments have zero target weight; the remainder stays in cash. |
| Quantities and volume | Whole shares encoded as actual nonnegative integers; holdings, remaining quantities and requested order size must be positive. Reject fractional shares, numeric strings and bools. |
| Execution cost | A nonnegative USD commission per order and combined spread/slippage in basis points (`10` bps = 0.1% per side), below 10000 bps. These are simulation assumptions. |
| Policy/generation settings | Named scalar strings, integers or booleans. Use strings for decimal settings; policy-specific parsing/allowed names are checked in the implementing story. Containers and floats are rejected. |

Validation never rounds an input into acceptance. Values exceeding supported precision fail. Accounting adapters must choose conversions explicitly instead of sending numpy floats straight into money/quantity fields. The BB-002 execution convention records the tested Lumibot 4.5.91 native cent rounding for synthetic quote fills; changing it changes the specification identity. That convention is distinct from storing an average fill price such as 55.055 after a split. These records do not calculate fills or silently round balances to cents.

`PortfolioState.equity_usd = cash + raw-marked holdings + dividend receivables`. Spendable cash is cash minus pending reservations; receivables cannot fund a buy. Pending sells cannot exceed held shares, and expected proceeds are not added to buying power. These checks catch internally inconsistent snapshots; account-wide risk limits and reconciliation are still later work. A snapshot with unknown/foreign exposure must be reconciled before a strategy context is constructed, rather than dropping that exposure to satisfy the schema.

## Time and information eligibility

Timestamps must include an offset or timezone, and are normalized to UTC. Bare dates, epoch numbers and timezone-naive times are rejected for timestamp fields. Session dates are separate ISO `YYYY-MM-DD` dates interpreted against the declared New York calendar; observation start/end and execution timestamps must agree with their session date.

The distinct times are intentional:

- `interval_start`/`interval_end`: the observed daily bar interval. Its end cannot follow public availability.
- `published_at`: the source document's publication time; `available_at` is when that specific content/version became publicly usable.
- `first_ingested_at`: when this application first acquired that observation or document. It cannot precede public availability.
- `computed_at`/`generated_at`: actual feature/model-output creation times. They are never backdated to the historical decision being studied.
- `adjusted_as_of`/`source_cutoff`: the latest information allowed when adjusting features or interpreting source documents.
- `decision_at`: the information cutoff exposed to the strategy. Availability equal to this cutoff is eligible; anything later is rejected.
- `execution_at`: a strictly later eligible execution time, using observations from earlier sessions. Exact holidays, next-session selection, DST and coverage validation require the dataset/calendar implementation in BB-004/009.
- `expires_at`: an **exclusive** boundary. A macro output or target is unusable at the exact expiry instant. Targets must preserve the context's decision, execution and expiry timestamps and information cutoff.
- `occurred_at`/`recorded_at`: preserve the native execution event time even when a callback or reconnect records it later. Recording cannot precede occurrence.

Historical backtests may use older public observations that were ingested later and reproduce features computed later. Feature adjustments must still use a cutoff no later than the historical decision. Paper/shadow contexts also require ingestion, computation and generation to have occurred by the decision. They reject synthetic market observations and require prospective macro output.

Numerical models must identify their saved preprocessing and ordered feature schema, and their training cutoff must precede the decision. A pinned model for a whole experiment must finish training before the first execution session. The estimator/feature names and order must agree, not just a mutable model alias. Proving matured labels, leakage-free fitting and artifact contents belongs to BB-015; this schema validates the supplied metadata.

Historical LLM replay must use `historical_exploratory`, including unknown or later training cutoffs. Generation after a historical decision is allowed only in that explicitly labelled replay path. Prospective use requires the output to already exist and remain unexpired. This preserves the distinction between historical interpretation and a recorded real-time prediction.

## Provenance and evidence

Source hashes are SHA-256 of the exact original UTF-8 text. Supporting spans use zero-based, half-open Unicode **character** offsets `[start, end)`, not byte offsets. Source IDs, revision content hashes and exact span text are checked together in `validate_macro_sources` and when constructing a context. A non-unknown comparison must cite both current and comparison document groups. Unknown outcomes can omit spans; they cannot silently become “unchanged.” Correct quoting is not proof that a model's interpretation is correct; independent evaluation remains BB-013.

Dataset kinds must match the supported v1 observation/document/assessment schema. Unknown revision timing requires an explicit dataset limitation that is also preserved in the experiment. Synthetic input anywhere requires a synthetic backtest label. The fixed universe, its listing intervals and selection limitations are recorded instead of inferring a historical universe from currently surviving tickers.

SHA-256 references are required and mutable aliases are rejected where immutable identities are needed. BB-003 validates syntax and cross-record bindings, not the existence or contents of external dataset/model blobs. BB-004/005 and later model stories own artifact resolution, checksum verification, snapshot publication and data-quality checks. Do not mistake a valid specification for a runnable or qualified experiment.

Audit events distinguish a delta execution from the cumulative filled quantity: a four-of-ten partial event records `fill_quantity_delta=4`, `cumulative_filled_quantity=4`, `requested_quantity=10`. A later cancellation can preserve cumulative four with zero new execution. Missing acknowledgments can remain `uncertain` without inventing a broker ID. Event validation creates no order state machine and does not deduplicate events; durable identity and reconciliation remain BB-006/018. Corporate-action posting and its richer audit records remain BB-009; the experiment already declares entitlement, payment and receivable treatment.

## Canonical identity and version policy

Every persisted top-level contract requires integer `schema_version: 1`. Unknown/missing versions and extra fields are rejected, including string or boolean versions. Supporting records are governed by that enclosing version. There are no migrations yet. Future incompatible changes require a new explicitly supported format with a tested migration or an explicit rejection; do not reinterpret old saved records under new semantics.

`canonical_json` validates the record, expands defaults, includes explicit nulls, normalizes aware instants to UTC with six fractional digits, and writes finite decimals as normalized strings without insignificant trailing zeros or exponent notation. Object keys sort lexicographically; UTF-8 text is retained and JSON contains no formatting whitespace. Ordered sequences stay ordered. Strategy settings normalize by unique name; feature order and universe order remain part of the declared specification. This is BuffetBot's versioned encoding, not a claim of implementing an external canonical-JSON standard.

`experiment_id(spec)` is the lowercase SHA-256 of those canonical UTF-8 bytes. Key insertion order, equivalent offsets, equivalent decimal spelling and explicit/default values do not change it. Changes to parameters, seeds, data, model/prompt/code/lock references or execution assumptions do. `new_run(spec)` gives each attempt a fresh UUID4 while retaining that specification ID. `ExperimentManifest` recomputes the ID on load and rejects a tampered specification. BB-006/010 will use the run ID for durable jobs/artifact locations so reruns cannot overwrite each other.

## Runnable examples and handoff

```bash
uv run --locked --offline python examples/contracts/validate.py
uv run --locked --offline pytest -q tests/test_contracts.py
```

Use `/home/jack/.local/bin/uv` if necessary on this development machine. No qualification group, account, network, model download or GPU is required. The [example directory](../examples/contracts) contains a synthetic specification, context, target and audit event. Its model/dataset digests are explicitly illustrative identifiers, not published artifacts; its example URL is non-resolving and no source is fetched. The all-cash demonstration exercises the strategy signature without implementing BB-007's trading policies. Each invocation prints two distinct run IDs for the same specification.

BB-004 reuses these records for immutable data snapshots and adds snapshot/corporate-action contracts. BB-007 implements and validates concrete policies/parameters. BB-008 checks execution-time risk. BB-009 binds engine observations/events to these records and implements the qualified corporate-action rules. BB-013/015 validate actual model outputs/artifacts. BB-017/018 apply the broker/account boundary and native lifecycle; those later integrations are not completed by schema validation or snapshot storage.
