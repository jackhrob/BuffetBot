# BB-014 — Hybrid comparison and prospective shadow runs

**Status:** Not started  
**Depends on:** [BB-007](07-strategy-policies.md), [BB-008](08-portfolio-risk.md), [BB-010](10-reports-and-comparisons.md), [BB-011](11-research-dashboard.md), [BB-013](13-llm-extraction.md)  
**North Star:** Hybrid strategy experiment; prospective evidence; separate portfolios

## User outcome

As a researcher, I can measure whether macro interpretation changes strategy behavior and whether those changes improve results under common assumptions.

## Scope and simplest approach

Implement C as a small explicit adjustment to B. Run A, B, and C through the same simulator, risk checks, and reporting path. Add a prospective mode that records decisions before future outcomes are known and maintains independent shadow portfolios using the qualified engine's simulation facilities.

## Acceptance criteria

1. Declare the category-to-allocation mapping, maximum adjustment, expiry, rebalance timing, and unknown/invalid/stale assessment fallback before evaluation. The mapping is configuration/policy code, not free-form LLM order instructions.
2. A/B/C share dates, snapshots, universe, starting capital, execution/cost conventions, and risk budgets. Each has independent holdings, cash, fills, and report identifiers.
3. Show which numerical inputs, assessment IDs, evidence passages, and policy rule changed C's targets. Macro influence never overrides BB-008 limits.
4. Use only source versions eligible at the declared cutoff. Preserve actual assessment generation time and model-cutoff status. Historical derivations using a later model are visibly exploratory and never relabelled as contemporaneously generated evidence.
5. Persist future-facing assessments and decisions before their outcome interval completes. Prospective results cannot be rewritten by later document revisions, prompt changes, or reanalysis.
6. Shadow mode has no broker submission path. Its fill assumptions and latency/cost limitations are explicit, and it reuses a tested simulation/accounting path rather than creating a second general simulator.
7. Missing assessments follow the declared policy and appear in comparison statistics. Entirely absent macro data is reported as missing experimental coverage, not evidence that the hybrid performed identically by design.
8. Extend the dashboard with side-by-side A/B/C results and a macro evidence view. Users can distinguish synthetic, retrospective exploratory, and prospective records.
9. Demonstrate one real-data comparison using saved actual local-model output, plus prospective decision capture with actual generation timestamps. Price/behavior fixtures separately verify the timing and accounting edge cases.

## Verification

- Use a known assessment to cause a bounded target change and verify its trace through risk planning to the report.
- Inject expired output, a later source revision, and missing inference; verify deterministic fallback and unchanged old decisions.
- Verify A/B/C portfolios do not share state and shadow runs cannot access broker order methods.

## Completion evidence

Save the frozen mapping, comparison manifest/reports, prospective decision record, source evidence links, and timing/portfolio-isolation checks. A rejected hybrid remains a valid outcome.

## Handoff and limits

Do not add regime-discovery frameworks or automatically tune the mapping on the evaluation period. BB-019 later schedules this same prospective workflow alongside the selected paper strategy.
