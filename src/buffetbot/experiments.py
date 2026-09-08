"""Explicit experiment inputs, canonical content identity and independent run manifests."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import UUID4, Field, model_validator

from buffetbot.contracts import (
    NY,
    Digest,
    Identifier,
    Instrument,
    LanguageModelReference,
    Mode,
    Money,
    Number,
    Origin,
    Record,
    Session,
    Shares,
    StrategyContext,
    StrategyDefinition,
    TargetWeight,
    Timestamp,
    VersionedRecord,
    unique,
)


class DatasetReference(Record):
    dataset_id: Digest
    kind: Literal["market", "documents", "macro_assessments"]
    schema_id: Literal["market_observation.v1", "source_document.v1", "macro_assessment.v1"]
    origin: Origin
    provider: Identifier
    feed: Identifier
    revision_policy: Literal["point_in_time", "unknown"]
    limitations: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def compatible_schema(self):
        expected = {
            "market": "market_observation.v1",
            "documents": "source_document.v1",
            "macro_assessments": "macro_assessment.v1",
        }
        if self.schema_id != expected[self.kind]:
            raise ValueError("Dataset schema_id does not match its kind")
        if self.revision_policy == "unknown" and "unknown_revision_timing" not in self.limitations:
            raise ValueError(
                "Unknown revisions must declare the unknown_revision_timing limitation"
            )
        return self


class CostAssumptions(Record):
    currency: Literal["USD"] = "USD"
    commission_per_order_usd: Money
    combined_spread_slippage_bps: Annotated[Number, Field(ge=0, lt=10_000)]
    execution_cost_model: Literal["synthetic_open_bid_ask"] = "synthetic_open_bid_ask"


class ExecutionConvention(Record):
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day"] = "day"
    session: Literal["regular"] = "regular"
    release: Literal["next_session_open"] = "next_session_open"
    quantities: Literal["whole_shares"] = "whole_shares"
    executable_prices: Literal["raw"] = "raw"
    feature_adjustment: Literal["split_as_of_cutoff"] = "split_as_of_cutoff"
    price_rounding: Literal["lumibot_4.5.91_quote_cent"] = "lumibot_4.5.91_quote_cent"
    missing_data: Literal["reject"] = "reject"
    end_of_run: Literal["keep_positions_and_unfilled_orders"] = "keep_positions_and_unfilled_orders"


class CashTreatment(Record):
    initial_positions: Literal["cash_only"] = "cash_only"
    interest: Literal["zero"] = "zero"
    leverage: Literal["disabled"] = "disabled"
    dividends: Literal["ex_date_entitlement_pay_date_cash"] = "ex_date_entitlement_pay_date_cash"
    receivables: Literal["equity_only_not_spendable"] = "equity_only_not_spendable"
    dividend_reinvestment: Literal["none"] = "none"
    splits: Literal["raw_prices_native_quantity_adjustment"] = (
        "raw_prices_native_quantity_adjustment"
    )
    unsupported_corporate_actions: Literal["reject"] = "reject"


class BenchmarkDefinition(Record):
    name: Literal["buy_and_hold"] = "buy_and_hold"
    weights: Annotated[tuple[TargetWeight, ...], Field(min_length=1)]
    entry: Literal["first_execution_session"] = "first_execution_session"
    costs: Literal["same_as_strategy"] = "same_as_strategy"

    @model_validator(mode="after")
    def valid_allocation(self):
        unique([w.symbol for w in self.weights], "benchmark symbols")
        if not 0 < sum(w.weight for w in self.weights) <= 1:
            raise ValueError("Benchmark weights must total more than zero and at most one")
        return self


class ExperimentSpecification(VersionedRecord):
    mode: Mode
    research_use: Literal["synthetic", "historical_exploratory", "prospective"]
    universe: Annotated[tuple[Instrument, ...], Field(min_length=1)]
    universe_selection: Literal["fixed_declared_universe"] = "fixed_declared_universe"
    limitations: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    start_session: Session
    end_session: Session
    warmup_sessions: Shares
    initial_cash_usd: Annotated[Money, Field(gt=0)]
    strategy: StrategyDefinition
    benchmark: BenchmarkDefinition
    costs: CostAssumptions
    execution: ExecutionConvention
    cash_treatment: CashTreatment
    datasets: Annotated[tuple[DatasetReference, ...], Field(min_length=1)]
    language_model: LanguageModelReference | None = None
    code_revision: Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{40}$")]
    code_sha256: Digest
    dependency_lock_sha256: Digest
    engine_version: Literal["4.5.91"] = "4.5.91"
    seed: Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]

    @model_validator(mode="after")
    def compatible_experiment(self):
        unique([i.symbol for i in self.universe], "universe symbols")
        unique([d.dataset_id for d in self.datasets], "dataset IDs")
        if self.start_session > self.end_session:
            raise ValueError("start_session must not follow end_session (both inclusive)")
        if not {w.symbol for w in self.benchmark.weights} <= {i.symbol for i in self.universe}:
            raise ValueError("Benchmark weights must reference the experiment universe")
        for instrument in self.universe:
            if self.start_session < instrument.listed_on or (
                instrument.delisted_on is not None and self.end_session >= instrument.delisted_on
            ):
                raise ValueError(
                    "Experiment dates fall outside a declared instrument listing interval"
                )
        kinds = {d.kind for d in self.datasets}
        if "market" not in kinds:
            raise ValueError("Experiment requires a market dataset reference")
        if self.language_model and not {"documents", "macro_assessments"} <= kinds:
            raise ValueError(
                "Language-model experiments require source and saved-assessment datasets"
            )
        if "macro_assessments" in kinds and self.language_model is None:
            raise ValueError(
                "Saved macro assessments require an explicit language model/prompt reference"
            )
        if self.mode == "backtest" and self.research_use == "prospective":
            raise ValueError("Backtests must be labelled synthetic or historical_exploratory")
        if self.mode != "backtest" and self.research_use != "prospective":
            raise ValueError("Paper/shadow specifications must be prospective")
        synthetic = any(d.origin == "synthetic" for d in self.datasets)
        if synthetic != (self.research_use == "synthetic"):
            raise ValueError("Synthetic dataset inputs require an explicitly synthetic backtest")
        if any(not set(d.limitations) <= set(self.limitations) for d in self.datasets):
            raise ValueError("Experiment limitations must include its dataset limitations")
        model = self.strategy.numerical_model
        if model and model.trained_through.astimezone(NY).date() >= self.start_session:
            raise ValueError(
                "Pinned numerical model must be trained before the first execution session"
            )
        return self


def canonical_json(record: Record) -> str:
    """V1 canonical JSON: validated defaults, UTC, decimal strings and sorted object keys."""
    checked = type(record).model_validate(record)
    return json.dumps(
        checked.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def experiment_id(specification: ExperimentSpecification) -> str:
    return hashlib.sha256(canonical_json(specification).encode("utf-8")).hexdigest()


class ArtifactReference(Record):
    role: Identifier
    content_sha256: Digest


class ExperimentManifest(VersionedRecord):
    run_id: UUID4
    created_at: Timestamp
    experiment_id: Digest
    specification: ExperimentSpecification
    artifacts: tuple[ArtifactReference, ...] = ()

    @model_validator(mode="after")
    def matching_specification(self):
        if self.experiment_id != experiment_id(self.specification):
            raise ValueError("experiment_id does not match the canonical specification")
        unique([a.role for a in self.artifacts], "artifact roles")
        return self


def new_run(
    specification: ExperimentSpecification, *, created_at: datetime | None = None
) -> ExperimentManifest:
    """Allocate identity only. No directories, jobs, execution or publication occur here."""
    specification = ExperimentSpecification.model_validate(specification)
    return ExperimentManifest(
        schema_version=1,
        run_id=uuid4(),
        created_at=created_at or datetime.now(UTC),
        experiment_id=experiment_id(specification),
        specification=specification,
    )


def validate_context(manifest: ExperimentManifest, context: StrategyContext) -> StrategyContext:
    """Bind a data-only context to its frozen run specification before invoking a strategy."""
    manifest = ExperimentManifest.model_validate(manifest)
    context = StrategyContext.model_validate(context)
    spec = manifest.specification
    if context.run_id != manifest.run_id or context.experiment_id != manifest.experiment_id:
        raise ValueError("Context references a different run/experiment")
    if (
        context.mode != spec.mode
        or context.strategy != spec.strategy
        or context.universe != spec.universe
    ):
        raise ValueError("Context mode/strategy/universe must match the run specification")
    if not spec.start_session <= context.execution_session <= spec.end_session:
        raise ValueError("Context execution session is outside the experiment range")
    datasets = {d.dataset_id: d for d in spec.datasets}
    if set(context.dataset_ids) != set(datasets):
        raise ValueError("Context dataset identities must match the run specification")
    for observation in context.observations:
        dataset = datasets[observation.dataset_id]
        if (dataset.kind, dataset.origin, dataset.provider, dataset.feed) != (
            "market",
            observation.origin,
            observation.provider,
            observation.feed,
        ):
            raise ValueError("Observation provenance does not match its dataset reference")
    for document in context.documents:
        dataset = datasets[document.dataset_id]
        if (dataset.kind, dataset.revision_policy) != ("documents", document.revision_policy):
            raise ValueError(
                "Source document revision policy/kind must match its dataset reference"
            )
    if context.macro and (
        context.macro.model != spec.language_model
        or datasets[context.macro.dataset_id].kind != "macro_assessments"
    ):
        raise ValueError("Macro assessment model/prompt/dataset does not match the specification")
    return context
