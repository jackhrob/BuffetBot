# BB-009 — Backtest execution and accounting

**Status:** Not started  
**Depends on:** [BB-002](02-engine-qualification.md), [BB-004](04-dataset-snapshots.md), [BB-006](06-jobs-and-worker.md), [BB-007](07-strategy-policies.md), [BB-008](08-portfolio-risk.md)  
**North Star:** Realistic simulation; accounting correctness; shared decisions

## User outcome

As a researcher, I can run a strategy through a believable, inspectable simulation with correct cash, quantities, and execution timing.

## Scope and simplest approach

Build the production backtest adapter around the engine selected in BB-002. Supply snapshots and the shared strategy/risk code. Reuse the engine's accounting and fill facilities with explicit configuration and narrowly necessary fixes; do not implement a general exchange simulator.

## Acceptance criteria

1. A validated specification starts a durable backtest job from immutable snapshots. The adapter exposes only information eligible at each historical decision cutoff.
2. Signals requiring a completed close execute no earlier than the next eligible session under the chosen convention. The simulation does not claim an unavailable opening/closing auction or an intraday path inferred from daily OHLC.
3. Configure fees, spread/slippage, cash/buying-power behavior, order expiration, rounding, and supported liquidity assumptions explicitly. Avoid counting a spread again when already included in modeled fill prices.
4. Verify split changes to quantity and cost basis, dividend entitlement/cash timing, and raw-price marking against the shared hand-worked fixtures. Do not count a dividend both in adjusted returns and cash.
5. Every decision, rejected plan, order, fill, corporate action, cash movement, and portfolio valuation is traceable. Cash plus marked holdings reconciles to equity within declared rounding tolerances.
6. Handle insufficient funds, closed sessions, missing execution observations, unfilled orders, and positions open at the end under documented rules. Do not silently liquidate at the end or drop an incomplete order.
7. Run controls and strategies with equivalent dates, warmup exclusion, universe, cash treatment, and costs. Distinguish absent history from a policy deliberately holding cash.
8. Run fixtures without network or model calls and reproduce results from the same snapshot/configuration. Errors preserve an incomplete/failed job and diagnostic artifacts rather than a success report.

## Verification

- Compare full ledgers to independent examples for ordinary trading, costs, a split, a dividend, a gap, and an unfilled last-session order.
- Prove the same-close error and dividend double-counting error would fail those checks.
- Run the same decision context through a paper-style adapter stub and the backtest adapter; compare targets and validation reasons, without requiring identical broker fills.

## Completion evidence

Save fixture ledgers, reconciliation totals/tolerances, execution-model documentation, and repeat-run results. Reuse these scenarios for later regressions.

## Handoff and limits

Results feed BB-010. Any remaining engine accounting limitation must be resolved or explicitly exclude unsupported input; it cannot be hidden behind a disclaimer in an otherwise successful report.
