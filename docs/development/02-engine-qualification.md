# BB-002 — Trading engine qualification

**Status:** Not started  
**Depends on:** [BB-001](01-project-foundation.md)  
**North Star:** Technical stack; shared decision logic; engine evaluation

## User outcome

As the developer, I know that the selected engine can support the MVP's accounting, data, model, and paper requirements before the application depends on it.

## Scope and simplest approach

Evaluate Lumibot first in the isolated project environment. Use a tiny supplied dataset and a disposable evaluation strategy. Produce a short decision record and retain useful fixtures as tests. This is a bounded qualification exercise, not a survey of every trading library or the production adapter implementation.

## Acceptance criteria

1. Record the tested version, Python compatibility, dependencies, license, and any required external services. Pin the chosen version after the evaluation.
2. Run a backtest from supplied local data without paid data or broker credentials. Demonstrate the strategy can receive a completed observation and submit an order for a later eligible execution time.
3. Verify cash, holdings, commissions, an explicit spread/slippage assumption, a split, and a dividend against independent hand-worked expectations. Demonstrate how executable prices are separated from adjusted feature prices.
4. Load a small saved numerical model and its preprocessing inside the strategy runtime. Verify output matches the same artifact outside the engine within a declared tolerance.
5. Inspect and demonstrate the supported adapter paths for paper configuration, account snapshots, stable client order identity, order lookup, partial fills, and startup reconciliation. Identify native engine ownership and the narrow extensions required.
6. Record order types, timing rules, calendar behavior, limitations of daily bars, and unsupported requirements. A default fill model is not accepted without checking its behavior.
7. Produce a clear adopt/reject decision. Any required accounting or lifecycle gap must have a demonstrated small resolution or trigger another engine evaluation. Preserve the same proposed strategy contract when replacing the candidate.
8. Distinguish documentation/code inspection from actual broker tests. This story can qualify the software path without credentials; real paper behavior remains mandatory in BB-017 and BB-018.

## Verification

- Run the supplied-data example twice and compare accounting results.
- Use fixtures where same-close execution and dividend double counting produce visibly wrong totals.
- Exercise missing model files and unsupported order configuration; confirm explicit errors.

## Completion evidence

Save the engine decision, dependency details, exact example commands, expected/observed ledger totals, and a list of remaining integration checks. A successful library import alone is insufficient.

## Handoff and limits

BB-003 formalizes only the contracts needed by the qualified path. Reuse native engine features; do not create a second order state machine or general matching engine to compensate for an unsuitable dependency.
