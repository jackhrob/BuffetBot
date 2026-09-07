# BB-021 — Paper operations dashboard

**Status:** Not started  
**Depends on:** [BB-011](11-research-dashboard.md), [BB-016](16-candidate-selection.md), [BB-017](17-paper-broker.md), [BB-019](19-scheduled-paper-trading.md), [BB-020](20-operational-controls.md)  
**North Star:** Operator visibility; clear controls; mode separation

## User outcome

As the owner, I can inspect the paper account, trace a decision to its evidence, and issue clearly scoped operational commands from the same local application.

## Scope and simplest approach

Extend the existing Streamlit application using persisted snapshots, events, and command requests. The dashboard remains a view/request client; it does not maintain its own account balances, execute orders, or calculate an independent risk state.

## Acceptance criteria

1. Display paper mode prominently with a redacted account identity, selected/previous/requested release, worker state, data/account freshness, last/next cycle, and readiness or pause reasons.
2. Show broker-reconciled cash/buying power, positions, open/unresolved orders, recent fills, exposure, and current configured limits with their observation timestamps. Stale or missing values are marked unavailable/stale rather than presented as current zeros.
3. Allow tracing a cycle from source snapshot and optional macro evidence through targets, risk decisions, order intentions, native events, and account reconciliation. Distinguish strategy intent from actual fills.
4. Show paper broker results separately from simulated/shadow estimates. Differences in fees, corporate actions, and simulator behavior are explicit; do not manufacture broker dividends to make paper and research reports agree.
5. Expose BB-020's pause/resume, cancel, and managed-position-close commands with concrete scope and effect. Validated durable request IDs prevent browser retries from repeating one command.
6. Command state distinguishes requested, executing, completed, partially completed, failed, and unresolved as appropriate. A button click or accepted cancellation request cannot immediately display an account as flat.
7. Show candidate selection/rollback requests separately from the release currently active in the worker. Mid-cycle changes remain pending until the safe activation boundary.
8. The UI remains usable while the worker/broker/model is unavailable and presents recorded state with age and clear diagnostics. Closing/reopening the browser retains operation history.
9. No credentials, unrestricted serialized model uploads, raw secret-bearing errors, or live-trading controls appear in the UI or exports.

## Verification

- Walk through connect, inspect, run a cycle, pause, cancel, request closure, resume, and request a release change using supported paper behavior.
- Use fixture failures to exercise stale snapshots, unresolved orders, pending activation, worker loss, and partial command completion.
- Refresh/reconnect after submitting a command and verify only the original intention is processed.

## Completion evidence

Provide the operator walkthrough, correlated command/cycle/event records, and focused UI verification results. Include examples of stale and unresolved states.

## Handoff and limits

Reuse the existing application and read models. Do not add a separate web backend, multi-user authentication system, push-notification service, or second account dashboard.
