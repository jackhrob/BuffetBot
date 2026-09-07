# BB-024 — MVP release and operating guide

**Status:** Not started  
**Depends on:** [BB-023](23-integrated-verification.md)  
**North Star:** Definition of done; usable local product; explicit limits

## User outcome

As the owner, I can install and operate the completed MVP from its documentation, understand what has been verified, and continue research without relying on the development conversation.

## Scope and simplest approach

Finalize the local release, README, example configuration, operating guide, and acceptance evidence. Keep documentation in the repository alongside the small release manifest. No release-management service, hosted deployment, or public publication is required.

## Acceptance criteria

1. Every MVP story is complete with supporting evidence, and all mandatory checks in [release acceptance](release-acceptance.md) pass. Missing broker credentials, unavailable real model inference, or skipped actual integration tests leave release readiness incomplete.
2. The README provides the shortest verified path from a clean setup to the offline demo, a real-data backtest, macro analysis, candidate training/review, and configured paper operation. Commands shown as available actually work.
3. The operating guide covers required accounts/data entitlements, secret configuration, selected model, supported universe/order rules, schedules, freshness, manifests, report meanings, and known simulator/model limitations.
4. Explain pausing, cancelling, closing managed positions, resuming, release activation/rollback, uncertain orders, broker outages, account resets, and backup/restore with their actual effects. Include recovery checks before order-capable resumption.
5. Supply a short acceptance walkthrough that exercises all four product workflows: experiments, macro evidence, candidate comparisons, and paper operation. A fresh environment can follow it without hidden local state or instructions from chat.
6. Record source revision or source-content identity, locked dependencies, data/demo hashes, prompt/model identities, schema version, external verification dates, and evidence paths. The selected engine/model are the ones actually tested.
7. Show operating costs and external requirements honestly. Local inference/demo support cannot be described as current market access without the required data/account setup.
8. Keep live trading unavailable in the released MVP. Separate any proposed later capabilities—fine-tuning, automatic promotion, broader markets, or live capital—from implemented features.
9. Review the final implementation for unnecessary technical layers. Remove unused scaffolding/dependencies and duplicated logic when safe, then rerun affected checks. Document any material deviation from the reviewed architecture and why it was necessary.

## Verification

- Follow the operating guide from a clean setup using the released configuration and acceptance walkthrough.
- Cross-check claims in the README/dashboard against actual artifacts and the external verification record.
- Confirm the release checklist has evidence for every mandatory item and no incomplete story is presented as delivered.

## Completion evidence

Provide the release manifest, final story/check status, complete walkthrough result, operating guide, and explicit known limitations. A negative strategy/model result is acceptable when accurately evaluated and reported; missing product behavior is not.

## Handoff and limits

The release ends with a usable research and paper trading application. Subsequent investment evaluation and any live-capital release remain separate decisions; no public publishing or account funding is part of this story.
