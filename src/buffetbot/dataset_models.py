"""Small, versioned records for local daily market snapshots."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from buffetbot.contracts import (
    Digest,
    Identifier,
    Instrument,
    Origin,
    PositiveShares,
    Price,
    Record,
    Session,
    Shares,
    Symbol,
    Text,
    Timestamp,
    VersionedRecord,
    unique,
)


class SnapshotPlan(VersionedRecord):
    schema_id: Literal["market_observation.v1"] = "market_observation.v1"
    origin: Origin
    provider: Identifier
    feed: Identifier
    universe: Annotated[tuple[Instrument, ...], Field(min_length=1)]
    interval: Literal["1d"] = "1d"
    coverage_start: Session
    coverage_end: Session
    first_execution_session: Session
    warmup_sessions: Shares
    retrieved_at: Timestamp
    retrieval_convention: Text
    availability_convention: Text
    revision_policy: Literal["point_in_time", "unknown"]
    limitations: tuple[Identifier, ...]
    executable_adjustment: Literal["raw"] = "raw"
    research_adjustment: Literal["split_as_of_cutoff"] = "split_as_of_cutoff"
    zero_volume_policy: Literal["allow_with_warning", "reject"]
    # Complete is an explicit source attestation over the entire requested range/universe.
    # An empty action list alone never establishes completeness.
    corporate_actions_coverage: Literal["complete", "unknown"]
    corporate_actions_source: Text

    @model_validator(mode="after")
    def consistent_request(self):
        unique([i.symbol for i in self.universe], "universe symbols")
        unique(self.limitations, "limitations")
        if not self.coverage_start <= self.first_execution_session <= self.coverage_end:
            raise ValueError("Require coverage_start <= first_execution_session <= coverage_end")
        if self.revision_policy == "unknown" and "unknown_revision_timing" not in self.limitations:
            raise ValueError("Unknown revision timing requires its explicit limitation")
        if self.origin == "synthetic" and "synthetic_data" not in self.limitations:
            raise ValueError("Synthetic snapshots must declare synthetic_data")
        if self.origin != "synthetic" and "synthetic_data" in self.limitations:
            raise ValueError("Non-synthetic snapshots cannot declare synthetic_data")
        return self


class CorporateAction(VersionedRecord):
    """Regular cash dividends and whole-number forward splits only.

    effective_session is the split session or dividend ex-date. Entitlement/quantity
    changes occur at that session's open. Cash becomes payable on pay_date, possibly
    after this snapshot ends; later accounting must retain the receivable.
    """

    action_id: Identifier
    symbol: Symbol
    kind: Literal["split", "cash_dividend"]
    effective_session: Session
    available_at: Timestamp
    first_ingested_at: Timestamp
    revision_id: Identifier
    split_ratio: Annotated[int, Field(strict=True, ge=2)] | None
    cash_amount_usd: Price | None
    pay_date: Session | None

    @model_validator(mode="after")
    def supported_action(self):
        if self.available_at > self.first_ingested_at:
            raise ValueError("Action availability cannot follow first ingestion")
        if self.kind == "split":
            if self.split_ratio is None or self.cash_amount_usd is not None or self.pay_date:
                raise ValueError("A forward split requires only an integer ratio >= 2")
        elif (
            self.split_ratio is not None
            or self.cash_amount_usd is None
            or self.pay_date is None
            or self.pay_date < self.effective_session
        ):
            raise ValueError("A dividend requires amount and pay_date >= ex-date, without ratio")
        return self


class TradingSession(Record):
    session: Session
    market_open: Timestamp
    market_close: Timestamp


class Finding(Record):
    severity: Literal["error", "warning"]
    code: Identifier
    symbol: Symbol | None = None
    session: Session | None = None
    detail: Text


class SymbolCoverage(Record):
    symbol: Symbol
    expected_bars: Shares
    observed_bars: Shares
    missing_sessions: tuple[Session, ...]


class QualityReport(VersionedRecord):
    origin: Origin
    usable: bool
    coverage: tuple[SymbolCoverage, ...]
    expected_closures: tuple[Session, ...]
    shortened_sessions: tuple[Session, ...]
    findings: tuple[Finding, ...]


class SnapshotFile(Record):
    name: Literal["bars.parquet", "actions.parquet", "sessions.parquet"]
    sha256: Digest
    rows: Shares
    size_bytes: PositiveShares


class SnapshotManifest(VersionedRecord):
    storage_schema: Literal["daily_market_snapshot.v1"] = "daily_market_snapshot.v1"
    plan: SnapshotPlan
    calendar_source: Literal["pandas_market_calendars:NYSE"] = "pandas_market_calendars:NYSE"
    calendar_version: Literal["5.4.0"] = "5.4.0"
    parquet_writer: Literal["pyarrow:25.0.1"] = "pyarrow:25.0.1"
    files: tuple[SnapshotFile, ...]
    quality: QualityReport

    @model_validator(mode="after")
    def complete_manifest(self):
        if tuple(f.name for f in self.files) != (
            "bars.parquet",
            "actions.parquet",
            "sessions.parquet",
        ):
            raise ValueError("Require exactly the supported snapshot files in canonical order")
        if self.quality.origin != self.plan.origin or not self.quality.usable:
            raise ValueError("Published quality must be usable and match the dataset origin")
        return self
