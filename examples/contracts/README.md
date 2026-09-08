# Synthetic contract examples

Run from the repository root:

```bash
uv run --locked --offline python examples/contracts/validate.py
```

- `experiment.json`: explicit synthetic research specification and illustrative data/model references.
- `context.json`: completed raw/feature observations, two synthetic source documents, a historical exploratory assessment, and current/pending exposure bound to that specification.
- `targets.json`: a 50% SPY allocation record to validate; no order is sent.
- `execution-event.json`: a synthetic four-of-ten partial fill, preserving the earlier native event time.
- `validate.py`: validates all records, demonstrates the all-cash strategy protocol, and allocates two different run IDs for the same specification.

These examples are fabricated schema inputs. SPY prices, documents, model/data identifiers and execution activity are not market evidence. The illustrative digests do not refer to published snapshots or trained model files. The example specification's code-content digest labels the demonstration rather than a runnable release. `https://example.invalid` URLs are never fetched.

The validator reports equity of **$2,070** ($1,000 cash + 10 × $105 shares + $20 receivable) and spendable cash of **$780** ($1,000 − $220 reserved). The demonstration policy returns all cash; it does not use the example target to submit trades. No files or jobs are created by `new_run`.

See [the contract guide](../../docs/contracts.md) for units, time eligibility, canonical identity and versioning. Actual snapshot validation and storage begin in BB-004.
