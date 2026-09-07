"""Internal child entry point. Always launch using `python -m qualification`."""

import hashlib
import importlib.metadata
import json
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

NETWORK_ATTEMPTS = []


def deny_network(*args, **kwargs):
    NETWORK_ATTEMPTS.append("attempt")
    raise RuntimeError("Network access is forbidden during BB-002 qualification")


def main():
    # Guard before importing engine/model libraries. A swallowed attempt still fails the run.
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network

    from qualification.adapters import completed_features, validate_order
    from qualification.backtest import (
        FIXTURES,
        check_ledger,
        load_fixture,
        run_backtest,
        save_model,
    )
    from qualification.paper import qualify_paper

    assert importlib.metadata.version("lumibot") == "4.5.91"
    model_path = Path("pipeline.joblib")
    outside_model = save_model(model_path)
    native = run_backtest(model_path, corrected=False)
    first = run_backtest(model_path)
    second = run_backtest(model_path)
    check_ledger(first)
    assert first == second, "Repeated backtests differ"
    assert abs(native["cash"] - 10095.70) < 1e-6
    assert not any(e["status"] == "dividend" for e in native["events"])
    no_spread = run_backtest(model_path, spread=False)
    assert no_spread["cash"] == 10118.0
    assert [e["price"] for e in no_spread["events"] if e["status"] == "fill"] == [110.0, 60.0]

    errors = []
    for decision in first["decisions"]:
        outside = float(outside_model.predict([[decision["feature_close"]]])[0])
        errors.append(abs(outside - decision["prediction"]))
    assert max(errors) <= 1e-12
    bars, features, _, schedule = load_fixture()
    # Poison every future feature; eligible context must be unchanged.
    cutoff = bars.index[1]
    changed = features.copy()
    changed.loc[changed.available_at >= cutoff, "feature_close"] = 999999.0
    changed.loc[changed.available_at >= cutoff, "instruction"] = "sell"
    assert completed_features(features, cutoff, bars.stock_splits).equals(
        completed_features(changed, cutoff, bars.stock_splits)
    )
    assert first["decisions"][0]["feature_close"] == 105
    assert first["snapshots"][1]["native_last_price"] == 112
    assert first["snapshots"][1]["native_history_close"] == 112
    # July 2 feature becomes 56 only when July 3's split has become effective.
    assert first["decisions"][1]["feature_close"] == 56
    # Buying on the ex-date must not create an entitlement; sale quantity is in post-split units.
    ex_entry_features = features.copy()
    ex_entry_features["instruction"] = "hold"
    ex_entry_features.loc[ex_entry_features.session == "2024-07-03", "instruction"] = "buy"
    ex_entry_features.loc[ex_entry_features.session == "2024-07-05", "instruction"] = "sell"
    ex_entry = run_backtest(model_path, feature_override=ex_entry_features)
    # Native stock fill prices round to cents: 56 * 1.001 becomes 56.06.
    assert abs(ex_entry["cash"] - 10036.80) < 1e-6, ex_entry
    assert ex_entry["events"][0]["price"] == 56.06
    assert not any(e["status"] == "dividend" for e in ex_entry["events"])
    expected_failures = []
    try:
        run_backtest(Path("missing.joblib"))
    except FileNotFoundError:
        expected_failures.append("missing_model")
    for config in [("limit", "day", False), ("market", "gtc", False), ("market", "day", True)]:
        try:
            validate_order(*config)
        except ValueError:
            expected_failures.append(str(config))
    assert len(expected_failures) == 4
    # Ensure the same ledger validator catches an extra dividend and same-close fill.
    for corruption in ("dividend_twice", "same_close"):
        wrong = json.loads(json.dumps(first))
        if corruption == "dividend_twice":
            wrong["cash"] += 20
        else:
            wrong["events"][0]["price"] = 105
            wrong["events"][0]["time"] = "2024-07-01T16:00:00-04:00"
        try:
            check_ledger(wrong)
        except AssertionError:
            expected_failures.append(corruption)
    assert len(expected_failures) == 6
    paper = qualify_paper()
    assert not NETWORK_ATTEMPTS, "A dependency attempted networking"

    root = FIXTURES.parents[1]
    source_files = [root / "pyproject.toml", root / "uv.lock"]
    source_files += sorted((root / "qualification").rglob("*.py"))
    source_files += sorted((root / "src").rglob("*.py"))
    source_files += sorted((root / "tests").rglob("*.py"))
    source_files += sorted(FIXTURES.iterdir())
    hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files
    }
    engine = importlib.metadata.distribution("lumibot")
    license_file = next(p for p in engine.files if str(p).endswith("licenses/LICENSE"))
    license_bytes = engine.locate_file(license_file).read_bytes()
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    report = {
        "story": "BB-002",
        "decision": "Adopt Lumibot 4.5.91 with demonstrated narrow adapters",
        "verified_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "base_revision": revision,
        "engine_metadata": {
            "version": engine.version,
            "requires_python": engine.metadata["Requires-Python"],
            "metadata_license": engine.metadata["License"],
            "shipped_license_header": license_bytes.decode().splitlines()[:2],
            "shipped_license_sha256": hashlib.sha256(license_bytes).hexdigest(),
            "direct_dependencies": engine.requires,
        },
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "source_hashes": hashes,
        "network_attempts": 0,
        "repeated_ledgers_equal": True,
        "native": native,
        "corrected": first,
        "without_spread_cash": no_spread["cash"],
        "ex_date_entry_cash": ex_entry["cash"],
        "model": {
            "kind": "StandardScaler + Ridge; synthetic serialization probe",
            "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "max_absolute_prediction_error": max(errors),
            "tolerance": 1e-12,
        },
        "expected_failures": expected_failures,
        "future_feature_mutation": "Passed",
        "calendar": {
            "sessions": schedule.index.strftime("%Y-%m-%d").tolist(),
            "july_3_close": schedule.loc["2024-07-03", "market_close"].isoformat(),
        },
        "paper": paper,
    }
    Path(sys.argv[1]).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
