"""Deterministic pre-publication checks. Missing sessions never become fabricated bars."""

from datetime import timedelta
from decimal import Decimal
from importlib.metadata import version

import pandas_market_calendars as calendars

from buffetbot.contracts import MarketBar
from buffetbot.dataset_models import (
    CorporateAction,
    Finding,
    QualityReport,
    SnapshotPlan,
    SymbolCoverage,
    TradingSession,
)


def trading_sessions(start, end) -> tuple[TradingSession, ...]:
    if version("pandas_market_calendars") != "5.4.0":
        raise ValueError("Snapshots require the pinned pandas_market_calendars 5.4.0 calendar")
    schedule = calendars.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    return tuple(
        TradingSession(
            session=index.date(),
            market_open=row.market_open.to_pydatetime(),
            market_close=row.market_close.to_pydatetime(),
        )
        for index, row in schedule.iterrows()
    )


def check_quality(
    plan: SnapshotPlan,
    bars: tuple[MarketBar, ...],
    actions: tuple[CorporateAction, ...],
    sessions: tuple[TradingSession, ...],
) -> QualityReport:
    findings = []

    def add(code, detail, symbol=None, session=None, severity="error"):
        findings.append(
            Finding(severity=severity, code=code, detail=detail, symbol=symbol, session=session)
        )

    calendar = {s.session: s for s in sessions}
    instruments = {i.symbol: i for i in plan.universe}
    keys = [(b.symbol, b.session) for b in bars]
    if keys != sorted(set(keys)):
        add("bar_order_or_duplicate", "Bars must be unique and ordered by symbol, session.")
    action_keys = [(a.symbol, a.effective_session, a.kind) for a in actions]
    if action_keys != sorted(set(action_keys)) or len({a.action_id for a in actions}) != len(
        actions
    ):
        add("action_order_or_duplicate", "Actions require unique IDs and ordered symbol/date/kind.")
    if plan.first_execution_session not in calendar:
        add("execution_not_session", "First execution date must be an exchange session.")
    prior = [d for d in calendar if d < plan.first_execution_session]
    if len(prior) < plan.warmup_sessions:
        add("insufficient_warmup", "Requested coverage does not include all warmup sessions.")
    required_start = (
        prior[-plan.warmup_sessions]
        if plan.warmup_sessions and len(prior) >= plan.warmup_sessions
        else plan.first_execution_session
    )
    coverage = []
    for instrument in plan.universe:
        symbol = instrument.symbol
        if instrument.listed_on > required_start or (
            instrument.delisted_on and instrument.delisted_on <= plan.coverage_end
        ):
            add(
                "listing_coverage", "Listing must cover warmup and the declared experiment.", symbol
            )
        expected = {
            d
            for d in calendar
            if d >= instrument.listed_on
            and (instrument.delisted_on is None or d < instrument.delisted_on)
        }
        observed = {b.session for b in bars if b.symbol == symbol}
        missing = tuple(sorted(expected - observed))
        if missing:
            add(
                "missing_bars",
                "Expected listed sessions are missing; no forward fill is allowed.",
                symbol,
            )
        coverage.append(
            SymbolCoverage(
                symbol=symbol,
                expected_bars=len(expected),
                observed_bars=sum(b.symbol == symbol for b in bars),
                missing_sessions=missing,
            )
        )

    for bar in bars:
        if (bar.origin, bar.provider, bar.feed) != (plan.origin, plan.provider, plan.feed):
            add(
                "bar_provenance",
                "Bar origin/provider/feed must match the manifest.",
                bar.symbol,
                bar.session,
            )
        instrument = instruments.get(bar.symbol)
        session = calendar.get(bar.session)
        if (
            instrument is None
            or bar.session < instrument.listed_on
            or (instrument.delisted_on and bar.session >= instrument.delisted_on)
        ):
            add(
                "unlisted_bar",
                "Bar is outside the declared universe or listing.",
                bar.symbol,
                bar.session,
            )
        if session is None:
            add(
                "unknown_session",
                "Bar is outside coverage or falls on a market closure.",
                bar.symbol,
                bar.session,
            )
        elif (bar.interval_start, bar.interval_end) != (session.market_open, session.market_close):
            add(
                "session_hours",
                "Daily interval must match calendar open/close, including early closes.",
                bar.symbol,
                bar.session,
            )
        if bar.first_ingested_at > plan.retrieved_at:
            add(
                "retrieval_timing",
                "Retrieval completion cannot precede ingestion.",
                bar.symbol,
                bar.session,
            )
        if bar.volume == 0:
            add(
                "zero_volume",
                "Zero volume retained explicitly; no liquidity is inferred.",
                bar.symbol,
                bar.session,
                severity="warning" if plan.zero_volume_policy == "allow_with_warning" else "error",
            )

    if plan.corporate_actions_coverage != "complete":
        add(
            "incomplete_actions",
            "Complete split/dividend metadata or explicit no-action source coverage is required.",
        )
    for action in actions:
        instrument = instruments.get(action.symbol)
        if (
            instrument is None
            or action.effective_session not in calendar
            or (
                action.effective_session < instrument.listed_on
                or (instrument.delisted_on and action.effective_session >= instrument.delisted_on)
            )
        ):
            add(
                "action_session",
                "Action must occur in covered, listed exchange sessions.",
                action.symbol,
            )
        if action.first_ingested_at > plan.retrieved_at:
            add(
                "action_retrieval_timing",
                "Action ingestion cannot follow retrieval completion.",
                action.symbol,
            )

    # Large opening gaps are observations for review, never automatically classified as splits.
    splits = {(a.symbol, a.effective_session): a.split_ratio for a in actions if a.kind == "split"}
    previous = {}
    for bar in bars:
        if bar.symbol in previous:
            comparable_close = previous[bar.symbol] / Decimal(
                splits.get((bar.symbol, bar.session), 1)
            )
            if abs(bar.open / comparable_close - 1) >= Decimal("0.20"):
                add(
                    "large_opening_gap",
                    "Opening gap is at least 20% after declared splits; review source data.",
                    bar.symbol,
                    bar.session,
                    severity="warning",
                )
        previous[bar.symbol] = bar.close
    if plan.revision_policy == "unknown":
        add(
            "unknown_revision_timing",
            "Historical revisions cannot establish point-in-time availability.",
            severity="warning",
        )
    if plan.origin == "synthetic":
        add(
            "synthetic_data",
            "Fabricated fixture; not validated market history or trading performance.",
            severity="warning",
        )
    days = (plan.coverage_end - plan.coverage_start).days + 1
    return QualityReport(
        schema_version=1,
        origin=plan.origin,
        usable=not any(f.severity == "error" for f in findings),
        coverage=tuple(coverage),
        expected_closures=tuple(
            plan.coverage_start + timedelta(days=i)
            for i in range(days)
            if plan.coverage_start + timedelta(days=i) not in calendar
        ),
        shortened_sessions=tuple(
            s.session
            for s in sessions
            if s.market_close - s.market_open < timedelta(hours=6, minutes=30)
        ),
        findings=tuple(findings),
    )
