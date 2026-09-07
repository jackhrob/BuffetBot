# BB-013 — Local LLM extraction and evaluation

**Status:** Not started  
**Depends on:** [BB-003](03-contracts-and-experiments.md), [BB-006](06-jobs-and-worker.md), [BB-012](12-macro-data.md)  
**North Star:** Evidence-backed macro analysis; measured model quality

## User outcome

As a researcher, I can inspect a local model's interpretation of two statements alongside the exact evidence and a measured quality report.

## Scope and simplest approach

Use the existing Ollama service and start with one installed general-purpose model. Implement a small provider function for structured extraction, local output caching, and evaluation. Supply selected text directly; no agent framework, tool-using model, vector database, or fine-tuning pipeline is required.

## Acceptance criteria

1. Given immutable statement references, request defined categories for policy direction and changes in stated concerns. Support unchanged, ambiguous, and unknown outcomes rather than forcing a directional answer.
2. Record model digest, prompt/schema versions, source hashes, parameters, actual generation time, source cutoff, response, latency, and error status. A mutable model alias cannot silently replace the model associated with a saved run.
3. Validate schema, allowed categories, supporting source IDs/spans, length bounds, and expiry. A source span must exist in the supplied text; plausible fabricated citations are invalid.
4. Run with bounded inputs, timeout, and retry policy. Preserve unavailable/malformed/unsupported responses distinctly; they cannot become neutral market observations by default.
5. Cache on the full effective input/model/prompt configuration. Replays load stored outputs. New prompts, models, or source revisions create new assessment identities.
6. Treat documents as data and provide no broker credentials, execution tools, or shell authority. Embedded instructions cannot alter output permissions or application configuration.
7. Create a small labelled evaluation set with independently reviewed expected interpretations and source evidence, including conditional, unchanged, conflicting, and missing-context cases. Record label/reviewer provenance; the tested model cannot generate its own supposed independent ground truth.
8. Report interpretation accuracy by category, evidence support, unknown/invalid rates, runtime, and failures. Declare any qualification thresholds before final evaluation; retain a failed candidate honestly. A valid schema alone is not a semantic-quality pass.
9. Complete an actual Ollama invocation against a real statement pair and show its evidence through a CLI/artifact view. Fixture responses support offline tests but cannot substitute for this invocation.

## Verification

- Replay recorded valid/invalid responses and exercise timeout, wrong model identity, unsupported spans, and document instructions.
- Run the fixed labelled set with the pinned local model and preserve individual outputs as well as aggregate scores.
- Restart the service/client and confirm saved historical results remain reproducible without new inference.

## Completion evidence

Provide actual invocation metadata, model evaluation artifacts, label provenance, fallback behavior, and supported-span checks. Report historical training-cutoff uncertainty explicitly.

## Handoff and limits

BB-014 defines how qualified assessments affect an experimental allocation policy. Poor model quality can lead to rejection; neither fine-tuning nor a profitable model is required to complete this honest evaluation workflow.
