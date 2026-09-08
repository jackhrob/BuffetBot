"""Versioned data-only boundaries for research and target generation.

No engine, provider, filesystem handle or model runtime belongs in these records.
See docs/contracts.md for the v1 units, temporal rules and compatibility policy.
"""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


def exact_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Use a decimal string, Decimal or integer; floats are not exact units")
    return value


def decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def timestamp_input(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Use a timezone-aware datetime or ISO timestamp with an offset")
    if isinstance(value, str) and "T" not in value:
        raise ValueError("Timestamp must contain an explicit date, time and offset")
    return value


def session_input(value):
    if type(value) is date or (isinstance(value, str) and len(value) == 10):
        return value
    raise ValueError("Use an ISO session date (YYYY-MM-DD), not a timestamp")


def version_input(value):
    if type(value) is not int:
        raise ValueError("schema_version must be integer 1")
    return value


Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Symbol = Annotated[str, Field(strict=True, pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=200_000)]
Number = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    Field(allow_inf_nan=False, max_digits=24, decimal_places=8),
    PlainSerializer(decimal_text, return_type=str, when_used="json"),
]
Money = Annotated[Number, Field(ge=0)]
Price = Annotated[Number, Field(gt=0)]
Weight = Annotated[Number, Field(ge=0, le=1)]
Shares = Annotated[int, Field(strict=True, ge=0)]
PositiveShares = Annotated[Shares, Field(gt=0)]
Timestamp = Annotated[
    AwareDatetime,
    BeforeValidator(timestamp_input),
    AfterValidator(lambda value: value.astimezone(UTC)),
    PlainSerializer(
        lambda value: value.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]
Session = Annotated[date, BeforeValidator(session_input)]
Mode = Literal["backtest", "shadow", "paper"]
Origin = Literal["synthetic", "historical", "prospective"]
NY = ZoneInfo("America/New_York")


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class VersionedRecord(Record):
    # Required in persisted input; omitted and unknown versions are rejected, never guessed.
    schema_version: Annotated[Literal[1], BeforeValidator(version_input)]


class Instrument(Record):
    symbol: Symbol
    asset_class: Literal["us_etf"] = "us_etf"
    currency: Literal["USD"] = "USD"
    exchange: Identifier
    calendar: Literal["XNYS"] = "XNYS"
    timezone: Literal["America/New_York"] = "America/New_York"
    listed_on: Session
    delisted_on: Session | None = None

    @model_validator(mode="after")
    def listing_dates(self):
        if self.delisted_on is not None and self.delisted_on <= self.listed_on:
            raise ValueError("delisted_on must be later than listed_on (exclusive boundary)")
        return self


class Setting(Record):
    name: Identifier
    # Decimal policy settings use decimal strings; each policy validates its own parameter names.
    value: StrictBool | StrictInt | StrictStr


class NumericalModelReference(Record):
    artifact_sha256: Digest
    preprocessing_sha256: Digest
    training_dataset_id: Digest
    feature_schema_id: Identifier
    feature_names: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    trained_through: Timestamp
    created_at: Timestamp

    @model_validator(mode="after")
    def training_order(self):
        unique(self.feature_names, "model feature names")
        if self.trained_through > self.created_at:
            raise ValueError("trained_through cannot follow model created_at")
        return self


class LanguageModelReference(Record):
    artifact_sha256: Digest
    prompt_sha256: Digest
    output_schema_id: Literal["macro_assessment.v1"] = "macro_assessment.v1"
    training_cutoff: Timestamp | None


class StrategyDefinition(Record):
    name: Identifier
    version: Identifier
    feature_schema_id: Identifier
    feature_names: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    parameters: tuple[Setting, ...] = ()
    numerical_model: NumericalModelReference | None = None

    @field_validator("parameters")
    @classmethod
    def parameter_names(cls, values):
        unique([v.name for v in values], "parameter names")
        return tuple(sorted(values, key=lambda v: v.name))

    @model_validator(mode="after")
    def compatible_model(self):
        unique(self.feature_names, "strategy feature names")
        if (
            self.numerical_model
            and self.numerical_model.feature_schema_id != self.feature_schema_id
        ):
            raise ValueError(
                "numerical_model.feature_schema_id must match strategy feature_schema_id"
            )
        if self.numerical_model and self.numerical_model.feature_names != self.feature_names:
            raise ValueError("Numerical model feature names/order must match the strategy")
        return self


class MarketBar(VersionedRecord):
    """Normalized source row, before a snapshot identity has been assigned."""

    symbol: Symbol
    session: Session
    interval: Literal["1d"] = "1d"
    interval_start: Timestamp
    interval_end: Timestamp
    available_at: Timestamp
    first_ingested_at: Timestamp
    provider: Identifier
    feed: Identifier
    revision_id: Identifier
    origin: Origin
    adjustment: Literal["raw"] = "raw"
    currency: Literal["USD"] = "USD"
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Shares

    @model_validator(mode="after")
    def completed_raw_bar(self):
        if (
            not self.interval_start
            < self.interval_end
            <= self.available_at
            <= self.first_ingested_at
        ):
            raise ValueError(
                "Require interval_start < interval_end <= available_at <= first_ingested_at"
            )
        if any(
            t.astimezone(NY).date() != self.session
            for t in (self.interval_start, self.interval_end)
        ):
            raise ValueError("interval times must fall in the declared New York session date")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Raw OHLC must satisfy low <= open/close <= high")
        return self


class MarketObservation(MarketBar):
    """A source bar bound to a verified, immutable snapshot."""

    dataset_id: Digest


class FeatureValue(Record):
    name: Identifier
    value: Number


class FeatureObservation(VersionedRecord):
    symbol: Symbol
    session: Session
    dataset_id: Digest
    feature_schema_id: Identifier
    available_at: Timestamp
    computed_at: Timestamp
    adjusted_as_of: Timestamp
    adjustment: Literal["split_as_of_cutoff"] = "split_as_of_cutoff"
    values: Annotated[tuple[FeatureValue, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def feature_times(self):
        unique([v.name for v in self.values], "feature names")
        if self.available_at > self.computed_at or self.adjusted_as_of > self.computed_at:
            raise ValueError("Feature availability/adjustment cutoff cannot follow computed_at")
        if self.session > self.available_at.astimezone(NY).date():
            raise ValueError("Feature session cannot follow available_at")
        return self


class SourceDocument(VersionedRecord):
    document_id: Identifier
    dataset_id: Digest
    source_url: HttpUrl
    published_at: Timestamp
    available_at: Timestamp
    first_ingested_at: Timestamp
    revision_id: Identifier
    revision_policy: Literal["point_in_time", "unknown"]
    content_sha256: Digest
    original_text: Text

    @model_validator(mode="after")
    def provenance(self):
        if not self.published_at <= self.available_at <= self.first_ingested_at:
            raise ValueError("Require published_at <= available_at <= first_ingested_at")
        if hashlib.sha256(self.original_text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 does not match original_text UTF-8 bytes")
        return self


class EvidenceSpan(Record):
    document_id: Identifier
    content_sha256: Digest
    start: Shares
    end: PositiveShares
    text: Text

    @model_validator(mode="after")
    def span_length(self):
        if self.end - self.start != len(self.text):
            raise ValueError("Evidence [start, end) must match text length in Unicode characters")
        return self


class MacroAssessment(VersionedRecord):
    assessment_id: Identifier
    dataset_id: Digest
    source_document_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    comparison_document_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    policy_direction: Literal["tighter", "easier", "unchanged", "ambiguous", "unknown"]
    concern_change: Literal["inflation", "growth", "both", "unchanged", "ambiguous", "unknown"]
    evidence: tuple[EvidenceSpan, ...]
    source_cutoff: Timestamp
    generated_at: Timestamp
    expires_at: Timestamp
    use: Literal["historical_exploratory", "prospective"]
    model: LanguageModelReference
    generation_parameters: tuple[Setting, ...] = ()
    response_sha256: Digest
    latency_ms: Shares

    @model_validator(mode="after")
    def assessment_provenance(self):
        unique([*self.source_document_ids, *self.comparison_document_ids], "document references")
        unique([v.name for v in self.generation_parameters], "generation parameter names")
        if not self.source_cutoff <= self.generated_at or self.expires_at <= self.source_cutoff:
            raise ValueError("Require source_cutoff <= generated_at and source_cutoff < expires_at")
        if self.use == "prospective" and self.generated_at >= self.expires_at:
            raise ValueError("Prospective assessment must be generated before expiry")
        if (
            self.model.training_cutoff is not None
            and self.model.training_cutoff > self.generated_at
        ):
            raise ValueError("Language-model training cutoff cannot follow generation")
        referenced = set(self.source_document_ids + self.comparison_document_ids)
        cited = {e.document_id for e in self.evidence}
        if not cited <= referenced:
            raise ValueError("Evidence refers to an undeclared source/comparison document")
        if self.policy_direction != "unknown" or self.concern_change != "unknown":
            if not cited.intersection(self.source_document_ids) or not cited.intersection(
                self.comparison_document_ids
            ):
                raise ValueError(
                    "Known/ambiguous comparisons need evidence from both document groups"
                )
        return self


def validate_macro_sources(assessment: MacroAssessment, documents: tuple[SourceDocument, ...]):
    """Validate references and exact quotations; factual interpretation still needs evaluation."""
    unique([d.document_id for d in documents], "document IDs")
    by_id = {d.document_id: d for d in documents}
    for document_id in assessment.source_document_ids + assessment.comparison_document_ids:
        if document_id not in by_id:
            raise ValueError(f"Missing source document: {document_id}")
        if by_id[document_id].available_at > assessment.source_cutoff:
            raise ValueError("Source document became available after assessment source_cutoff")
    for span in assessment.evidence:
        doc = by_id[span.document_id]
        if (
            doc.content_sha256 != span.content_sha256
            or doc.original_text[span.start : span.end] != span.text
        ):
            raise ValueError("Evidence hash/span does not match the referenced source text")


class Holding(Record):
    symbol: Symbol
    quantity: PositiveShares
    raw_mark_usd: Price
    marked_at: Timestamp


class PendingOrder(Record):
    intention_id: Identifier
    symbol: Symbol
    side: Literal["buy", "sell"]
    remaining_quantity: PositiveShares
    reserved_cash_usd: Money

    @model_validator(mode="after")
    def reservation(self):
        if self.side == "sell" and self.reserved_cash_usd != 0:
            raise ValueError("Sell orders reserve shares, not cash")
        return self


class PortfolioState(Record):
    as_of: Timestamp
    currency: Literal["USD"] = "USD"
    cash_usd: Money
    dividend_receivable_usd: Money
    holdings: tuple[Holding, ...] = ()
    pending_orders: tuple[PendingOrder, ...] = ()

    @model_validator(mode="after")
    def exposure(self):
        unique([h.symbol for h in self.holdings], "holding symbols")
        unique([p.intention_id for p in self.pending_orders], "pending intention IDs")
        if any(h.marked_at > self.as_of for h in self.holdings):
            raise ValueError("Holding marks cannot follow portfolio as_of")
        if sum(p.reserved_cash_usd for p in self.pending_orders) > self.cash_usd:
            raise ValueError("Pending cash reservations exceed cash; receivables are not spendable")
        held = {h.symbol: h.quantity for h in self.holdings}
        for symbol in {p.symbol for p in self.pending_orders}:
            selling = sum(
                p.remaining_quantity
                for p in self.pending_orders
                if p.symbol == symbol and p.side == "sell"
            )
            if selling > held.get(symbol, 0):
                raise ValueError("Pending sells exceed held whole shares")
        return self

    @property
    def equity_usd(self) -> Decimal:
        return (
            self.cash_usd
            + self.dividend_receivable_usd
            + sum(h.quantity * h.raw_mark_usd for h in self.holdings)
        )

    @property
    def spendable_cash_usd(self) -> Decimal:
        return self.cash_usd - sum(p.reserved_cash_usd for p in self.pending_orders)


class StrategyContext(VersionedRecord):
    run_id: UUID
    experiment_id: Digest
    mode: Mode
    decision_at: Timestamp
    execution_at: Timestamp
    execution_session: Session
    target_expires_at: Timestamp
    universe: Annotated[tuple[Instrument, ...], Field(min_length=1)]
    dataset_ids: Annotated[tuple[Digest, ...], Field(min_length=1)]
    strategy: StrategyDefinition
    portfolio: PortfolioState
    observations: tuple[MarketObservation, ...]
    features: tuple[FeatureObservation, ...] = ()
    documents: tuple[SourceDocument, ...] = ()
    macro: MacroAssessment | None = None

    @model_validator(mode="after")
    def eligible_context(self):
        symbols = {i.symbol for i in self.universe}
        unique([i.symbol for i in self.universe], "universe symbols")
        unique(self.dataset_ids, "dataset IDs")
        if not self.decision_at < self.execution_at < self.target_expires_at:
            raise ValueError("Require decision_at < execution_at < target_expires_at")
        if self.execution_at.astimezone(NY).date() != self.execution_session:
            raise ValueError("execution_at must fall on execution_session in New York")
        if self.portfolio.as_of > self.decision_at:
            raise ValueError("portfolio.as_of cannot follow decision_at")
        for instrument in self.universe:
            if self.execution_session < instrument.listed_on or (
                instrument.delisted_on is not None
                and self.execution_session >= instrument.delisted_on
            ):
                raise ValueError("Execution session falls outside an instrument listing interval")
        for item in (*self.portfolio.holdings, *self.portfolio.pending_orders):
            if item.symbol not in symbols:
                raise ValueError("Portfolio exposure references a symbol outside the universe")
        unique(
            [(o.symbol, o.session) for o in self.observations], "observation symbol/session pairs"
        )
        unique([(f.symbol, f.session) for f in self.features], "feature symbol/session pairs")
        unique([d.document_id for d in self.documents], "document IDs")
        for observation in (*self.observations, *self.features):
            if observation.symbol not in symbols or observation.dataset_id not in self.dataset_ids:
                raise ValueError("Observation symbol/dataset must be declared in the context")
            if (
                observation.available_at > self.decision_at
                or observation.session >= self.execution_session
            ):
                raise ValueError("Observation is not eligible at decision_at for a later session")
        for feature in self.features:
            if feature.feature_schema_id != self.strategy.feature_schema_id:
                raise ValueError("Feature schema does not match the strategy")
            if tuple(v.name for v in feature.values) != self.strategy.feature_names:
                raise ValueError("Feature names/order do not match the declared strategy schema")
            if feature.adjusted_as_of > self.decision_at:
                raise ValueError("Feature adjustment uses information after decision_at")
            source = next(
                (
                    o
                    for o in self.observations
                    if (o.symbol, o.session, o.dataset_id)
                    == (feature.symbol, feature.session, feature.dataset_id)
                ),
                None,
            )
            if source is None or feature.available_at < source.available_at:
                raise ValueError(
                    "Feature needs a matching raw observation available no later than the feature"
                )
            if feature.computed_at < source.first_ingested_at:
                raise ValueError(
                    "Feature cannot be computed before its raw observation was ingested"
                )
        if self.mode != "backtest":
            if any(o.first_ingested_at > self.decision_at for o in self.observations):
                raise ValueError(
                    "Prospective context cannot use observations ingested after decision_at"
                )
            if any(f.computed_at > self.decision_at for f in self.features):
                raise ValueError(
                    "Prospective context cannot use features computed after decision_at"
                )
            if any(o.origin == "synthetic" for o in self.observations):
                raise ValueError("Synthetic observations are limited to backtests")
        for document in self.documents:
            if (
                document.dataset_id not in self.dataset_ids
                or document.available_at > self.decision_at
            ):
                raise ValueError("Document dataset/availability is not eligible for this context")
            if self.mode != "backtest" and document.first_ingested_at > self.decision_at:
                raise ValueError("Prospective document was ingested after decision_at")
        model = self.strategy.numerical_model
        if model and (
            model.trained_through >= self.decision_at
            or (self.mode != "backtest" and model.created_at > self.decision_at)
        ):
            raise ValueError("Numerical model training/creation cutoff is not eligible")
        if self.macro:
            if self.macro.dataset_id not in self.dataset_ids:
                raise ValueError("Macro dataset must be declared in the context")
            if not self.macro.source_cutoff <= self.decision_at < self.macro.expires_at:
                raise ValueError("Macro assessment is future or expired at decision_at")
            if self.mode != "backtest" and (
                self.macro.use != "prospective" or self.macro.generated_at > self.decision_at
            ):
                raise ValueError(
                    "Prospective context needs an already generated prospective assessment"
                )
            if self.mode == "backtest" and self.macro.use != "historical_exploratory":
                raise ValueError("Historical macro replay must be labelled historical_exploratory")
            validate_macro_sources(self.macro, self.documents)
        return self


class TargetWeight(Record):
    symbol: Symbol
    weight: Weight


class PortfolioTargets(VersionedRecord):
    run_id: UUID
    experiment_id: Digest
    strategy_name: Identifier
    strategy_version: Identifier
    decision_at: Timestamp
    feature_cutoff: Timestamp
    execution_at: Timestamp
    expires_at: Timestamp
    weights: tuple[TargetWeight, ...]
    reason_codes: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def long_cash_targets(self):
        unique([w.symbol for w in self.weights], "target symbols")
        if sum(w.weight for w in self.weights) > 1:
            raise ValueError(
                "Total target weight cannot exceed 1; weights are fractions, not percent"
            )
        if not self.feature_cutoff <= self.decision_at < self.execution_at < self.expires_at:
            raise ValueError("Require feature_cutoff <= decision_at < execution_at < expires_at")
        return self

    @property
    def cash_weight(self) -> Decimal:
        return Decimal(1) - sum(w.weight for w in self.weights)


def validate_targets(
    context: StrategyContext,
    targets: PortfolioTargets,
    *,
    at: datetime | None = None,
) -> PortfolioTargets:
    context = StrategyContext.model_validate(context)
    targets = PortfolioTargets.model_validate(targets)
    if targets.run_id != context.run_id or targets.experiment_id != context.experiment_id:
        raise ValueError("Targets reference a different run/experiment")
    if (targets.strategy_name, targets.strategy_version) != (
        context.strategy.name,
        context.strategy.version,
    ):
        raise ValueError("Targets reference a different strategy version")
    if (targets.decision_at, targets.execution_at, targets.expires_at) != (
        context.decision_at,
        context.execution_at,
        context.target_expires_at,
    ):
        raise ValueError("Target decision/execution/expiry timestamps must match the context")
    if targets.feature_cutoff != context.decision_at:
        raise ValueError("Targets must preserve the context's information cutoff")
    if not {w.symbol for w in targets.weights} <= {i.symbol for i in context.universe}:
        raise ValueError("Targets reference a symbol outside the eligible universe")
    if at is not None and (not isinstance(at, datetime) or at.utcoffset() is None):
        raise ValueError("Target validation time must be a timezone-aware datetime")
    checked_at = at if at is not None else context.decision_at
    if not targets.decision_at <= checked_at < targets.expires_at:
        raise ValueError("Targets are future or expired at validation time")
    return targets


class Strategy(Protocol):
    def generate_targets(self, context: StrategyContext) -> PortfolioTargets: ...


class ExecutionAuditEvent(VersionedRecord):
    event_id: Identifier
    run_id: UUID
    experiment_id: Digest
    mode: Mode
    source: Literal["engine", "broker"]
    intention_id: Identifier
    client_order_id: Identifier
    engine_order_id: Identifier | None
    broker_order_id: Identifier | None
    native_event_id: Identifier | None
    native_status: Identifier
    status: Literal[
        "planned",
        "submitted",
        "acknowledged",
        "partial_fill",
        "filled",
        "cancelled",
        "rejected",
        "expired",
        "uncertain",
    ]
    symbol: Symbol
    side: Literal["buy", "sell"]
    requested_quantity: PositiveShares
    cumulative_filled_quantity: Shares
    fill_quantity_delta: Shares
    fill_price_usd: Price | None
    commission_usd: Money
    occurred_at: Timestamp
    recorded_at: Timestamp

    @model_validator(mode="after")
    def consistent_event(self):
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede the native occurred_at")
        if (
            not self.fill_quantity_delta
            <= self.cumulative_filled_quantity
            <= self.requested_quantity
        ):
            raise ValueError("Require fill delta <= cumulative fill <= requested quantity")
        if self.status in ("partial_fill", "filled"):
            if self.fill_quantity_delta == 0 or self.fill_price_usd is None:
                raise ValueError(
                    "Fill events require a positive execution delta and raw fill price"
                )
            if (
                self.status == "filled"
                and self.cumulative_filled_quantity != self.requested_quantity
            ):
                raise ValueError("Filled status requires the full requested quantity")
            if (
                self.status == "partial_fill"
                and self.cumulative_filled_quantity >= self.requested_quantity
            ):
                raise ValueError("Partial fill must leave a positive remaining quantity")
        elif self.fill_quantity_delta or self.fill_price_usd is not None:
            raise ValueError("Non-fill events cannot add a fill quantity or fill price")
        if self.source == "broker" and self.mode != "paper":
            raise ValueError("Broker evidence belongs to paper mode, not simulated modes")
        if self.source == "engine" and self.status != "planned" and self.engine_order_id is None:
            raise ValueError("Engine events after planning require engine_order_id")
        if self.source == "broker" and self.status in ("acknowledged", "partial_fill", "filled"):
            if self.broker_order_id is None:
                raise ValueError("Broker acknowledgments and fills require broker_order_id")
        return self
