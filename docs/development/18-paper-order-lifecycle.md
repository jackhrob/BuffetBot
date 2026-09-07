# BB-018 — Paper order execution and recovery

**Status:** Not started  
**Depends on:** [BB-008](08-portfolio-risk.md), [BB-009](09-backtest-accounting.md), [BB-017](17-paper-broker.md)  
**North Star:** Reliable paper execution; uncertain outcomes; recovery

## User outcome

As the operator, I can submit validated paper orders and recover from network/process failures without silently duplicating exposure.

## Scope and simplest approach

Connect validated plans to the selected engine's order facilities. Persist a narrow intention/audit record with stable broker-compatible client identity before submission, then record native acknowledgments/events. Reconcile uncertainty using native lookup and account state rather than implementing a parallel trading state machine.

## Acceptance criteria

1. Submission requires the active worker lock, ready/reconciled paper account, a valid selected plan, and a final BB-008 validation against current state. Direct strategy/LLM/UI calls cannot bypass this boundary.
2. Derive a persistent logical intention ID and supported broker client ID from the run/cycle and intended action. Re-delivery cannot create an independent second intention for the same logical action.
3. Preserve acknowledged, partial, filled, rejected, cancelled, expired, and uncertain outcomes with native IDs/statuses. Duplicate events do not double-count quantities, cash, or costs; reordered events trigger reconciliation when needed.
4. If a submission times out, query its known identity and reconcile before considering another attempt. A missing lookup response is not conclusive proof the broker never accepted the order. Unresolved ambiguity blocks new conflicting exposure.
5. Handle cancellation/fill races and replacement sizing using actual filled and outstanding quantities. Requesting cancellation does not immediately release reserved exposure or buying power.
6. A crash before submission, after submission but before acknowledgment persistence, or during partial fills recovers using durable intent plus broker truth. Document the achievable behavior without claiming universal exactly-once remote execution.
7. Preserve engine-owned lifecycle state and a reconcilable ledger. Differences between simulated and paper fills remain visible rather than being retroactively rewritten to agree.
8. Complete a controlled actual paper lifecycle using small simulated quantities: acceptance, a terminal fill, and a cancellation attempt with its actual terminal outcome. Use suitable order types/session timing; if an intended cancellation fills first, record the fill honestly.
9. Deterministic fixtures/fault injection cover partial fills and races the broker simulator cannot reliably be made to produce. These drills complement, not replace, the actual paper check.

## Verification

- Replay the complete duplicate/reordered/partial/cancel-race fixture sequence and reconcile ending cash, quantities, and open exposure.
- Inject crashes on both sides of the remote submission boundary and verify lookup-driven recovery.
- Record the actual broker paper acceptance/fill/cancellation lifecycle with redacted IDs and ledger totals.

## Completion evidence

Save native event/audit traces, expected and actual reconciliation totals, fault-injection results, and the actual paper test result. An unrun external test leaves the integration incomplete.

## Handoff and limits

Support only the order conventions needed by the initial daily strategies. BB-019 schedules these operations; BB-020 defines operator controls and prolonged-failure behavior.
