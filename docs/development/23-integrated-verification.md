# BB-023 — Integrated verification and failure drills

**Status:** Not started  
**Depends on:** [BB-014](14-hybrid-and-shadow.md), [BB-015](15-candidate-training.md), [BB-018](18-paper-order-lifecycle.md), [BB-020](20-operational-controls.md), [BB-021](21-operations-dashboard.md), [BB-022](22-deployment-and-restore.md)  
**North Star:** Demonstrated correctness; complete integration evidence

## User outcome

As the owner, I have evidence that the assembled MVP works across its boundaries and recovers from the failures most likely to corrupt trading results.

## Scope and simplest approach

Assemble a small integrated suite and a manual/external verification matrix from the fixtures and checks already built. Use pytest and ordinary scripts/commands. Add cross-component scenarios where necessary; do not rebuild the same unit tests in another framework.

## Acceptance criteria

1. An offline integrated path imports fixtures, runs controls and A/B/C with explicitly synthetic recorded model output, generates reports, trains a candidate, reviews/selects a release, and simulates the paper lifecycle through the adapter boundary. Labels and provenance remain intact throughout.
2. A separate external path verifies actual market and macro ingestion, actual Ollama extraction, actual numerical training on market data, actual paper reads/orders, and one scheduled eligible paper cycle. Each result records the exact tested version/configuration and evidence origin.
3. Combine failures across boundaries: restart after uncertain submission; partial fill plus cancel/release-change request; stale market input during a cycle; malformed/expired model output; duplicate UI request; second worker; and restored local state that differs from the current broker.
4. Each drill states its expected invariants before execution, including no independent duplicate exposure, reconciled quantities/cash, preserved active release, blocked new exposure where required, and honest job/control status.
5. Future-data, overlapping-label, corporate-action, and cost tests from earlier stories run as part of the relevant regression set. No assertion requires a strategy to be profitable.
6. Ordinary automated checks run without credentials or unbounded network access. External tests are explicit and cannot submit orders merely because a developer runs the default unit suite.
7. Report Passed, Failed, Not run, or Blocked per required check. Skipped/fixture-only checks cannot turn external integration evidence green. Resolve failures or leave the corresponding story/release incomplete.
8. Measure cycle/job runtime, worker responsiveness during research, and model latency on the documented workload. Verify required work can finish before its configured cutoff; choose limits based on measurements rather than building speculative performance infrastructure.
9. Record known limitations and their product effect. A limitation that violates mandatory acceptance criteria is an unresolved defect, not merely a release-note item.

## Verification

- Execute the documented offline suite and external matrix on the release-candidate environment.
- Reuse fault-injection fixtures with predeclared invariants and correlate final storage/account state.
- Review the [release acceptance checklist](release-acceptance.md) against produced artifacts rather than checkboxes alone.

## Completion evidence

Save the scenario matrix, code/environment identity, exact commands, results, artifacts, and unresolved items. Evidence from earlier stories can be reused when relevant code/configuration has not changed; rerun affected checks after material fixes.

## Handoff and limits

BB-024 packages this evidence and the operating guide. A short successful paper run validates mechanics only; it does not establish a durable investment advantage.
