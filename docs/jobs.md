# Durable local jobs

BB-006 provides a small local SQLite job queue for work that may outlive a browser request or a worker process. It currently accepts one deliberately harmless job kind, `research_probe`, used to verify the lifecycle without data, model, broker, or network access. Future research handlers must be explicitly added and preserve the same boundary; generic jobs cannot carry broker commands.

## Commands

All commands emit JSON and use the selected configuration's `paths.state` and `paths.artifacts` directories.

```bash
uv run --locked --offline buffetbot jobs submit --request examples/jobs/research-probe.json
uv run --locked --offline buffetbot jobs list
uv run --locked --offline buffetbot worker status
uv run --locked --offline buffetbot worker once
uv run --locked --offline buffetbot jobs show <request_id>
uv run --locked --offline buffetbot jobs cancel <request_id>
uv run --locked --offline buffetbot worker shutdown
uv run --locked --offline buffetbot worker resume
uv run --locked --offline buffetbot worker serve
```

`submit` validates a versioned request containing stable UUID request and run IDs. Repeating the same request ID with identical run, kind, and payload returns the original record; changing its meaning is rejected. Jobs progress through `queued`, `running`, `succeeded`, `failed`, `interrupted`, or `cancelled`. A cancellation stops queued work immediately and asks a running child to stop; the terminal record tells the operator what happened.

## Storage, publication, and recovery

`state/jobs.sqlite3` holds job records, state-transition events, and the persisted shutdown flag. The store uses numbered SQLite migrations and `PRAGMA user_version`. A pre-migration SQLite backup is written as `jobs.pre-v<old>-to-v<new>.sqlite3`; a database from a newer schema is rejected. Claims and all updates use short `BEGIN IMMEDIATE` transactions. A locked database is retried twice after 50 ms and 100 ms, then returns a recoverable busy result without a partial update.

The worker claims only queued work. At startup it marks any previous `running` research job as `interrupted` with `worker_restarted`; it never retries that job automatically. This conservative behavior is intentional because later broker/order flows must reconcile their own durable identities and cannot use research retry logic.

The worker writes a child result or diagnostic JSON to `artifacts/jobs/<request-id>/`. It fsyncs a staging file, renames it, fsyncs the directory, rereads it, hashes it, and only then records `succeeded`. A publication failure records a diagnostic when storage permits and never produces a successful job record.

## Worker boundary

The worker holds a non-blocking operating-system lock at `state/worker.lock` for its entire `once` or `serve` operation. A second worker for the same state directory exits with a busy response. The lock is process-held, so the operating system releases it after an owner dies; spawned research children do not receive the lock descriptor.

At most one research child runs. Children start with a small environment allowlist (`LANG`, `LC_ALL`, `PATH`, `SYSTEMROOT`, `TERM`, `TZ`), with all broker variables excluded. They have a 35-second wall-clock limit and a 30-second CPU limit. The current probe performs only a bounded delay and writes a synthetic record. `worker status`, job inspection, cancellation, and shutdown require neither an LLM nor an open browser.

`worker shutdown` persists a request that prevents new claims. A running child observes it, terminates, and is recorded as interrupted. `worker resume` is explicit; restarting the process alone does not clear the shutdown request.

## Offline demonstration

```bash
uv run --locked --offline python examples/jobs/validate.py
```

The demonstration disables Python socket/DNS access, uses temporary state/artifact paths, submits the same synthetic request twice, runs it once, validates the published artifact and hash, and removes its temporary files. It does not contact a provider, start a model, or use credentials.
