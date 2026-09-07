# BB-022 — Local deployment, backup, and restore

**Status:** Not started  
**Depends on:** [BB-011](11-research-dashboard.md), [BB-013](13-llm-extraction.md), [BB-016](16-candidate-selection.md), [BB-020](20-operational-controls.md), [BB-021](21-operations-dashboard.md)  
**North Star:** Quick repeatable deployment; persistent state; simple infrastructure

## User outcome

As the operator, I can install, start, stop, back up, and recover BuffetBot using documented commands on one local host.

## Scope and simplest approach

Provide a locked native setup and a Docker Compose setup for the same dashboard and worker. Use mounted state/artifact directories, the existing local Ollama service, and a simple local supervisor/health check. Do not package unrelated infrastructure or modify existing models/workloads unnecessarily.

## Acceptance criteria

1. Document actual setup/start/stop/check commands and supported runtime assumptions. A clean environment can run the synthetic demo without broker credentials or external network access after dependencies are provisioned.
2. Compose runs only the required application processes, preserves state/artifacts across recreation, and uses the same configuration/contracts as native execution. The worker lock works across processes/containers sharing the documented state directory.
3. Bind UI/control interfaces locally by default. Supply broker secrets only to the order-capable worker; its research children still receive the allowlisted environment from BB-006.
4. Demonstrate the container-to-existing-Ollama connection on the supported host. Record model/host requirements and handle missing inference explicitly; do not secretly replace real inference with fixture output.
5. Startup validates schema/configuration and resumes in paused/reconciling state as appropriate. Shutdown and supervisor restart preserve incomplete jobs and uncertain orders honestly.
6. Back up SQLite using a consistent method and include referenced immutable artifacts/manifests, selected releases, and configuration metadata. Exclude secrets by default and document how credentials are restored separately.
7. Restore into a separate directory, verify checksums/schema/model references, reproduce a research run, and confirm paper operation remains non-submitting until the current broker account is reconciled. An old backup is not proof of current holdings.
8. Define local log/artifact retention with simple limits. Do not delete selected/previous releases or files referenced by preserved runs. Disk-full, permission-denied, and missing-volume errors are visible and do not produce successful jobs.
9. Document migration and rollback procedure, the independent health-check invocation, and the limitations of monitoring from the same host.

## Verification

- Run the demo from a fresh environment and fresh Compose volumes, then recreate containers and verify persistence.
- Back up during a supported safe state, restore separately, and replay a saved experiment.
- Exercise missing volume permissions, absent Ollama, and mismatched restored account identity without exposing credentials or sending orders.

## Completion evidence

Provide native/container command results, dependency/model requirements, backup manifest, restore/replay evidence, and recovery instructions.

## Handoff and limits

One host and one deployment remain the supported topology. No Kubernetes, remote object store, distributed database, bundled model-training cluster, or public hosting is needed.
