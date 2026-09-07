# BB-011 — Research dashboard

**Status:** Not started  
**Depends on:** [BB-005](05-market-data-ingestion.md), [BB-006](06-jobs-and-worker.md), [BB-010](10-reports-and-comparisons.md)  
**North Star:** Experiment user experience; simple local architecture

## User outcome

As the owner, I can run, compare, and inspect research from a local browser without editing application code.

## Scope and simplest approach

Use Streamlit as a view and command-request client. Read the same SQLite/artifact records used by the CLI, and enqueue validated requests through BB-006. Keep strategy calculations and report math out of widget callbacks.

## Acceptance criteria

1. Provide an experiment form for available snapshots, strategy, date range, initial simulated capital, and permitted settings. Show coverage, origin, and warmup constraints before submission.
2. Validate the form through BB-003; errors are specific and preserve the user's inputs. Only implemented/supported policies and execution conventions appear as runnable choices.
3. Submission returns a durable job ID and displays queued/running/completed/failed/interrupted state. Refresh, reconnect, and repeated delivery of one request cannot duplicate execution; a deliberate rerun receives a new run ID.
4. View reports, benchmark comparisons, equity/drawdown plots, reasons, and trade ledgers using BB-010 artifacts. Export the relevant report/ledger without a second calculation path.
5. Display synthetic/market-data origin, historical mode, data dates, versions, costs, and incomplete/mismatched comparisons visibly. Missing artifacts or failed jobs show a useful recovery path.
6. A small actual-data experiment and an offline fixture experiment can each be completed from the UI. Their result labels remain distinct.
7. The UI stays responsive while a research job runs and can show worker unavailable/stale state. Closing the browser does not stop durable work or lose its record.
8. The process binds locally by default, cannot call broker order methods, and does not expose local secrets through settings, exception screens, exports, or arbitrary filesystem paths.

## Verification

- Exercise one complete browser flow with the offline fixture and one real downloaded snapshot.
- Submit/refresh/reconnect while a slow job runs; verify a single job for the original request and persistent results after closing the browser.
- Check malformed inputs, missing worker, failed run, and missing artifact behavior using focused UI tests and a documented manual walkthrough.

## Completion evidence

Provide the walkthrough, job/run IDs, report paths, and UI verification results. A screenshot alone is insufficient to establish working behavior.

## Handoff and limits

This is the first usable research release. Add macro and operations views in their respective stories. No separate frontend build, user-account system, or API server is required.
