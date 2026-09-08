"""Atomic local Parquet snapshots with verified, in-memory reads.

Identity is SHA-256 of the canonical manifest, which includes each Parquet checksum.
Source bars omit dataset_id; readers bind it after verification, avoiding a hash cycle.
"""

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from buffetbot.contracts import (
    NY,
    MarketBar,
    MarketObservation,
    Price,
    Record,
    Session,
    Symbol,
    Timestamp,
)
from buffetbot.dataset_models import (
    CorporateAction,
    QualityReport,
    SnapshotFile,
    SnapshotManifest,
    SnapshotPlan,
    TradingSession,
)
from buffetbot.dataset_quality import check_quality, trading_sessions
from buffetbot.experiments import DatasetReference, ExperimentSpecification, canonical_json


class SnapshotError(ValueError):
    """Recoverable input/storage failure; existing snapshots are never repaired in place."""


class SnapshotQualityError(SnapshotError):
    def __init__(self, report: QualityReport):
        super().__init__(
            "Dataset failed quality checks; correct the input and publish a new snapshot."
        )
        self.report = report


DATE = pa.date32()
TIME = pa.timestamp("us", tz="UTC")
PRICE = pa.decimal128(24, 8)
STRING = pa.string()


def schema(name, fields):
    return pa.schema(fields, metadata={b"buffetbot.schema": name.encode()})


BAR_SCHEMA = schema(
    "market_bar.v1",
    [
        ("schema_version", pa.int8()),
        ("symbol", STRING),
        ("session", DATE),
        ("interval", STRING),
        ("interval_start", TIME),
        ("interval_end", TIME),
        ("available_at", TIME),
        ("first_ingested_at", TIME),
        ("provider", STRING),
        ("feed", STRING),
        ("revision_id", STRING),
        ("origin", STRING),
        ("adjustment", STRING),
        ("currency", STRING),
        ("open", PRICE),
        ("high", PRICE),
        ("low", PRICE),
        ("close", PRICE),
        ("volume", pa.uint64()),
    ],
)
ACTION_SCHEMA = schema(
    "corporate_action.v1",
    [
        ("schema_version", pa.int8()),
        ("action_id", STRING),
        ("symbol", STRING),
        ("kind", STRING),
        ("effective_session", DATE),
        ("available_at", TIME),
        ("first_ingested_at", TIME),
        ("revision_id", STRING),
        ("split_ratio", pa.int64()),
        ("cash_amount_usd", PRICE),
        ("pay_date", DATE),
    ],
)
SESSION_SCHEMA = schema(
    "trading_session.v1",
    [
        ("session", DATE),
        ("market_open", TIME),
        ("market_close", TIME),
    ],
)
TABLES = (
    ("bars.parquet", MarketBar, BAR_SCHEMA),
    ("actions.parquet", CorporateAction, ACTION_SCHEMA),
    ("sessions.parquet", TradingSession, SESSION_SCHEMA),
)


def arrow_table(records, table_schema):
    return pa.Table.from_pylist([r.model_dump() for r in records], schema=table_schema)


@dataclass(frozen=True)
class Snapshot:
    dataset_id: str
    manifest: SnapshotManifest
    bars: tuple[MarketBar, ...]
    actions: tuple[CorporateAction, ...]
    sessions: tuple[TradingSession, ...]

    def observations(self) -> tuple[MarketObservation, ...]:
        return tuple(
            MarketObservation(**b.model_dump(), dataset_id=self.dataset_id) for b in self.bars
        )

    def reference(self) -> DatasetReference:
        plan = self.manifest.plan
        return DatasetReference(
            dataset_id=self.dataset_id,
            kind="market",
            schema_id=plan.schema_id,
            origin=plan.origin,
            provider=plan.provider,
            feed=plan.feed,
            revision_policy=plan.revision_policy,
            limitations=plan.limitations,
        )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sync(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_directory(directory: Path, dataset_id: str) -> Snapshot:
    """Also used before the atomic rename; no unchecked data reaches a caller."""
    if directory.is_symlink() or not directory.is_dir():
        raise SnapshotError("Snapshot directory is missing or is a symlink.")
    expected_names = {"manifest.json", *(name for name, _, _ in TABLES)}
    if {p.name for p in directory.iterdir()} != expected_names:
        raise SnapshotError(
            "Snapshot files are missing or unsupported; restore the original snapshot."
        )
    if any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        raise SnapshotError("Snapshot members must be regular files, without symlinks.")
    raw_manifest = (directory / "manifest.json").read_bytes()
    if sha256(raw_manifest) != dataset_id:
        raise SnapshotError("Manifest checksum mismatch; restore the original snapshot.")
    manifest = SnapshotManifest.model_validate_json(raw_manifest)
    if canonical_json(manifest).encode() != raw_manifest:
        raise SnapshotError("Manifest must use the supported canonical encoding.")
    records = []
    for member, (name, record_type, table_schema) in zip(manifest.files, TABLES, strict=True):
        # Read once: checksum and decode the same bytes, then query the verified in-memory data.
        data = (directory / name).read_bytes()
        if len(data) != member.size_bytes or sha256(data) != member.sha256:
            raise SnapshotError(f"Checksum mismatch for {name}; restore the original snapshot.")
        table = pq.read_table(pa.BufferReader(data))
        if not table.schema.equals(table_schema, check_metadata=True) or len(table) != member.rows:
            raise SnapshotError(f"Unsupported schema or row count in {name}.")
        records.append(tuple(record_type.model_validate(row) for row in table.to_pylist()))
    bars, actions, sessions = records
    plan = manifest.plan
    if sessions != trading_sessions(plan.coverage_start, plan.coverage_end):
        raise SnapshotError("Saved sessions disagree with the pinned calendar.")
    quality = check_quality(plan, bars, actions, sessions)
    if quality != manifest.quality or not quality.usable:
        raise SnapshotError("Saved quality findings disagree with the verified dataset.")
    return Snapshot(dataset_id, manifest, bars, actions, sessions)


def read_snapshot(data_root: Path, dataset_id: str) -> Snapshot:
    if not isinstance(dataset_id, str) or not re.fullmatch(r"[a-f0-9]{64}", dataset_id):
        raise SnapshotError("Snapshot ID must be a lowercase SHA-256 digest.")
    try:
        store = Path(data_root) / "snapshots"
        if store.is_symlink():
            raise SnapshotError("Snapshot store must not be a symlink.")
        return _read_directory(store / dataset_id, dataset_id)
    except SnapshotError:
        raise
    except (OSError, ValueError, pa.ArrowException) as error:
        raise SnapshotError(
            "Cannot read snapshot: invalid schema/data or inaccessible files."
        ) from error


def publish_snapshot(data_root: Path, plan: SnapshotPlan, bars, actions) -> Snapshot:
    """Validate, stage on the same filesystem, fsync, verify, and atomically rename.

    Identical inputs reuse a verified snapshot. Changed records/provenance produce a new
    identity. Leftover .staging-* directories from SIGKILL are never valid snapshot IDs.
    """
    stage = None
    try:
        plan = SnapshotPlan.model_validate(plan)
        bars = tuple(MarketBar.model_validate(b) for b in bars)
        actions = tuple(CorporateAction.model_validate(a) for a in actions)
        sessions = trading_sessions(plan.coverage_start, plan.coverage_end)
        quality = check_quality(plan, bars, actions, sessions)
        if not quality.usable:
            raise SnapshotQualityError(quality)
        store = Path(data_root) / "snapshots"
        if store.is_symlink():
            raise SnapshotError("Snapshot store must not be a symlink.")
        store.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=store))
        files = []
        for (name, _, table_schema), records in zip(TABLES, (bars, actions, sessions), strict=True):
            path = stage / name
            pq.write_table(
                arrow_table(records, table_schema), path, compression="zstd", version="2.6"
            )
            _sync(path)
            data = path.read_bytes()
            files.append(
                SnapshotFile(
                    name=name, sha256=sha256(data), rows=len(records), size_bytes=len(data)
                )
            )
        manifest = SnapshotManifest(
            schema_version=1,
            plan=plan,
            files=tuple(files),
            quality=quality,
            parquet_writer=f"pyarrow:{pa.__version__}",
        )
        encoded = canonical_json(manifest).encode()
        dataset_id = sha256(encoded)
        (stage / "manifest.json").write_bytes(encoded)
        _sync(stage / "manifest.json")
        _sync(stage)
        snapshot = _read_directory(stage, dataset_id)
        destination = store / dataset_id
        if destination.exists() or destination.is_symlink():
            return read_snapshot(data_root, dataset_id)
        try:
            os.rename(stage, destination)
        except OSError:
            # An identical concurrent publisher may have won the rename. Verify it fully.
            if destination.exists():
                return read_snapshot(data_root, dataset_id)
            raise
        _sync(store)
        return snapshot
    except SnapshotError:
        raise
    except (OSError, ValueError, OverflowError, pa.ArrowException) as error:
        raise SnapshotError(
            "Cannot publish snapshot: invalid records or a local storage failure."
        ) from error
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def inspect_snapshot(data_root: Path, dataset_id: str) -> dict:
    """The shared report path: verify everything before querying coverage with DuckDB."""
    snapshot = read_snapshot(data_root, dataset_id)
    with duckdb.connect(
        config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false"}
    ) as db:
        db.register("bars", arrow_table(snapshot.bars, BAR_SCHEMA))
        rows = db.execute("""
            SELECT symbol, count(*) AS bars, min(session), max(session),
                   count(*) FILTER (WHERE volume = 0)
            FROM bars GROUP BY symbol ORDER BY symbol
        """).fetchall()
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "origin": snapshot.manifest.plan.origin,
        "status": "verified",
        "quality": snapshot.manifest.quality.model_dump(mode="json"),
        "coverage": [
            dict(
                symbol=s,
                bars=n,
                first_session=str(first),
                last_session=str(last),
                zero_volume_bars=zero,
            )
            for s, n, first, last, zero in rows
        ],
        "manifest": snapshot.manifest.model_dump(mode="json"),
    }


def validate_snapshot_for_experiment(
    snapshot: Snapshot, specification: ExperimentSpecification
) -> Snapshot:
    """Bind a verified snapshot to the exact provenance, listing and warmup request."""
    specification = ExperimentSpecification.model_validate(specification)
    reference = snapshot.reference()
    declared = next(
        (r for r in specification.datasets if r.dataset_id == snapshot.dataset_id), None
    )
    if declared != reference:
        raise SnapshotError("Experiment must declare the exact verified dataset reference.")
    plan = snapshot.manifest.plan
    instruments = {i.symbol: i for i in plan.universe}
    if any(instruments.get(i.symbol) != i for i in specification.universe):
        raise SnapshotError("Experiment instruments must match the snapshot listing metadata.")
    sessions = [s.session for s in snapshot.sessions]
    prior = [d for d in sessions if d < specification.start_session]
    if (
        specification.start_session not in sessions
        or specification.end_session > plan.coverage_end
        or len(prior) < specification.warmup_sessions
    ):
        raise SnapshotError("Snapshot does not cover the experiment and its warmup sessions.")
    required_start = (
        prior[-specification.warmup_sessions]
        if specification.warmup_sessions
        else specification.start_session
    )
    if any(i.listed_on > required_start for i in specification.universe):
        raise SnapshotError("Experiment warmup would require pre-listing history.")
    return snapshot


class ResearchBar(Record):
    symbol: Symbol
    session: Session
    available_at: Timestamp
    open: Price
    high: Price
    low: Price
    close: Price


def research_view(snapshot: Snapshot, *, cutoff: datetime) -> dict:
    """An explicit split-only view, derived as of a cutoff; raw bars stay intact.

    Returns a research export, not a strategy context or an executable price series.
    Existing context contracts still enforce computation/ingestion timing in paper mode.
    """
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise SnapshotError("Research cutoff requires a timezone-aware datetime.")
    plan = snapshot.manifest.plan
    if not plan.coverage_start <= cutoff.astimezone(NY).date() <= plan.coverage_end:
        raise SnapshotError("Research cutoff must stay within the declared action coverage.")
    sessions = {s.session: s for s in snapshot.sessions}
    splits = [
        a
        for a in snapshot.actions
        if a.kind == "split" and sessions[a.effective_session].market_open <= cutoff
    ]
    if any(a.available_at > cutoff for a in splits):
        raise SnapshotError("An effective split was not available by this research cutoff.")
    rows = []
    for bar in snapshot.bars:
        if bar.available_at > cutoff:
            continue
        relevant = [
            a for a in splits if a.symbol == bar.symbol and bar.session < a.effective_session
        ]
        factor = Decimal(1)
        for action in relevant:
            factor *= action.split_ratio
        try:
            rows.append(
                ResearchBar(
                    symbol=bar.symbol,
                    session=bar.session,
                    available_at=max([bar.available_at, *(a.available_at for a in relevant)]),
                    **{
                        name: (getattr(bar, name) / factor).quantize(Decimal("0.00000001"))
                        for name in ("open", "high", "low", "close")
                    },
                ).model_dump(mode="json")
            )
        except ValidationError as error:
            raise SnapshotError(
                "Split-adjusted price is outside the supported decimal precision."
            ) from error
    return {
        "schema_version": 1,
        "origin": snapshot.manifest.plan.origin,
        "dataset_id": snapshot.dataset_id,
        "view": "split_as_of_cutoff",
        "cutoff": cutoff.isoformat(),
        "rounding": "8_decimal_places_half_even",
        "split_action_ids": [a.action_id for a in splits],
        "limitations": list(snapshot.manifest.plan.limitations),
        "bars": rows,
    }
