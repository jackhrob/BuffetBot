"""Behavioral checks for time, units, evidence, exposure and reproducible identity."""

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from buffetbot.contracts import (
    ExecutionAuditEvent,
    FeatureObservation,
    MacroAssessment,
    MarketObservation,
    PortfolioState,
    PortfolioTargets,
    SourceDocument,
    StrategyContext,
    TargetWeight,
    validate_targets,
)
from buffetbot.experiments import (
    ExperimentManifest,
    ExperimentSpecification,
    canonical_json,
    experiment_id,
    new_run,
    validate_context,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/contracts"


def example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def changed(data, path, value):
    result = deepcopy(data)
    container = result
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value
    return result


def specimen():
    return ExperimentSpecification.model_validate(example("experiment"))


def context_manifest(context):
    return ExperimentManifest(
        schema_version=1,
        run_id=context.run_id,
        created_at="2026-09-07T00:00:00Z",
        experiment_id=context.experiment_id,
        specification=specimen(),
    )


@pytest.mark.parametrize(
    "model,data",
    [
        (ExperimentSpecification, example("experiment")),
        (StrategyContext, example("context")),
        (PortfolioTargets, example("targets")),
        (ExecutionAuditEvent, example("execution-event")),
        (MarketObservation, example("context")["observations"][0]),
        (FeatureObservation, example("context")["features"][0]),
        (SourceDocument, example("context")["documents"][0]),
        (MacroAssessment, example("context")["macro"]),
    ],
)
def test_v1_round_trips_and_requires_explicit_supported_version(model, data):
    record = model.model_validate(data)
    assert model.model_validate_json(canonical_json(record)) == record
    for version in (0, 2, "1", True, 1.0):
        with pytest.raises(ValidationError) as failure:
            model.model_validate(dict(data, schema_version=version))
        assert failure.value.errors()[0]["loc"] == ("schema_version",)
    missing = dict(data)
    del missing["schema_version"]
    with pytest.raises(ValidationError, match="schema_version"):
        model.model_validate(missing)


@pytest.mark.parametrize(
    "path,value",
    [
        (("decision_at",), "2024-07-01T20:15:00"),
        (("decision_at",), 1719864900),
        (("observations", 0, "available_at"), "2024-07-01T20:16:00Z"),
        (("observations", 0, "interval_end"), "2024-07-01T20:16:00Z"),
        (("observations", 0, "session"), "2024-07-02"),
        (("observations", 0, "first_ingested_at"), "2024-06-30T00:00:00Z"),
        (("observations", 0, "high"), "104"),
        (("observations", 0, "adjustment"), "total_return"),
        (("observations", 0, "symbol"), "QQQ"),
        (("observations", 0, "dataset_id"), "a" * 64),
        (("observations", 0, "volume"), 1.5),
        (("observations", 0, "volume"), True),
        (("features", 0, "available_at"), "2024-07-01T20:16:00Z"),
        (("features", 0, "adjusted_as_of"), "2024-07-01T20:16:00Z"),
        (("features", 0, "computed_at"), "2024-07-01T20:15:00Z"),
        (("features", 0, "available_at"), "2024-07-01T20:14:00Z"),
        (("features", 0, "feature_schema_id"), "different.v1"),
        (("features", 0, "dataset_id"), "b" * 64),
        (("portfolio", "as_of"), "2024-07-01T20:16:00Z"),
        (("portfolio", "holdings", 0, "marked_at"), "2024-07-01T20:16:00Z"),
        (("portfolio", "holdings", 0, "quantity"), "10"),
        (("portfolio", "holdings", 0, "quantity"), -1),
        (("portfolio", "pending_orders", 0, "symbol"), "QQQ"),
        (("universe", 0, "asset_class"), "crypto"),
        (("universe", 0, "currency"), "EUR"),
        (("universe", 0, "delisted_on"), "2024-07-02"),
        (("execution_at",), "2024-07-01T20:00:00Z"),
        (("execution_session",), "2024-07-03"),
        (("target_expires_at",), "2024-07-02T13:30:00Z"),
        (("strategy", "numerical_model", "trained_through"), "2024-07-01T20:15:00Z"),
        (("strategy", "numerical_model", "feature_schema_id"), "mismatched.v1"),
        (("macro", "expires_at"), "2024-07-01T20:15:00Z"),
        (("macro", "source_cutoff"), "2024-07-01T20:16:00Z"),
        (("macro", "source_document_ids"), ["missing"]),
        (("macro", "evidence", 0, "content_sha256"), "c" * 64),
        (("macro", "model", "artifact_sha256"), "mutable-model-alias"),
        (("documents", 0, "content_sha256"), "d" * 64),
        (("documents", 0, "published_at"), "2024-07-02T00:00:00Z"),
    ],
)
def test_context_rejects_ineligible_or_inconsistent_input(path, value):
    with pytest.raises(ValidationError):
        StrategyContext.model_validate(changed(example("context"), path, value))


def test_replay_distinguishes_public_availability_from_later_ingestion_and_generation():
    context = StrategyContext.model_validate(example("context"))
    assert context.observations[0].first_ingested_at > context.decision_at
    assert context.macro.generated_at > context.decision_at
    assert context.macro.use == "historical_exploratory"
    for mode in ("paper", "shadow"):
        with pytest.raises(ValidationError, match="Prospective"):
            StrategyContext.model_validate(dict(example("context"), mode=mode))


def prospective_context():
    data = example("context")
    data["mode"] = "paper"
    for item in data["observations"]:
        item["origin"] = "prospective"
        item["first_ingested_at"] = data["decision_at"]
    for item in data["features"]:
        item["computed_at"] = data["decision_at"]
    for item in data["documents"]:
        item["first_ingested_at"] = data["decision_at"]
    data["macro"]["generated_at"] = data["decision_at"]
    data["macro"]["use"] = "prospective"
    return data


def test_prospective_context_checks_actual_ingestion_computation_and_model_generation():
    valid = prospective_context()
    assert StrategyContext.model_validate(valid).mode == "paper"
    for path in [
        ("observations", 0, "first_ingested_at"),
        ("features", 0, "computed_at"),
        ("documents", 0, "first_ingested_at"),
        ("macro", "generated_at"),
        ("strategy", "numerical_model", "created_at"),
    ]:
        with pytest.raises(ValidationError):
            StrategyContext.model_validate(changed(valid, path, "2024-07-01T20:15:01Z"))
    expired = deepcopy(valid)
    expired["macro"].update(
        source_cutoff="2024-07-01T20:14:59Z",
        generated_at="2024-07-01T20:14:59Z",
        expires_at=valid["decision_at"],
    )
    with pytest.raises(ValidationError, match="expired"):
        StrategyContext.model_validate(expired)


def test_duplicate_data_and_missing_sources_cannot_enter_context():
    for key in ("universe", "observations", "features", "documents"):
        data = example("context")
        data[key].append(deepcopy(data[key][0]))
        with pytest.raises(ValidationError, match="unique"):
            StrategyContext.model_validate(data)
    data = example("context")
    data["documents"] = data["documents"][1:]
    with pytest.raises(ValidationError, match="Missing source document"):
        StrategyContext.model_validate(data)


def test_unicode_source_spans_are_exact_not_just_plausible_text():
    data = example("context")
    text = "Policy is unchanged. π"
    digest = hashlib.sha256(text.encode()).hexdigest()
    data["documents"][0].update(original_text=text, content_sha256=digest)
    data["macro"]["evidence"][0].update(text=text, content_sha256=digest, end=len(text))
    StrategyContext.model_validate(data)
    data["macro"]["evidence"][0]["text"] = text.replace("π", "x")
    with pytest.raises(ValidationError, match="span"):
        StrategyContext.model_validate(data)


def test_unknown_assessment_is_explicit_and_can_abstain_without_invented_evidence():
    data = example("context")
    data["macro"].update(policy_direction="unknown", concern_change="unknown", evidence=[])
    StrategyContext.model_validate(data)
    data["macro"]["policy_direction"] = "unchanged"
    with pytest.raises(ValidationError, match="evidence from both"):
        StrategyContext.model_validate(data)


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-Infinity", "-0.01", "1.01", "50%", 0.5, True, "0.123456789"]
)
def test_weights_reject_nonfinite_inexact_or_wrong_units(value):
    with pytest.raises(ValidationError) as failure:
        TargetWeight(symbol="SPY", weight=value)
    assert failure.value.errors()[0]["loc"] == ("weight",)


@pytest.mark.parametrize(
    "path,value",
    [
        (("initial_cash_usd",), "10000 USD"),
        (("initial_cash_usd",), 10000.0),
        (("initial_cash_usd",), 0),
        (("warmup_sessions",), 1.0),
        (("start_session",), "2024-07-02T00:00:00Z"),
        (("end_session",), "2024-07-01"),
        (("mode",), "live"),
        (("research_use",), "prospective"),
        (("engine_version",), "latest"),
        (("execution", "order_type"), "limit"),
        (("execution", "time_in_force"), "gtc"),
        (("execution", "executable_prices"), "adjusted"),
        (("cash_treatment", "dividends"), "ex_date_cash"),
        (("costs", "commission_per_order_usd"), "-1"),
        (("costs", "combined_spread_slippage_bps"), "10000"),
        (("datasets", 0, "schema_id"), "source_document.v1"),
        (("datasets", 0, "revision_policy"), "unknown"),
        (("datasets", 0, "dataset_id"), "missing-snapshot"),
        (("language_model",), None),
        (("strategy", "parameters", 0, "value"), {"hidden": "mutable config"}),
        (("strategy", "parameters", 0, "value"), 1.5),
        (("code_revision",), "main"),
        (("seed",), True),
    ],
)
def test_specification_rejects_unsupported_or_unreproducible_settings(path, value):
    with pytest.raises(ValidationError):
        ExperimentSpecification.model_validate(changed(example("experiment"), path, value))


def test_required_refs_and_parameters_cannot_be_silently_missing_or_duplicated():
    data = example("experiment")
    del data["datasets"][0]["dataset_id"]
    with pytest.raises(ValidationError, match="dataset_id"):
        ExperimentSpecification.model_validate(data)
    data = example("experiment")
    data["strategy"]["parameters"] *= 2
    with pytest.raises(ValidationError, match="parameter names"):
        ExperimentSpecification.model_validate(data)


def test_pending_exposure_uses_exact_cash_and_never_spends_dividend_receivables():
    portfolio = StrategyContext.model_validate(example("context")).portfolio
    assert portfolio.equity_usd == Decimal("2070")
    assert portfolio.spendable_cash_usd == Decimal("780")
    data = portfolio.model_dump(mode="json")
    data["pending_orders"][0]["reserved_cash_usd"] = "1001"
    with pytest.raises(ValidationError, match="receivables are not spendable"):
        PortfolioState.model_validate(data)
    data["pending_orders"][0]["reserved_cash_usd"] = "220"
    data["pending_orders"][1]["remaining_quantity"] = 11
    with pytest.raises(ValidationError, match="exceed held"):
        PortfolioState.model_validate(data)


def test_targets_bind_to_eligible_universe_strategy_run_and_cutoff():
    context = StrategyContext.model_validate(example("context"))
    target = PortfolioTargets.model_validate(example("targets"))
    assert validate_targets(context, target).cash_weight == Decimal("0.5")
    all_cash = PortfolioTargets.model_validate(dict(example("targets"), weights=[]))
    assert validate_targets(context, all_cash).cash_weight == 1
    for path, value in [
        (("weights", 0, "symbol"), "QQQ"),
        (("strategy_version",), "2"),
        (("experiment_id",), "a" * 64),
        (("run_id",), "f75bcb36-14c5-43b9-a624-e66ef6adf5da"),
        (("feature_cutoff",), "2024-07-01T20:14:00Z"),
        (("expires_at",), "2024-07-02T15:00:00Z"),
    ]:
        altered = PortfolioTargets.model_validate(changed(example("targets"), path, value))
        with pytest.raises(ValueError):
            validate_targets(context, altered)
    for weights in [
        [{"symbol": "SPY", "weight": "0.6"}, {"symbol": "QQQ", "weight": "0.6"}],
        [{"symbol": "SPY", "weight": "0.5"}, {"symbol": "SPY", "weight": "0.5"}],
    ]:
        with pytest.raises(ValidationError):
            PortfolioTargets.model_validate(dict(example("targets"), weights=weights))


def test_target_expiry_is_exclusive_and_validation_requires_an_aware_clock():
    context = StrategyContext.model_validate(example("context"))
    target = PortfolioTargets.model_validate(example("targets"))
    validate_targets(context, target, at=target.expires_at - timedelta(microseconds=1))
    for at in (target.expires_at, target.decision_at - timedelta(microseconds=1)):
        with pytest.raises(ValueError, match="future or expired"):
            validate_targets(context, target, at=at)
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_targets(context, target, at=datetime(2024, 7, 1, 20, 15))


def test_ordered_feature_schema_is_checked_even_when_schema_identifiers_match():
    for path, value in [
        (("strategy", "numerical_model", "feature_names"), ["different"]),
        (("features", 0, "values", 0, "name"), "different"),
    ]:
        with pytest.raises(ValidationError, match="names/order"):
            StrategyContext.model_validate(changed(example("context"), path, value))


def test_training_must_precede_the_decision_and_the_first_execution_session():
    data = example("context")
    data["strategy"]["numerical_model"].update(
        trained_through=data["decision_at"],
        created_at=data["decision_at"],
    )
    with pytest.raises(ValidationError, match="cutoff is not eligible"):
        StrategyContext.model_validate(data)
    data = example("experiment")
    data["strategy"]["numerical_model"].update(
        trained_through="2024-07-02T12:00:00Z",
        created_at="2024-07-02T12:00:00Z",
    )
    with pytest.raises(ValidationError, match="first execution session"):
        ExperimentSpecification.model_validate(data)


@pytest.mark.parametrize(
    "path,value",
    [
        (("status",), "filled"),
        (("cumulative_filled_quantity",), 11),
        (("fill_quantity_delta",), 5),
        (("fill_price_usd",), None),
        (("fill_quantity_delta",), 0),
        (("requested_quantity",), 10.5),
        (("commission_usd",), "-1"),
        (("recorded_at",), "2024-07-01T20:00:00Z"),
        (("source",), "broker"),
    ],
)
def test_audit_events_preserve_fill_units_and_native_time(path, value):
    with pytest.raises(ValidationError):
        ExecutionAuditEvent.model_validate(changed(example("execution-event"), path, value))


def test_uncertain_and_cancelled_events_preserve_partial_exposure_without_inventing_fills():
    data = example("execution-event")
    data.update(
        status="uncertain", native_status="timeout", fill_quantity_delta=0, fill_price_usd=None
    )
    event = ExecutionAuditEvent.model_validate(data)
    assert event.cumulative_filled_quantity == 4
    assert event.recorded_at > event.occurred_at
    data.update(status="cancelled", native_status="canceled")
    assert ExecutionAuditEvent.model_validate(data).cumulative_filled_quantity == 4


def reverse_keys(value):
    if isinstance(value, dict):
        return {k: reverse_keys(v) for k, v in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_keys(v) for v in value]
    return value


def test_canonical_identity_normalizes_key_order_decimals_defaults_and_timezone_instants():
    data = example("experiment")
    first = specimen()
    reordered = ExperimentSpecification.model_validate_json(json.dumps(reverse_keys(data)))
    assert experiment_id(first) == experiment_id(reordered)
    data["initial_cash_usd"] = "1.000000E4"
    data["costs"]["commission_per_order_usd"] = "1.0000"
    data["strategy"]["numerical_model"]["created_at"] = "2024-06-01T19:00:00-05:00"
    data["execution"] = {}
    assert experiment_id(ExperimentSpecification.model_validate(data)) == experiment_id(first)
    assert canonical_json(first) == canonical_json(reordered)
    assert '"initial_cash_usd":"10000"' in canonical_json(first)
    assert "2024-06-02T00:00:00.000000Z" in canonical_json(first)


@pytest.mark.parametrize(
    "path,value",
    [
        (("seed",), 8),
        (("costs", "commission_per_order_usd"), "2"),
        (("datasets", 0, "dataset_id"), "a" * 64),
        (("code_sha256",), "b" * 64),
        (("strategy", "version"), "2"),
        (("language_model", "prompt_sha256"), "c" * 64),
    ],
)
def test_material_inputs_change_experiment_identity(path, value):
    different = ExperimentSpecification.model_validate(changed(example("experiment"), path, value))
    assert experiment_id(different) != experiment_id(specimen())


def test_reruns_share_specification_identity_but_never_the_run_id():
    first, second = new_run(specimen()), new_run(specimen())
    assert first.experiment_id == second.experiment_id
    assert first.run_id != second.run_id
    assert ExperimentManifest.model_validate_json(canonical_json(first)) == first
    data = first.model_dump(mode="json")
    data["specification"]["seed"] += 1
    with pytest.raises(ValidationError, match="does not match"):
        ExperimentManifest.model_validate(data)


def test_context_is_bound_to_manifest_data_strategy_and_model_references():
    context = StrategyContext.model_validate(example("context"))
    manifest = context_manifest(context)
    assert validate_context(manifest, context) == context
    for path, value in [
        (("strategy", "version"), "2"),
        (("observations", 0, "feed"), "different_feed"),
        (("macro", "model", "prompt_sha256"), "c" * 64),
    ]:
        different = StrategyContext.model_validate(changed(example("context"), path, value))
        with pytest.raises(ValueError, match="match"):
            validate_context(manifest, different)


def test_records_are_deeply_immutable_and_unvalidated_copies_are_rechecked_at_boundaries():
    context = StrategyContext.model_validate(example("context"))
    with pytest.raises(ValidationError, match="frozen"):
        context.portfolio.cash_usd = Decimal("0")
    assert isinstance(context.observations, tuple)
    assert isinstance(context.strategy.parameters, tuple)
    # Pydantic's model_copy(update=...) is an intentionally unvalidated API.
    bad = specimen().model_copy(update={"initial_cash_usd": Decimal("-1")})
    with pytest.raises(ValidationError):
        new_run(bad)
    with pytest.raises(ValidationError):
        canonical_json(bad)
    with pytest.raises(ValidationError, match="Extra inputs"):
        StrategyContext.model_validate(dict(example("context"), broker=object()))


def test_example_runs_offline_without_engine_or_provider_imports():
    root = EXAMPLES.parents[1]
    script = """
import runpy, socket, sys
def deny(*args, **kwargs):
    raise AssertionError('Contracts must not attempt networking')
socket.socket = deny
runpy.run_path('examples/contracts/validate.py', run_name='__main__')
assert not any(name in sys.modules for name in ['lumibot', 'alpaca', 'sklearn', 'pandas'])
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert len(set(report["run_ids"])) == 2
