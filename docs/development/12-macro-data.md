# BB-012 — Macro documents and historical releases

**Status:** Not started  
**Depends on:** [BB-004](04-dataset-snapshots.md), [BB-006](06-jobs-and-worker.md)  
**North Star:** Macro evidence; publication timing; historical revisions

## User outcome

As a researcher, I can inspect original macro sources and know which version was eligible at a particular decision time.

## Scope and simplest approach

Support official central-bank statements and a small declared set of FRED/ALFRED series. Use bounded source-specific fetchers, normal text parsing, and local immutable storage. A supplied URL/list or official publication index is sufficient; a web-browsing agent or general crawler is unnecessary.

## Acceptance criteria

1. Store original document content, canonical source reference, publication time when known, first observation time, content hash, and extraction/parser version. Preserve revisions as separate versions.
2. Identify the comparison pair for a statement assessment explicitly. A later revision cannot silently replace the text previously supplied to a model.
3. Store macro series identifiers, observation dates, release/vintage information, availability convention, units, and source records. Historical joins select the value actually eligible at the cutoff, not today's latest revision.
4. Do not treat a vintage date as proof of an intraday release time. Use a documented conservative availability rule where needed; flag unknown publication/revision histories and restrict or label affected historical experiments.
5. Capture ingestion failures, unchanged content, parser failures, missing releases, and unsupported formats honestly. Reads have bounded retries, caching, and explicit credential/entitlement errors.
6. Publish documents/series through the snapshot discipline in BB-004 and expose a simple as-of retrieval function for strategy/model inputs.
7. Include fixtures demonstrating an original release, later revision, missing timestamp, changed statement, duplicate ingestion, and an unchanged statement.
8. Ingest at least one real statement pair and one actual vintage-aware macro series range, verify selected source values and timestamps, and record remaining limitations. Fixture-only evidence does not complete the source integration.

## Verification

- Query the same observation before and after its revision; verify different eligible values without future information entering the earlier result.
- Re-fetch unchanged content and verify duplicate detection; re-fetch changed content and verify the prior version survives.
- Verify real-source ingestion and offline replay while keeping credentials out of artifacts.

## Completion evidence

Provide redacted source requests, document/series hashes, timestamp/availability policy, as-of query examples, and actual-ingestion results.

## Handoff and limits

BB-013 receives selected immutable documents, not unrestricted internet access. Financial news vendors, embeddings, vector databases, and a universal document ingestion platform are outside this story.
