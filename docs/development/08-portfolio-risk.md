# BB-008 — Portfolio limits and order planning

**Status:** Not started  
**Depends on:** [BB-003](03-contracts-and-experiments.md), [BB-007](07-strategy-policies.md)  
**North Star:** Explicit execution authority; operational limits

## User outcome

As the operator, I know every order intention is checked against current account state and the same declared portfolio limits.

## Scope and simplest approach

Implement a deterministic target-to-order planning function and final pre-submission validation around the selected engine's supported portfolio/order facilities. Return a small plan containing intentions, rejections, required prerequisites, and reasons. The engine remains responsible for submission and order lifecycle.

## Acceptance criteria

1. Inputs include target weights, current holdings, cash/buying power, unresolved/open orders, instrument rules, valid prices, mode, and risk configuration. Unreconciled or stale account state blocks new exposure.
2. Enforce long-only positions, allowed instruments, position and aggregate exposure, pending exposure, maximum order size, turnover/order-frequency bounds where configured, available funds, and target expiry outside strategy/model code.
3. Reject invalid/nonfinite values, unknown instruments, missing required prices, and unsupported order types. Use the same semantics in backtesting and paper execution.
4. Define quantity rounding and minimum-size rules. Buying estimates reserve applicable costs and price uncertainty; expected sales do not become available buying power before the engine/broker's rules permit it.
5. Account for outstanding buy/sell quantities and unresolved intentions when deriving deltas. A second planning call on unchanged state cannot independently add exposure already represented by a pending intention.
6. Define the execution convention selected in BB-002, including price freshness, sequencing, and validation immediately before submission. A changed quote/account snapshot can invalidate a previously valid plan.
7. Persist the effective risk configuration and all reasons for clipped or rejected actions. Risk fields cannot be supplied or overridden by an LLM response or model artifact.
8. Define the response to configured loss/drawdown limits as explicit actions on new and existing exposure. Tracking those conditions is integrated in BB-020; this story establishes the action contract.

## Verification

- Use independently calculated target/holdings examples including rounding, insufficient funds, commissions, pending buys, pending sells, and a cancellation not yet acknowledged.
- Attempt to exceed limits through an otherwise valid strategy output; verify rejection at the shared boundary.
- Change the price or cash balance between planning and final validation and verify an obsolete plan cannot be submitted unchanged.

## Completion evidence

Provide risk configuration examples, expected/actual plans, reason records, and boundary test results. Include the rounding/funds policy in developer documentation.

## Handoff and limits

Do not add a portfolio optimizer, margin engine, or another order manager. Use the selected engine's capabilities and explicit small checks appropriate to daily ETFs and one paper account.
