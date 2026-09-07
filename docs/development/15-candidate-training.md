# BB-015 — Numerical candidate training

**Status:** Not started  
**Depends on:** [BB-005](05-market-data-ingestion.md), [BB-006](06-jobs-and-worker.md), [BB-007](07-strategy-policies.md), [BB-009](09-backtest-accounting.md), [BB-010](10-reports-and-comparisons.md)  
**North Star:** Chronological ML evaluation; bounded policy improvement

## User outcome

As a researcher, I can train and evaluate one simple numerical candidate without future information contaminating its results or replacing the selected strategy.

## Scope and simplest approach

Start with one regularized numerical estimator and a small explicitly bounded parameter set. Define a fixed forward-return task, such as the return from the next eligible entry to a five-session exit. Use scikit-learn preprocessing/estimation and normal local artifacts; no automated model search platform is needed.

## Acceptance criteria

1. Declare features, prediction/holding horizon, entry/exit price convention, label start/end times, missing-data handling, estimator, parameter candidates, and portfolio mapping before evaluating results.
2. Build features using only eligible observations. Train only on labels whose outcomes are fully known at the training cutoff; preserve that cutoff in the artifact.
3. Split panel observations by date across all instruments. Remove training labels overlapping validation/test periods. Fit scaling, imputation, and any feature selection within each training partition only.
4. Reserve a final evaluation period outside tuning. Preserve every candidate trial and explain that repeatedly inspecting the same final period makes it development data for later experiments.
5. Use an explicit deterministic mapping from forecasts to valid portfolio targets and evaluate through BB-009 and BB-008. Forecast metrics and portfolio outcomes after costs are reported separately against the rule baseline.
6. Reject insufficient history, empty folds, nonfinite features, immature labels, and schema mismatches with useful diagnostics rather than manufacturing scores.
7. Save a complete candidate bundle: model, preprocessing, feature schema/order, code/dependency identity, dataset/specification hashes, training cutoff, seeds, configuration, and evaluations. No training job can activate the candidate for paper operation.
8. Load the bundle in an isolated process and reproduce sample predictions and evaluated targets within declared tolerances. Load only trusted locally produced artifacts referenced by verified manifests, not arbitrary uploaded serialized models.
9. Complete one real-market-data training/evaluation run. Weak or negative results are retained; the software does not search until it finds profits or silently change the target.

## Verification

- Use engineered time/label fixtures where a future observation, overlapping label, or global scaler would change the result; verify isolation.
- Check all instruments on a date remain in the same partition and incomplete future outcomes are excluded.
- Save/reload the real candidate and reproduce its predictions and backtest report.

## Completion evidence

Provide the target/feature definition, chronological split report, leakage-check results, complete trial list, real-data result, and reload/replay evidence.

## Handoff and limits

BB-016 exposes evaluation and selection. Deep learning, reinforcement learning, LLM fine-tuning, broad hyperparameter optimization, and automatic promotion are later work.
