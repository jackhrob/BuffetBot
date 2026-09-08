"""Alpaca wire format, complete pagination and explicit regular-session aggregation."""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError, model_validator

from buffetbot.contracts import NY, MarketBar, Price, Record, Session, Timestamp
from buffetbot.dataset_models import CorporateAction, SnapshotPlan
from buffetbot.dataset_quality import trading_sessions
from buffetbot.experiments import canonical_json
from buffetbot.ingestion_models import (
    ADAPTER_VERSION,
    CapturedPage,
    HistoricalRequest,
    SourceCapture,
)
from buffetbot.market_http import IngestionError, Response


def json_object(text):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys")
            result[key] = value
        return result

    def bad_constant(_):
        raise ValueError("Non-finite JSON number")

    try:
        return json.loads(
            text, parse_float=Decimal, parse_constant=bad_constant, object_pairs_hook=unique_object
        )
    except (ValueError, UnicodeError):
        raise IngestionError(
            "invalid_response", "Provider response is not valid, unambiguous JSON."
        ) from None


def wire_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def page_payload(page):
    data = json_object(page.body)
    group = "bars" if page.path == "/v2/stocks/bars" else "corporate_actions"
    if not isinstance(data, dict) or group not in data or "next_page_token" not in data:
        raise IngestionError(
            "incomplete_response", "Provider response lacks its data or pagination field."
        )
    values = data[group] if data[group] is not None else {}
    token = data["next_page_token"]
    if not isinstance(values, dict) or any(not isinstance(v, list) for v in values.values()):
        raise IngestionError(
            "invalid_response", "Provider data must be a dictionary of record lists."
        )
    if token is not None and (not isinstance(token, str) or not 0 < len(token) <= 4096):
        raise IngestionError("invalid_pagination", "Provider pagination token is invalid.")
    if token is not None and not any(values.values()):
        raise IngestionError("empty_page", "An empty page cannot advance a nonterminal download.")
    return values, token


def query_specs(request: HistoricalRequest, requested_at):
    sessions = trading_sessions(request.start_session, request.end_session)
    if not sessions or sessions[-1].market_close + timedelta(minutes=15) > requested_at:
        raise IngestionError(
            "unfinished_range", "Request only completed exchange sessions at least 15 minutes old."
        )
    prior = [s for s in sessions if s.session < request.first_execution_session]
    if (
        request.first_execution_session not in {s.session for s in sessions}
        or len(prior) < request.warmup_sessions
    ):
        raise IngestionError(
            "insufficient_warmup",
            "The requested range must cover execution and all prior warmup sessions.",
        )
    required_start = (
        prior[-request.warmup_sessions].session
        if request.warmup_sessions
        else request.first_execution_session
    )
    if any(
        i.listed_on > required_start or (i.delisted_on and i.delisted_on <= request.end_session)
        for i in request.universe
    ):
        raise IngestionError(
            "listing_coverage", "Instrument listing metadata does not cover execution and warmup."
        )
    symbols = ",".join(sorted(i.symbol for i in request.universe))
    for session in sessions:
        yield (
            "/v2/stocks/bars",
            dict(
                symbols=symbols,
                timeframe="1Min",
                start=session.market_open.isoformat(),
                end=(session.market_close - timedelta(microseconds=1)).isoformat(),
                adjustment="raw",
                feed=request.feed,
                currency="USD",
                asof="-",
                sort="asc",
                limit=10000,
            ),
        )
    # Filters are by process_date, not ex-date. Scan all available processed history
    # for these symbols, then select economic dates locally. Never filter to supported types.
    yield (
        "/v1/corporate-actions",
        dict(
            symbols=symbols,
            start="1970-01-01",
            end=requested_at.date().isoformat(),
            region="us",
            data_quality="all",
            sort="asc",
            limit=1000,
        ),
    )


def collect_pages(transport, request, requested_at):
    pages = []
    for path, base in query_specs(request, requested_at):
        tokens, fingerprints = set(), set()
        token = None
        while True:
            if len(pages) >= 2000:
                raise IngestionError(
                    "page_limit", "Import exceeds the 2000-page bound; use a smaller range."
                )
            params = dict(base, **({"page_token": token} if token else {}))
            response = transport.get(path, params)
            try:
                page = CapturedPage(
                    schema_version=1,
                    path=path,
                    params=params,
                    received_at=response.received_at,
                    request_id=response.request_id,
                    body=response.body.decode("utf-8"),
                )
            except (UnicodeError, ValidationError):
                raise IngestionError(
                    "invalid_response", "Provider page metadata or encoding is unsupported."
                ) from None
            values, token = page_payload(page)
            fingerprint = wire_hash(values)
            if fingerprint in fingerprints or (token is not None and token in tokens):
                raise IngestionError(
                    "repeated_page",
                    "Provider repeated a page or pagination token; download stopped.",
                )
            fingerprints.add(fingerprint)
            pages.append(page)
            if token is None:
                break
            tokens.add(token)
    return tuple(pages)


def validate_capture(capture):
    class Replay:
        position = 0

        def get(self, path, params):
            if self.position >= len(capture.pages):
                raise IngestionError(
                    "incomplete_capture", "Saved capture is missing requested pages."
                )
            page = capture.pages[self.position]
            self.position += 1
            if page.path != path or page.params != params:
                raise IngestionError(
                    "capture_request_mismatch",
                    "Saved pages do not match the declared request and pagination.",
                )
            return Response(page.body.encode(), page.received_at, page.request_id)

    replay = Replay()
    collect_pages(replay, capture.request, capture.requested_at)
    if replay.position != len(capture.pages):
        raise IngestionError(
            "extra_capture_pages", "Saved capture contains unrequested extra pages."
        )


class Minute(Record):
    t: Timestamp
    o: Price
    h: Price
    l: Price  # noqa: E741 — Alpaca's wire field for low.
    c: Price
    v: int

    @model_validator(mode="after")
    def valid_ohlc(self):
        if not self.l <= min(self.o, self.c) <= max(self.o, self.c) <= self.h:
            raise ValueError("Inconsistent minute OHLC")
        if self.v < 0 or self.t.second or self.t.microsecond:
            raise ValueError("Minute volume/timestamp is invalid")
        return self


def normalise_bars(capture):
    request = capture.request
    calendar = {s.session: s for s in trading_sessions(request.start_session, request.end_session)}
    symbols = {i.symbol for i in request.universe}
    groups, seen, last = {}, set(), {}
    for page in capture.pages:
        if page.path != "/v2/stocks/bars":
            continue
        payload, _ = page_payload(page)
        requested_day = datetime.fromisoformat(page.params["start"]).astimezone(NY).date()
        for symbol, rows in sorted(payload.items()):
            if symbol not in symbols:
                raise IngestionError(
                    "unexpected_symbol", "Provider returned an unrequested symbol."
                )
            for raw in rows:
                if not isinstance(raw, dict) or not {"t", "o", "h", "l", "c", "v"} <= raw.keys():
                    raise IngestionError(
                        "invalid_bar", "Provider minute is missing required fields."
                    )
                volume = raw["v"]
                if (
                    isinstance(volume, bool)
                    or not isinstance(volume, (int, Decimal))
                    or not Decimal(volume).is_finite()
                    or Decimal(volume) != int(volume)
                ):
                    raise IngestionError(
                        "invalid_volume",
                        "Minute volume must be a finite nonnegative whole-share count.",
                    )
                minute = Minute.model_validate(
                    {**{k: raw[k] for k in ("t", "o", "h", "l", "c")}, "v": int(volume)}
                )
                session = calendar.get(minute.t.astimezone(NY).date())
                key = (symbol, minute.t)
                if key in seen or (requested_day in last and key <= last[requested_day]):
                    raise IngestionError(
                        "duplicate_or_unordered_bar",
                        "Provider minutes overlap or violate ascending symbol/time ordering.",
                    )
                if (
                    session is None
                    or session.session != requested_day
                    or not session.market_open <= minute.t < session.market_close
                ):
                    raise IngestionError(
                        "outside_session",
                        "Provider minute falls outside the explicitly requested regular session.",
                    )
                seen.add(key)
                last[requested_day] = key
                groups.setdefault((symbol, session.session), []).append((minute, page.received_at))
    bars = []
    for symbol in sorted(symbols):
        for day, session in calendar.items():
            records = groups.get((symbol, day), [])
            expected = [
                session.market_open + timedelta(minutes=n)
                for n in range(
                    int((session.market_close - session.market_open).total_seconds() // 60)
                )
            ]
            if [m.t for m, _ in records] != expected:
                raise IngestionError(
                    "missing_minutes",
                    f"{symbol} on {day}: missing regular-session minutes; no bars were filled in.",
                )
            minutes = [m for m, _ in records]
            revision = hashlib.sha256(
                "".join(canonical_json(m) for m in minutes).encode()
            ).hexdigest()
            bars.append(
                MarketBar(
                    schema_version=1,
                    symbol=symbol,
                    session=day,
                    interval_start=session.market_open,
                    interval_end=session.market_close,
                    available_at=session.market_close + timedelta(minutes=15),
                    first_ingested_at=max(t for _, t in records),
                    provider="alpaca",
                    feed=request.feed,
                    revision_id=revision,
                    origin=capture.origin,
                    open=minutes[0].o,
                    high=max(m.h for m in minutes),
                    low=min(m.l for m in minutes),
                    close=minutes[-1].c,
                    volume=sum(m.v for m in minutes),
                )
            )
    return tuple(bars)


def normalise_actions(capture):
    request = capture.request
    calendar = {s.session: s for s in trading_sessions(request.start_session, request.end_session)}
    symbols = {i.symbol for i in request.universe}
    actions, ids = [], set()
    for page in capture.pages:
        if page.path != "/v1/corporate-actions":
            continue
        payload, _ = page_payload(page)
        for kind, records in payload.items():
            for raw in records:
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
                    raise IngestionError(
                        "invalid_action", "Corporate action is missing its stable source ID."
                    )
                if raw["id"] in ids:
                    raise IngestionError(
                        "duplicate_action", "Corporate-action pages repeat an event ID."
                    )
                ids.add(raw["id"])
                process_date = TypeAdapter(Session).validate_python(raw.get("process_date"))
                if kind in ("forward_splits", "cash_dividends") and raw.get("ex_date") is None:
                    raise IngestionError(
                        "incomplete_actions",
                        "A split/dividend is missing its ex-date; action coverage is unsupported.",
                    )
                effective = TypeAdapter(Session).validate_python(
                    raw.get("ex_date") or raw.get("effective_date") or raw.get("process_date")
                )
                in_range = request.start_session <= effective <= request.end_session
                if kind not in ("forward_splits", "cash_dividends"):
                    if in_range or request.start_session <= process_date <= request.end_session:
                        raise IngestionError(
                            "unsupported_action",
                            "Requested range contains an unsupported corporate-action type.",
                        )
                    continue
                if not in_range:
                    continue
                if raw.get("symbol") not in symbols or effective not in calendar:
                    raise IngestionError(
                        "action_scope",
                        "Corporate action is outside the requested universe or exchange sessions.",
                    )
                values = dict(
                    schema_version=1,
                    action_id=raw["id"],
                    symbol=raw["symbol"],
                    effective_session=effective,
                    available_at=calendar[effective].market_open,
                    first_ingested_at=page.received_at,
                    revision_id=wire_hash(raw),
                )
                if kind == "forward_splits":
                    old = TypeAdapter(Price).validate_python(raw.get("old_rate"))
                    new = TypeAdapter(Price).validate_python(raw.get("new_rate"))
                    ratio = new / old
                    if (
                        ratio != int(ratio)
                        or ratio < 2
                        or raw.get("due_bill_redemption_date") is not None
                    ):
                        raise IngestionError(
                            "unsupported_split",
                            "Only whole-number forward splits without due bills are supported.",
                        )
                    action = CorporateAction(
                        **values,
                        kind="split",
                        split_ratio=int(ratio),
                        cash_amount_usd=None,
                        pay_date=None,
                    )
                else:
                    if (
                        raw.get("special") is not False
                        or raw.get("foreign") is not False
                        or any(
                            raw.get(k) is not None
                            for k in ("due_bill_on_date", "due_bill_off_date")
                        )
                    ):
                        raise IngestionError(
                            "unsupported_dividend",
                            "Only regular domestic cash dividends without due bills are supported.",
                        )
                    action = CorporateAction(
                        **values,
                        kind="cash_dividend",
                        split_ratio=None,
                        cash_amount_usd=raw.get("rate"),
                        pay_date=raw.get("payable_date"),
                    )
                actions.append(action)
    return tuple(sorted(actions, key=lambda a: (a.symbol, a.effective_session, a.kind)))


def provenance_text(capture_id):
    return (
        f"{ADAPTER_VERSION}; original response capture SHA-256 {capture_id}; "
        "complete paginated read, no symbol remapping."
    )


def normalise_capture(capture: SourceCapture, capture_id: str):
    validate_capture(capture)
    bars, actions = normalise_bars(capture), normalise_actions(capture)
    request = capture.request
    limitations = [
        "unknown_revision_timing",
        "historical_availability_assumed",
        "historical_action_timing_assumed",
        "provider_action_completeness_unverified",
        "fixed_declared_universe",
        "regular_minutes_aggregation",
        "closing_boundary_auction_excluded",
    ]
    if capture.origin == "synthetic":
        limitations.append("synthetic_data")
    if request.feed == "iex":
        limitations.append("single_exchange_iex")
    plan = SnapshotPlan(
        schema_version=1,
        origin=capture.origin,
        provider="alpaca",
        feed=request.feed,
        universe=request.universe,
        coverage_start=request.start_session,
        coverage_end=request.end_session,
        first_execution_session=request.first_execution_session,
        warmup_sessions=request.warmup_sessions,
        retrieved_at=capture.captured_at,
        retrieval_convention=provenance_text(capture_id),
        availability_convention=(
            "Historical exploratory assumptions: completed regular-session bars "
            "at close + 15 minutes; actions at ex/effective open. Original "
            "publication and revision times are unknown; ingestion timestamps "
            "are actual capture times."
        ),
        revision_policy="unknown",
        limitations=tuple(limitations),
        zero_volume_policy=request.zero_volume_policy,
        corporate_actions_coverage="complete",
        corporate_actions_source=(
            "Alpaca v1 corporate-actions, all types and data_quality=all, "
            "process dates 1970 through capture request date; complete "
            "pagination then economic-date filtering. Completeness is relative "
            "to the provider response, not independently authenticated."
        ),
    )
    return plan, bars, actions
