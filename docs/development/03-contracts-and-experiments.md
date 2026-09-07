# BB-003 — Shared contracts and experiment specification

**Status:** Not started  
**Depends on:** [BB-001](01-project-foundation.md), [BB-002](02-engine-qualification.md)  
**North Star:** Architecture and ownership; research integrity

## User outcome

As a strategy developer, I can express one strategy against a stable context and reproduce an experiment from an explicit specification.

## Scope and simplest approach

Define a small collection of Pydantic models or equivalent typed domain records and a normal Python strategy interface. Keep identifiers, units, and time conventions explicit. Avoid generic schema registries, configurable pipelines, or dynamic plugins.

## Acceptance criteria

1. Define market observations, source documents, macro assessments, strategy context, portfolio targets, execution audit events, and experiment manifests with the provenance fields required by the North Star.
2. The strategy boundary is `generate_targets(context) -> PortfolioTargets`. It has no broker client or unrestricted storage handle. Context exposes only observations available by the cutoff and includes current/pending exposure when needed.
3. Portfolio weights are finite, reference eligible instruments, and respect the MVP's long/cash semantics. Units and rounding conventions for money, prices, and quantities are explicit at accounting boundaries.
4. Distinguish observation/session time, public availability time, first ingestion time, decision time, and expiry. Reject timezone-naive decision timestamps and invalid temporal order rather than silently guessing.
5. An experiment specification records universe, date ranges/warmup, fixed parameters, initial simulated capital, benchmark, costs, execution convention, cash/corporate-action treatment, and dataset/model identifiers before running.
6. Validate unsupported modes, instruments, invalid weights, NaNs, incompatible feature/model schemas, and missing required references with useful field-level errors.
7. Serialize a validated specification canonically and compute a stable content identifier. Separately preserve a unique run ID so reruns share inputs without overwriting each other's execution records.
8. Version the persisted contract format and document how later schema changes are recognized. Support explicit migration or rejection; never silently reinterpret an old record.

## Verification

- Check valid round trips and stable specification identities independent of input key ordering.
- Exercise future observations, boundary expiry, mixed timezones, NaNs, and wrong monetary/weight units using small examples.
- Verify independently created runs reference the same specification while keeping separate run IDs.

## Completion evidence

Provide the contract definitions, example specifications, documented time/unit conventions, and meaningful validation results.

## Handoff and limits

These records are shared by ingestion, strategies, reports, and adapters. Keep implementation choices such as table layout or a library's internal order object out of the strategy-facing contract.

Use the [BB-002 engine decision](evidence/BB-002-engine-decision.md) as the verified input: separate eligible features from executable raw prices, preserve dividend receivables/payment dates and native event time, and express the qualified market/day convention and explicit cost/rounding assumptions in the specification.
