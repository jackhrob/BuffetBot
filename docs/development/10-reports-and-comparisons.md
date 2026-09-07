# BB-010 — Reproducible reports and comparisons

**Status:** Not started  
**Depends on:** [BB-009](09-backtest-accounting.md)  
**North Star:** Inspectable results; separate engineering and investment evidence

## User outcome

As a researcher, I can explain a result, compare it fairly with a benchmark, and reproduce it later from its saved inputs.

## Scope and simplest approach

Generate structured summary data, equity/drawdown series, a readable report, and a trade ledger from saved engine outputs. Use one reporting implementation for the CLI and dashboard. Preserve the original run and create a new comparison artifact rather than editing past results.

## Acceptance criteria

1. Reports show net/gross P&L where supported, benchmark return, exposure, drawdown and recovery, turnover, execution costs, trade count, holding period, and instrument/period contributions. Report actual computation definitions and units.
2. Equity and realized/unrealized P&L reconcile with BB-009's cash/position ledger. Corporate actions and costs remain visible in attribution.
3. State conventions for returns, annualization, volatility, drawdown recovery, benchmark reinvestment, and uninvested cash. Short/degenerate samples produce explicit undefined/insufficient-data fields instead of misleading infinite or zero scores.
4. No deposits/withdrawals are silently treated as investment returns. Reject unsupported external cash flows or use an explicitly documented return method.
5. Comparison requires compatible dates, capital, universe, feed/adjustment convention, and execution assumptions, or clearly presents mismatches without implying like-for-like ranking.
6. Record code revision, canonical specification ID, snapshot hashes, dependency/environment identity, model/prompt/output IDs where applicable, seeds, and all output paths. For uncommitted code, save a source-content identifier instead of claiming a nonexistent commit.
7. Provide a replay command and verify it preserves material outputs within declared numerical tolerances. Preserve separate run records and explain any nondeterminism.
8. Provide a small predetermined cost/delay sensitivity comparison using new runs. Do not choose stress scenarios after viewing profits to make a result look robust.
9. Modes and data origins are prominent. Synthetic, historical, shadow, and actual paper evidence cannot be mistaken for each other; incomplete jobs cannot generate a successful report.

## Verification

- Check metrics on hand-calculated equity paths, including flat equity, no trades, a drawdown that never recovers, and an open final position.
- Reproduce a saved run and reject a tampered snapshot or incompatible model reference.
- Compare compatible runs and intentionally mismatched runs; verify the mismatch is explicit.

## Completion evidence

Provide representative reports, metric definitions, reconciliation/check results, and an exercised replay command.

## Handoff and limits

Use ordinary tabular/plot outputs; no separate analytics service or report-rendering platform. The dashboard consumes these same report artifacts.
