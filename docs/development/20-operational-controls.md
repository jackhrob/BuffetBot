# BB-020 — Operational controls and failure handling

**Status:** Not started  
**Depends on:** [BB-018](18-paper-order-lifecycle.md), [BB-019](19-scheduled-paper-trading.md)  
**North Star:** Visible failures; explicit pause/cancel/close behavior; recovery

## User outcome

As the operator, I can understand a failure, control existing paper exposure, and resume only when the account and data are ready.

## Scope and simplest approach

Use persisted operational flags, explicit worker commands, and a local health-check command. Reuse risk planning, order execution, and reconciliation for operator-requested actions. A monitoring cluster or distributed control plane is unnecessary.

## Acceptance criteria

1. Define ready, paused, recovering, and blocked/error states with machine-readable reasons and last successful data/account/worker activity. A pause survives process restart and cannot be cleared by a model.
2. Provide distinct commands for pausing new strategy submissions, resuming, cancelling specified/all managed open orders, and requesting closure of managed positions. Describe what each leaves outstanding before and after completion.
3. Pausing does not pretend to cancel existing orders or flatten positions. Explicit cancellation and position-close requests pass through the same paper identity, readiness, risk, intention, and event paths; they cannot claim success until broker state confirms the actual outcome.
4. Define failure responses for stale data, broker/inference timeouts, corrupted artifacts, prolonged disconnection, and account mismatch. Preserve an explicit existing-position policy; unknown/unreachable state cannot be labelled flat or recovered.
5. Track configured daily-loss and drawdown conditions using a documented equity baseline, session boundary, and supported cash-flow policy. Trigger the configured response outside models and preserve the incident and effective limits.
6. Resume/release activation requires the worker lock, valid unexpired artifacts, reconciled sufficiently recent account state, eligible data, and cleared blocking conditions. It cannot replay expired orders or auto-resume a manual pause after restart.
7. A rollback selects a previous verified release at a safe boundary, accounts for outstanding orders, and records the reason. Artifact failure cannot trigger an undocumented fallback model.
8. A separate local health-check process detects a stale worker heartbeat and returns a useful nonzero result without calling the worker or LLM. Document supervision and recovery without claiming it works if the entire host is down.
9. Unknown/manual broker holdings are not silently included in cancellation/closure scope. Display unsupported ownership and require explicit account reconciliation before affected actions.

## Verification

- Pause while an order partially fills, cancel it, and request closure; reconcile actual terminal outcomes including fill/cancel races.
- Restart a paused worker, trigger a configured loss threshold, corrupt a release artifact, and simulate prolonged disconnection.
- Kill/hang the worker and verify the independent local health check detects staleness; restore readiness through reconciliation.

## Completion evidence

Save the operating-state/action policy, incident/recovery traces, control outcomes, rollback demonstration, and health-check results.

## Handoff and limits

Controls apply to the configured paper account only. They do not guarantee liquidity, fills, or a maximum realized loss. Use native engine/broker operations rather than an additional execution service.
