# BB-006 — Durable jobs and worker lifecycle

**Status:** Not started  
**Depends on:** [BB-001](01-project-foundation.md), [BB-003](03-contracts-and-experiments.md), [BB-004](04-dataset-snapshots.md)  
**North Star:** Process boundaries; persistent state; recovery

## User outcome

As an operator, I can submit and inspect work without losing its state on refresh or restart, and research cannot block the trading worker.

## Scope and simplest approach

Use SQLite transactions, numbered migrations, and a small durable jobs table. Run one worker with a bounded number of ordinary research child processes. Use a process-held OS file lock on the shared local state path to exclude a second worker for this deployment. The MVP does not need distributed leases or a separate queue service.

## Acceptance criteria

1. Durable jobs have stable request/run IDs, validated inputs, queued/running/succeeded/failed/interrupted or cancelled state, timestamps, progress, and artifact references. Repeating the same UI request identifier does not enqueue duplicate work.
2. Claim/update jobs transactionally. Define a bounded response to SQLite contention; interrupted writes do not leave half-persisted state.
3. On restart, identify abandoned research jobs and explicitly resume from a proven checkpoint or mark them interrupted. Do not reexecute a partially completed broker command using generic research-job retry logic.
4. Publish manifests/artifacts atomically before marking success. A failed child leaves diagnostic evidence and cannot publish a successful report.
5. Acquire the worker lock before order-capable operation and hold it for the worker lifetime. Children must not inherit ownership that prevents recovery. A second worker using the same state directory exits clearly; lock release after process death is verified.
6. Launch research children with an allowlisted environment that excludes broker secrets. Bound CPU/process concurrency and inference timeouts so large jobs do not starve event handling.
7. Expose worker health and job state without depending on an LLM or an open browser. Shutdown requests stop new job starts and preserve interrupted work honestly.
8. Migrations are explicit and transactional where supported, versioned, and backed up before incompatible changes. Unsupported newer schemas fail clearly.

## Verification

- Submit the same request twice, kill a child during publication, and restart the worker with running jobs in storage.
- Start two workers against the same directory; verify one owner and successful restart after its death.
- Use a dummy credential and confirm a research child cannot read it; run a slow job while checking worker responsiveness.

## Completion evidence

Provide schema/migration notes, lifecycle tests, lock behavior evidence, and an example failed/interrupted job record. Document that multiple independent deployments against one broker account are unsupported.

## Handoff and limits

Later stories register concrete job handlers. Keep broker order recovery inside the engine/adapter path, not a generalized task retry framework.
