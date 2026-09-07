# BB-017 — Paper broker connection and reconciliation

**Status:** Not started  
**Depends on:** [BB-002](02-engine-qualification.md), [BB-003](03-contracts-and-experiments.md), [BB-006](06-jobs-and-worker.md), [BB-008](08-portfolio-risk.md)  
**North Star:** One paper account; account truth; startup reconciliation

## User outcome

As the operator, I can connect a paper account and see whether BuffetBot's view agrees with the broker before it can submit orders.

## Scope and simplest approach

Implement the qualified engine's Alpaca paper adapter and a read-only startup/reconciliation path. Preserve native broker/engine IDs and statuses. Use the existing worker/storage and avoid a second order owner. This story does not submit orders.

## Acceptance criteria

1. Paper mode chooses a fixed supported paper endpoint/configuration and validates account identity/permissions. Reject live endpoints and conflicting configuration before any order-capable operation.
2. Read account status, cash/buying power, positions, open orders, relevant recent fills, and supported instrument/order constraints through documented APIs. Record snapshot time and request success/failure.
3. Authenticate using local secrets that are absent from logs, dashboard payloads, research child environments, and model requests. Errors distinguish missing keys, invalid keys, unavailable service, and denied permissions.
4. Reconcile local audit records and engine state with broker snapshots. Preserve discrepancies, unresolved orders, and unknown positions rather than overwriting history or silently considering the account ready.
5. Startup and reconnect begin in a non-submitting state. Readiness requires validated account identity, a complete sufficiently recent snapshot, reconciliation, and the worker lock from BB-006.
6. Define behavior for a new account, an account reset, and unexpected manual trades/deposits. Adopt an explicitly recorded baseline only through the supported reconciliation path; do not trade or liquidate foreign holdings to make the account match.
7. Persist the bound account fingerprint and prevent silently attaching the state directory to a different account. Multiple independent deployments against the same account remain unsupported.
8. Complete an actual read-only paper connection and record reconciled account/position/order evidence. Without configured credentials, this check remains blocked and this story cannot be called fully done.

## Verification

- Exercise recorded snapshots with manual positions, mismatched balances, missing orders, denied permissions, and an account reset.
- Connect to the actual paper account without submitting an order and verify its redacted identity and counts.
- Restart and reconnect after a read failure; verify readiness is restored only after reconciliation.

## Completion evidence

Save redacted actual connection results, reconciliation records, account-binding behavior, and failure-case results. Clearly distinguish actual broker reads from fixtures.

## Handoff and limits

BB-018 adds mutations through this same adapter. No second broker, live endpoint toggle, account-transfer feature, or automatic adoption of unknown holdings is required.
