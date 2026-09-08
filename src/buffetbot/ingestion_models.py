"""Explicit historical import requests and immutable original response captures."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StrictInt, StrictStr, model_validator

from buffetbot.contracts import (
    Digest,
    Instrument,
    Session,
    Shares,
    Timestamp,
    VersionedRecord,
    unique,
)
from buffetbot.market_http import MAX_RESPONSE_BYTES

ADAPTER_VERSION = "alpaca_regular_minutes.v1"


class ImportReceipt(VersionedRecord):
    adapter_version: Literal["alpaca_regular_minutes.v1"]
    origin: Literal["historical", "synthetic"]
    request_id: Digest
    dataset_id: Digest
    capture_id: Digest


class HistoricalRequest(VersionedRecord):
    universe: Annotated[tuple[Instrument, ...], Field(min_length=1, max_length=5)]
    start_session: Session
    end_session: Session
    first_execution_session: Session
    warmup_sessions: Shares
    interval: Literal["1d"]
    feed: Literal["sip", "iex"]
    adjustment: Literal["raw"]
    aggregation: Literal["regular_session_from_1min"]
    zero_volume_policy: Literal["allow_with_warning", "reject"]

    @model_validator(mode="after")
    def supported_range(self):
        unique([i.symbol for i in self.universe], "universe symbols")
        if (
            not date(2016, 1, 1)
            <= self.start_session
            <= self.first_execution_session
            <= self.end_session
        ):
            raise ValueError("Require 2016-01-01 <= start <= first execution <= end")
        if (self.end_session - self.start_session).days > 366:
            raise ValueError(
                "A local MVP import covers at most 366 calendar days; use separate snapshots"
            )
        return self


class CapturedPage(VersionedRecord):
    path: Literal["/v2/stocks/bars", "/v1/corporate-actions"]
    params: dict[StrictStr, StrictStr | StrictInt]
    received_at: Timestamp
    request_id: Annotated[str, Field(strict=True, max_length=128)] | None
    body: Annotated[str, Field(strict=True, min_length=2, max_length=MAX_RESPONSE_BYTES)]


class SourceCapture(VersionedRecord):
    adapter_version: Literal["alpaca_regular_minutes.v1"] = ADAPTER_VERSION
    origin: Literal["historical", "synthetic"]
    request: HistoricalRequest
    requested_at: Timestamp
    captured_at: Timestamp
    pages: Annotated[tuple[CapturedPage, ...], Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def chronological_capture(self):
        if any(not self.requested_at <= p.received_at <= self.captured_at for p in self.pages):
            raise ValueError("Page receipt must fall between request start and capture completion")
        return self
