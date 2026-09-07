# BB-016 — Candidate review and release selection

**Status:** Not started  
**Depends on:** [BB-011](11-research-dashboard.md), [BB-014](14-hybrid-and-shadow.md), [BB-015](15-candidate-training.md)  
**North Star:** Inspectable candidates; deliberate selection; pinned execution

## User outcome

As the operator, I can review a candidate's evidence and deliberately select a reproducible release for shadow or paper use.

## Scope and simplest approach

Use SQLite metadata plus the existing immutable artifacts as a small candidate registry. Add a dashboard comparison/review view and a versioned release manifest. A separate model-registry service or promotion orchestrator is unnecessary.

## Acceptance criteria

1. Display baseline and candidate configuration, feature/model/prompt identity, training/evaluation dates, data coverage, costs, metrics, uncertainty/limitations, and qualification findings using existing reports.
2. Record created/evaluated/rejected/qualified-for-shadow states with reasons and evidence. Technical validity and strategy-performance assessment are separate fields; neither an LLM explanation nor a high historical return bypasses required checks.
3. A candidate can be rejected and retained. A policy that fails qualification cannot silently appear as ready for paper execution. The benchmark/rule baseline remains a selectable release if numerical/LLM candidates are rejected.
4. A release manifest pins strategy code/configuration, optional trusted model and preprocessing, optional macro policy, dependency expectations, and compatible feature schemas. Reference the effective risk policy separately so the model cannot redefine limits.
5. Deliberate selection creates an audited request with old/new release IDs and reason. It does not submit orders or mutate a running decision halfway through a cycle. BB-019/BB-020 own safe activation.
6. Missing/tampered artifacts, unresolved mutable model aliases, invalid expiry, incompatible schema, and insufficient provenance prevent activation with an explicit reason.
7. Preserve at least the current and previous valid release and their artifacts. A rollback is an explicit version selection with a recorded reason, not a mutable `latest` pointer.
8. Allow selection for shadow evaluation without implying authorization for live trading. The MVP offers only its supported research/shadow/paper states.
9. Complete the workflow for a real trained candidate and a rejected fixture candidate in the dashboard. No model-training job or inference response can select itself.

## Verification

- Review and select a valid baseline/candidate, reject another, and verify complete transition history.
- Tamper with a manifest/model, change a model alias, and request an incompatible release; verify clear rejection.
- Change the requested release during a simulated active cycle and verify the current cycle retains its original identity.

## Completion evidence

Provide a candidate comparison, qualification/rejection records, selected release manifest, and rollback/invalid-artifact check results.

## Handoff and limits

This story defines selection requests and immutable releases. Actual running-strategy activation waits for the reconciled safe boundary established in BB-019 and BB-020; automatic promotion is not part of the MVP.
