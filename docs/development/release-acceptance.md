# MVP release acceptance

This checklist verifies the end state described by the [North Star](../../NORTHSTAR.md) and [development stories](README.md). It is an evidence index, not a replacement for story acceptance criteria.

**Current state:** Full release checks not run. [BB-001 evidence](evidence/BB-001.md) verifies the local package/configuration foundation, but the complete setup check also requires BB-022's container deployment. [BB-002 evidence](evidence/BB-002.md) passes synthetic engine qualification; application accounting integration in BB-009 and actual broker checks remain unverified.

[BB-003 evidence](evidence/BB-003.md) verifies contracts and experiment identity. Policy/risk integration in BB-007/008 is still required before the full contract acceptance row can pass.

[BB-004 evidence](evidence/BB-004.md) passes the immutable-data row with synthetic fixtures, interrupted publications, corrupted files and an installed-package demonstration. Actual market ingestion and application accounting remain unverified.

For each row, record **Passed**, **Failed**, **Not run**, or **Blocked**, the code/configuration identity, command or walkthrough, date, artifact path, and whether it used synthetic fixtures, recorded responses, actual external data, or the broker paper environment. Passing an individual row does not imply broader release acceptance.

## Mandatory checks

| Check | Required observable result | Owning stories | Initial status |
| --- | --- | --- | --- |
| Clean setup | A fresh isolated environment and documented Compose setup start the application; live configuration is rejected | BB-001, BB-022 | Not run |
| Engine qualification | Supplied-data timing, costs, split/dividend accounting, saved-model loading, and required adapter paths are demonstrated | BB-002, BB-009 | Not run for full integration; BB-002 passed |
| Contract validation | Invalid units/weights/times and incompatible schemas fail explicitly; targets are isolated from broker authority | BB-003, BB-007, BB-008 | Not run for full integration; BB-003 passed |
| Immutable data | Snapshots survive refreshes unchanged; corrupt/incomplete snapshots are rejected; fixture origin stays visible | BB-004 | Passed — [synthetic evidence](evidence/BB-004.md) |
| Actual market ingestion | A real provider download has verified coverage, feed, action treatment, and cached provenance | BB-005 | Blocked — credentials missing; [offline adapter evidence](evidence/BB-005.md) passed |
| Durable jobs | Browser retries, child failures, and worker restarts preserve honest job states and artifacts | BB-006, BB-011 | Not run |
| Single worker | Two processes sharing the deployment state cannot both submit broker orders; owner death permits controlled recovery | BB-006, BB-020, BB-022 | Not run |
| Independent accounting | Cash, positions, fees, split, dividend, gap, and final open-order cases match independent expectations | BB-008, BB-009 | Not run |
| Reports and replay | Ledger/metrics reconcile; source/configuration identity is complete; a saved run reproduces material outputs | BB-010 | Not run |
| Research UI | The browser completes both a synthetic and a real-data experiment and displays provenance and failures | BB-011 | Not run |
| Actual macro ingestion | A real statement pair and vintage-aware series are stored; earlier cutoffs cannot access later revisions | BB-012 | Not run |
| Actual local inference | Ollama produces a recorded assessment on real documents; model identity, support checks, and labelled evaluation are present | BB-013 | Not run |
| Hybrid comparison | A/B/C use compatible independent portfolios; bounded influence, expiry, fallbacks, and exploratory labels work | BB-014 | Not run |
| Prospective evidence | Decisions/assessments are persisted before outcomes, retain actual timestamps, and cannot be rewritten by revisions | BB-014, BB-019 | Not run |
| Numerical training | A real-data candidate trains, evaluates chronologically, saves/reloads, and reports forecast and portfolio outcomes separately | BB-015 | Not run |
| Leakage checks | Future observations, overlapping labels, panel date mixing, and preprocessing fitted to evaluation data are caught | BB-007, BB-009, BB-015 | Not run |
| Candidate controls | Evaluation/rejection history and release manifests are inspectable; a training job cannot promote itself | BB-016 | Not run |
| Actual paper reads | Paper identity and current account/positions/orders are read and reconciled; live endpoints remain inaccessible | BB-017 | Not run |
| Actual paper lifecycle | Broker acceptance, terminal fill, and cancellation attempt/outcome are recorded with reconciled totals | BB-018 | Not run |
| Order failure drills | Timeout, unknown outcome, partial fill, duplicate/reordered events, and cancel/fill race preserve bounded exposure | BB-018, BB-020, BB-023 | Not run |
| Scheduled operation | One actual eligible paper cycle completes with pinned release and correct decision/execution timing | BB-019 | Not run |
| Calendar/restart behavior | Holidays, shortened sessions, DST, missed sessions, and mid-cycle restarts follow the declared policy | BB-019 | Not run |
| Controls and incidents | Pause/cancel/close/resume and configured loss responses have distinct verified effects; incidents remain visible | BB-020, BB-021 | Not run |
| Release activation/rollback | Safe activation preserves in-progress cycle identity and reconciles outstanding orders; invalid artifacts block activation | BB-016, BB-019, BB-020 | Not run |
| Operational UI | Freshness, readiness, unresolved orders, actual account state, and command progress are visible without secret exposure | BB-021 | Not run |
| Backup/restore | A consistent backup restores separately, reproduces research, and cannot resume orders before current broker reconciliation | BB-022 | Not run |
| Health/resource behavior | An independent local check detects a dead/stale worker; bounded research does not prevent required cycle work | BB-006, BB-020, BB-023 | Not run |
| Complete walkthrough | A fresh operator can follow documented research, macro, training/review, and paper workflows | BB-024 | Not run |

## Required failure invariants

- Uncertain broker acceptance is reconciled before another potentially conflicting submission.
- Open/partial/unresolved orders remain included in exposure and are not treated as cancelled merely because a request was sent.
- A stale, missing, corrupt, or incompatible input does not silently produce a healthy current result.
- Restart cannot clear a manual pause, change a cycle's selected release, or replay an expired intention as fresh.
- A model or external document cannot change risk limits, credentials, evaluation criteria, or execution mode.
- Synthetic, retrospective exploratory, shadow, and actual paper outputs remain distinguishable through reports and UI.
- Referenced snapshots, selected releases, and the rollback version survive normal retention and recovery operations.

## What does not establish completion

A passing mocked broker test, a saved screenshot, a successful model import, valid JSON, a positive backtest, or a statement that an integration should work does not replace the mandatory evidence above. External session/account constraints must be reported as pending rather than ignored. Continue independent checks while an external prerequisite is unavailable.

Investment outperformance and semantic model usefulness remain experimental findings. It is acceptable to reject the numerical/hybrid candidate and execute a valid baseline, provided real extraction/training/evaluation and selection workflows work and their limitations are visible. The application must not hide failed model qualification or invent successful evidence to satisfy release criteria.
