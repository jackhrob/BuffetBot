# BB-001 — Project foundation and configuration

**Status:** Done  
**Depends on:** None  
**North Star:** Technical stack; product principles; operational boundaries

## User outcome

As the developer/operator, I can install and inspect BuffetBot without altering system Python, exposing credentials, or accidentally selecting live trading.

## Scope and simplest approach

Create one Python package under `src/buffetbot`, one project configuration, a locked environment, and a small command entry point. Establish directories for configuration, tests, local state, and generated artifacts. Use typed configuration and normal Python logging. Install dependencies needed by the first stories; add later dependencies as their features arrive.

Provide a documented offline/demo configuration and an example local secrets file containing placeholders only. This story provides the application boundary, not empty implementations of every planned component.

## Acceptance criteria

1. A documented command creates an isolated Python 3.12 environment from the lockfile and runs the command entry point from a clean checkout.
2. A configuration inspection/doctor command reports resolved paths, effective mode, required integrations, and missing prerequisites without making broker mutations or printing secret values.
3. Configuration distinguishes offline research from paper operation. Live broker configuration is rejected with an actionable error. Paper credentials are required only for commands that use the broker.
4. State and artifact paths are configurable, validated, and kept separate from source files. Secrets, local account state, downloaded data, and model artifacts are ignored by Git.
5. Logs provide timestamps, severity, component, and a run/job identifier when available. Known secret fields are redacted from configuration and error output.
6. Ruff and a minimal pytest invocation run through documented project commands. Tests verify configuration boundaries rather than asserting an empty package imports.
7. The README accurately describes implemented commands, installation prerequisites, and current limitations; planned commands are not presented as working.

## Verification

- Install and run the doctor command in a fresh virtual environment.
- Exercise missing optional integration credentials, malformed paths, and a requested live mode; verify the expected distinct outcomes.
- Place a recognizable dummy secret in configuration and verify it is absent from captured logs and error output.

## Completion evidence

Record environment/lockfile details, setup and check commands, and their results. Demonstrate the offline invocation without account credentials. No external account connection or model download is required for this story.

## Handoff and limits

BB-002 uses this environment to qualify the engine. Use ordinary modules and functions; defer plugin frameworks, hosted configuration, authentication systems, and unrelated scaffolding.

## Completion record

Implemented September 7, 2026. [Verification evidence](evidence/BB-001.md) records the fresh isolated setup, 39 passing tests, Ruff checks, offline operation without credentials, configuration boundaries, and Git exclusions. No broker or model integration was exercised or claimed.
