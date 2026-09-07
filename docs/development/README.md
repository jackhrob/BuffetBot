# BuffetBot MVP development backlog

This backlog turns the reviewed [North Star](../../NORTHSTAR.md) into 24 implementation stories. **BB-001 and BB-002 are complete** with [foundation evidence](evidence/BB-001.md) and [engine qualification evidence](evidence/BB-002.md). BB-003 through BB-024 are **not started**. The local foundation and synthetic engine experiments are verified; production trading/model integration and actual paper operation remain future work.

The objective is a solid, stable MVP with the least technical complexity needed to meet its requirements. Development speed, story points, and estimates do not determine scope. Correctness, understandability, and a demonstrably working product do.

## How to use this backlog

Read the North Star, this index, and the relevant story before implementing. Stories are listed in a recommended order; their explicit dependencies determine readiness. A dependency means its required behavior must exist, not that every unrelated task must wait. Start with BB-001 and the bounded engine evaluation in BB-002.

Each story specifies its user outcome, implementation boundaries, observable acceptance criteria, verification, and completion evidence. Update its status as work progresses: **Not started**, **In progress**, **Blocked**, or **Done**. Record the actual missing prerequisite when blocked, and continue independent work. Routine implementation decisions within the reviewed direction do not require a new approval step for each story.

Do not mark a story done because code exists, a mocked request passed, or an external test was skipped. Preserve the evidence requested by the story. A functioning offline path is valuable but is not a substitute for the required external integration checks.

## Keep implementation simple

- Use one Python package, Streamlit, one worker, isolated research child processes, and the existing Ollama service. A research child is an ordinary local process, not a separately deployed service.
- Use SQLite through a small set of storage functions and explicit migrations. Use files for snapshots/artifacts and DuckDB for analytical queries. Avoid a second operational database or a separate message broker.
- Keep the trading engine responsible for its order lifecycle. Add narrow adapters and an audit trail; do not build another trading engine or an event-sourcing framework.
- Use ordinary functions and a few typed records. Add an interface only at a real boundary: strategy, data source, engine/broker, or model provider. No dynamic plugin discovery or dependency-injection framework is required.
- Support one operator, one deployment on one host, one executing worker, one paper account, and one executing strategy. Use a process-held operating-system lock on the shared local state directory to exclude a second worker; do not introduce distributed coordination.
- Keep the single-host dashboard local. Multi-user accounts, public hosting, additional brokers, Kubernetes, Redis, a separate REST backend, and distributed training are outside this backlog.
- Start with fixed strategy policies, one simple numerical estimator, one local model, a small declared universe, and bounded experiments. Avoid broad optimizers and autonomous code generation.
- Add dependencies only for a concrete requirement. Prefer existing engine/library behavior, the standard library, and small explicit implementations to generalized infrastructure.
- Write tests for behavior that matters. Reuse shared accounting fixtures and broker failure scenarios rather than building redundant test frameworks or asserting that historical profits must be positive.

## Story index and dependencies

All 24 stories are required for the MVP. The first usable research workflow is BB-001 through BB-011. Paper adapter discovery can begin after its dependencies without waiting for all model work.

| ID | Story | Depends on | Delivery area |
| --- | --- | --- | --- |
| BB-001 | [Project foundation and configuration](01-project-foundation.md) — Done | None | Foundation |
| BB-002 | [Trading engine qualification](02-engine-qualification.md) — Done | BB-001 | Foundation |
| BB-003 | [Shared contracts and experiment specification](03-contracts-and-experiments.md) | BB-001, BB-002 | Foundation |
| BB-004 | [Dataset snapshots, quality checks, and fixtures](04-dataset-snapshots.md) | BB-003 | Research |
| BB-005 | [Historical market data ingestion](05-market-data-ingestion.md) | BB-004 | Research |
| BB-006 | [Durable jobs and worker lifecycle](06-jobs-and-worker.md) | BB-001, BB-003, BB-004 | Foundation |
| BB-007 | [Benchmark and numerical strategy policies](07-strategy-policies.md) | BB-003, BB-004 | Research |
| BB-008 | [Portfolio limits and order planning](08-portfolio-risk.md) | BB-003, BB-007 | Research and operations |
| BB-009 | [Backtest execution and accounting](09-backtest-accounting.md) | BB-002, BB-004, BB-006, BB-007, BB-008 | Research |
| BB-010 | [Reproducible reports and comparisons](10-reports-and-comparisons.md) | BB-009 | Research |
| BB-011 | [Research dashboard](11-research-dashboard.md) | BB-005, BB-006, BB-010 | Research |
| BB-012 | [Macro documents and historical releases](12-macro-data.md) | BB-004, BB-006 | Macro analysis |
| BB-013 | [Local LLM extraction and evaluation](13-llm-extraction.md) | BB-003, BB-006, BB-012 | Macro analysis |
| BB-014 | [Hybrid comparison and prospective shadow runs](14-hybrid-and-shadow.md) | BB-007, BB-008, BB-010, BB-011, BB-013 | Hybrid research |
| BB-015 | [Numerical candidate training](15-candidate-training.md) | BB-005, BB-006, BB-007, BB-009, BB-010 | Machine learning |
| BB-016 | [Candidate review and release selection](16-candidate-selection.md) | BB-011, BB-014, BB-015 | Machine learning |
| BB-017 | [Paper broker connection and reconciliation](17-paper-broker.md) | BB-002, BB-003, BB-006, BB-008 | Paper operations |
| BB-018 | [Paper order execution and recovery](18-paper-order-lifecycle.md) | BB-008, BB-009, BB-017 | Paper operations |
| BB-019 | [Scheduled paper trading cycle](19-scheduled-paper-trading.md) | BB-005, BB-007, BB-014, BB-016, BB-018 | Paper operations |
| BB-020 | [Operational controls and failure handling](20-operational-controls.md) | BB-018, BB-019 | Paper operations |
| BB-021 | [Paper operations dashboard](21-operations-dashboard.md) | BB-011, BB-016, BB-017, BB-019, BB-020 | Operations UI |
| BB-022 | [Local deployment, backup, and restore](22-deployment-and-restore.md) | BB-011, BB-013, BB-016, BB-020, BB-021 | Delivery |
| BB-023 | [Integrated verification and failure drills](23-integrated-verification.md) | BB-014, BB-015, BB-018, BB-020, BB-021, BB-022 | Release validation |
| BB-024 | [MVP release and operating guide](24-mvp-release.md) | BB-023 | Release |

## Requirements coverage

| North Star requirement | Primary stories |
| --- | --- |
| Engine choice, locked environment, narrow architecture | BB-001–BB-003, BB-006, BB-022 |
| Historical data, revisions, timestamps, reproducible snapshots | BB-004, BB-005, BB-012 |
| Shared strategies, realistic costs, corporate actions, limits | BB-007–BB-010 |
| Experiments and visible provenance | BB-010, BB-011, BB-014 |
| Macro evidence and local model quality | BB-012–BB-014 |
| Chronological ML evaluation and controlled candidate selection | BB-015, BB-016 |
| Single paper account, order lifecycle, scheduling, recovery | BB-017–BB-020 |
| Operator visibility and controls | BB-011, BB-016, BB-020, BB-021 |
| Repeatable setup, backups, actual integration evidence | BB-022–BB-024 |

## Completion and evidence rules

A completed story has working behavior, satisfied acceptance criteria, proportionate verification, current user/developer instructions where relevant, and a short evidence record. Include the code revision, configuration, commands, and result/artifact paths. Redact secrets and account identifiers from shareable evidence.

Use **Passed**, **Failed**, **Not run**, or **Blocked** for each required check. State whether evidence uses synthetic fixtures, recorded external responses, current external data, or the actual broker paper environment. These labels must survive into the dashboard and release report.

The detailed [release acceptance checklist](release-acceptance.md) is the final check against a superficially complete MVP. BB-024 is done only when all mandatory release checks pass. A rejected model can satisfy the learning workflow if it is correctly evaluated and recorded; fabricated performance or an untested broker path cannot satisfy release acceptance.

## Decisions deliberately left to implementation

The implementation must record a small ETF universe, fixed strategy settings, simulated initial capital, cost assumptions, and an order convention supported by the selected engine and broker. These are simulation choices. Determine them before comparing results and preserve them in each experiment specification.

Qualify one engine and one installed model first. If a required engine behavior fails, document the evidence and choose the smallest viable alternative behind the same contracts. Do not use an unresolved engine choice to expand the platform. API account access and model weights are external prerequisites; support the offline path while recording precisely what remains unverified.

Live trading, language-model fine-tuning, automatic model promotion, additional asset classes, and multiple executing strategies remain later work. They are not prerequisites to this MVP.
