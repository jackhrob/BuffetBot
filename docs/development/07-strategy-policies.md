# BB-007 — Benchmark and numerical strategy policies

**Status:** Not started  
**Depends on:** [BB-003](03-contracts-and-experiments.md), [BB-004](04-dataset-snapshots.md)  
**North Star:** Shared strategies; simple controls; hybrid experiment A/B

## User outcome

As a researcher, I can compare understandable baseline policies without changing the execution or accounting implementation.

## Scope and simplest approach

Implement a buy-and-hold control, a fixed moving-average trend policy (A), and the same policy with a predefined volatility adjustment (B). Use explicit Python functions/classes registered by name in a small fixed mapping. Inputs and output targets use BB-003 contracts.

## Acceptance criteria

1. Policies implement the same target-generation interface and have no broker credentials, network calls, or direct order submission.
2. Define and document the benchmark's initial allocation/rebalancing convention and each strategy's moving-average windows, warmup, decision frequency, tie behavior, and cash policy before evaluating results.
3. Calculate features exclusively from completed observations available by the decision cutoff. Missing warmup or an invalid last observation produces a defined abstention/error outcome with reason codes.
4. A generates valid long/cash portfolio targets for the declared universe. State how weights are normalized when only some instruments qualify and how capital stays in cash when none qualify.
5. B applies an explicitly specified trailing volatility estimator, scale/cap formula, and rebalancing convention to A. Zero/undefined volatility cannot create infinite exposure or silently exceed constraints.
6. Targets record strategy/configuration identity, feature cutoff, expiry, and sufficient numerical reason fields to reconstruct the decision. Explanations come from recorded inputs rather than an LLM guessing afterward.
7. Identical contexts yield identical targets. Warmup and pending exposure are handled consistently when called through simulation and paper adapters.
8. No parameter search or online parameter mutation occurs inside these policies. The benchmark and A/B settings remain fixed for an experiment.

## Verification

- Use short hand-calculated price sequences for upward, downward, flat, crossing, and insufficient-history cases.
- Add observations after a cutoff and verify the earlier target is unchanged.
- Verify zero volatility, a missing session, ties, and no eligible positions produce the documented outcomes.

## Completion evidence

Provide policy formulas/configuration examples, target examples with reasons, and deterministic/time-cutoff test results. Profitability is not an acceptance condition.

## Handoff and limits

BB-008 applies account-wide risk limits independently of the policy. BB-014 later adds a bounded macro adjustment to B. Keep indicators limited to those these policies actually use.
