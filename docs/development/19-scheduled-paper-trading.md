# BB-019 — Scheduled paper trading cycle

**Status:** Not started  
**Depends on:** [BB-005](05-market-data-ingestion.md), [BB-007](07-strategy-policies.md), [BB-014](14-hybrid-and-shadow.md), [BB-016](16-candidate-selection.md), [BB-018](18-paper-order-lifecycle.md)  
**North Star:** Autonomous operation under a selected policy; shared decisions

## User outcome

As the operator, I can start the worker and have one selected strategy complete its daily paper workflow without leaving the dashboard open.

## Scope and simplest approach

Implement a calendar-aware schedule in the existing worker using ordinary persisted cycle records and a testable clock. The cycle orchestrates existing ingestion, strategy, planning, and execution functions. No distributed scheduler or autonomous orchestration agent is required.

## Acceptance criteria

1. Configuration declares exchange/session calendar, decision time, expected finalized-data availability, execution window/order convention, expiry, and failure policy. Handle holidays, shortened sessions, and daylight-saving changes using the same calendar/time conventions as research.
2. A cycle refreshes/validates data, reconciles the account, captures the selected release and configuration, generates targets, checks risk, submits eligible paper intentions, records events, and updates reports/health.
3. Persist deterministic cycle identity and progress before order-capable work. Restart/re-delivery recognizes already planned/submitted actions and uses BB-018 recovery rather than repeating the session's orders.
4. The signal cutoff precedes eligible execution. Late starts, missing finalized data, expired targets, and missed sessions follow a declared skip/recompute policy; there is no blind catch-up trading on old decisions.
5. Activate a requested release only at a reconciled boundary with outstanding/unresolved orders addressed. Every cycle keeps one pinned release identity even if a new selection arrives during its execution.
6. Run optional prospective A/B/C shadow jobs in separate simulated portfolios. Only the selected paper strategy can reach the broker, and a shadow or inference failure does not silently stop its numerical baseline.
7. A strategy that depends on missing/expired model inputs follows its tested fallback and records the effect. Invalid model artifacts or incompatible schemas prevent activation instead of changing models automatically.
8. Persist source freshness, decision rationale, target/plan, execution results, errors, and account reconciliation for each cycle. The worker operates with the browser closed.
9. Complete a real paper cycle in an eligible session or record the external session constraint as pending. Deterministic clock tests cover other calendar/timing scenarios without waiting through real days.

## Verification

- Advance an injected clock through ordinary/shortened sessions, a holiday, a DST transition, and a late restart.
- Restart after planning and after partial submission; verify no independent duplicate cycle/intention.
- Change the requested release mid-cycle and delay a shadow job; verify the executing cycle's identity and responsiveness remain correct.

## Completion evidence

Provide schedule/configuration, deterministic-clock results, restart traces, and an actual paper cycle with data/decision/execution timestamps.

## Handoff and limits

Use daily ETF operation only. BB-020 adds prolonged-failure policy and operator commands; frequent retraining and self-modifying schedules are outside this story.
