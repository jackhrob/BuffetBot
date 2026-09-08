"""Storage/quality failures that would otherwise invalidate research or leak partial data."""

import csv
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from buffetbot.contracts import MarketBar
from buffetbot.dataset_models import CorporateAction, SnapshotPlan
from buffetbot.experiments import ExperimentSpecification
from buffetbot.fixtures import load_fixture
from buffetbot.snapshots import (
    SnapshotError,
    SnapshotQualityError,
    inspect_snapshot,
    publish_snapshot,
    read_snapshot,
    research_view,
    validate_snapshot_for_experiment,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def snapshot(tmp_path):
    return publish_snapshot(tmp_path, *load_fixture())


def test_offline_publication_roundtrip_identity_provenance_and_duckdb_report(tmp_path, snapshot):
    reloaded = read_snapshot(tmp_path, snapshot.dataset_id)
    assert reloaded == snapshot
    assert reloaded.bars == load_fixture()[1]
    assert reloaded.actions == load_fixture()[2]
    assert {b.dataset_id for b in reloaded.observations()} == {snapshot.dataset_id}
    assert reloaded.reference().origin == "synthetic"
    path = tmp_path / "snapshots" / snapshot.dataset_id
    assert hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest() == snapshot.dataset_id
    table = pq.read_table(path / "bars.parquet")
    assert "dataset_id" not in table.column_names  # No circular content identity.
    assert table["close"][0].as_py() == Decimal("105")
    report = inspect_snapshot(tmp_path, snapshot.dataset_id)
    assert report["origin"] == report["quality"]["origin"] == "synthetic"
    assert report["quality"]["usable"]
    assert report["quality"]["expected_closures"] == ["2024-07-04", "2024-07-06", "2024-07-07"]
    assert report["quality"]["shortened_sessions"] == ["2024-07-03"]
    assert report["coverage"] == [
        dict(
            symbol="BBTEST",
            bars=6,
            first_session="2024-07-01",
            last_session="2024-07-09",
            zero_volume_bars=0,
        )
    ]
    assert reloaded.sessions[2].market_close.isoformat() == "2024-07-03T17:00:00+00:00"


def test_reimport_is_idempotent_and_revisions_never_overwrite_a_referenced_version(
    tmp_path, snapshot
):
    path = tmp_path / "snapshots" / snapshot.dataset_id
    original = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}
    assert publish_snapshot(tmp_path, *load_fixture()).dataset_id == snapshot.dataset_id
    plan, bars, actions = load_fixture()
    revised = bars[0].model_copy(update={"close": Decimal("104"), "revision_id": "fixture.v2"})
    changed = publish_snapshot(tmp_path, plan, (revised, *bars[1:]), actions)
    assert changed.dataset_id != snapshot.dataset_id
    assert read_snapshot(tmp_path, snapshot.dataset_id).bars[0].close == 105
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()} == original


def test_two_publishers_converge_without_overwriting(tmp_path):
    def publish(_):
        return publish_snapshot(tmp_path, *load_fixture()).dataset_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(publish, range(2)))
    assert ids[0] == ids[1]
    assert [p.name for p in (tmp_path / "snapshots").iterdir()] == [ids[0]]


@pytest.mark.parametrize("crash_at", ["first_parquet", "before_rename"])
def test_process_death_never_exposes_staging_and_retry_can_publish(tmp_path, crash_at):
    script = """
import os, sys
from pathlib import Path
import buffetbot.snapshots as storage
from buffetbot.fixtures import load_fixture
def stop(*args, **kwargs):
    os._exit(77)
if sys.argv[2] == 'before_rename':
    storage.os.rename = stop
else:
    storage._sync = stop
storage.publish_snapshot(Path(sys.argv[1]), *load_fixture())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), crash_at],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 77, result.stderr
    store = tmp_path / "snapshots"
    leftovers = list(store.iterdir())
    assert len(leftovers) == 1 and leftovers[0].name.startswith(".staging-")
    with pytest.raises(SnapshotError):
        read_snapshot(tmp_path, leftovers[0].name)
    if crash_at == "before_rename":
        digest = hashlib.sha256((leftovers[0] / "manifest.json").read_bytes()).hexdigest()
        with pytest.raises(SnapshotError, match="missing"):
            read_snapshot(tmp_path, digest)
    snapshot = publish_snapshot(tmp_path, *load_fixture())
    assert read_snapshot(tmp_path, snapshot.dataset_id).manifest.quality.usable


@pytest.mark.parametrize(
    "damage", ["bars", "manifest", "missing_actions", "extra", "symlink", "directory"]
)
def test_reader_rejects_corrupt_missing_and_unsupported_members(tmp_path, snapshot, damage):
    directory = tmp_path / "snapshots" / snapshot.dataset_id
    if damage == "bars":
        with (directory / "bars.parquet").open("ab") as target:
            target.write(b"changed")
    elif damage == "manifest":
        with (directory / "manifest.json").open("ab") as target:
            target.write(b" ")
    elif damage == "missing_actions":
        (directory / "actions.parquet").unlink()
    elif damage == "extra":
        (directory / "future-format.parquet").write_bytes(b"unsupported")
    else:
        member = directory / "actions.parquet"
        original = tmp_path / "original.parquet"
        member.rename(original)
        if damage == "symlink":
            member.symlink_to(original)
        else:
            member.mkdir()
    with pytest.raises(SnapshotError):
        inspect_snapshot(tmp_path, snapshot.dataset_id)
    # An identical reimport must refuse to repair/replace the damaged referenced version.
    with pytest.raises(SnapshotError):
        publish_snapshot(tmp_path, *load_fixture())


@pytest.mark.parametrize("change", ["version", "metadata", "rows", "quality"])
def test_recomputed_manifest_hash_cannot_hide_unsupported_or_inconsistent_input(
    tmp_path, snapshot, change
):
    directory = tmp_path / "snapshots" / snapshot.dataset_id
    path = directory / "manifest.json"
    data = json.loads(path.read_text())
    if change == "version":
        data["schema_version"] = 2
    elif change == "metadata":
        data["plan"]["feed"] = "wrong_feed"
    elif change == "rows":
        data["files"][0]["rows"] += 1
    else:
        data["quality"]["expected_closures"] = []
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(encoded)
    new_id = hashlib.sha256(encoded).hexdigest()
    directory.rename(directory.parent / new_id)
    with pytest.raises(SnapshotError):
        read_snapshot(tmp_path, new_id)


@pytest.mark.parametrize(
    "case,code", [("missing_bar", "missing_bars"), ("incomplete_actions", "incomplete_actions")]
)
def test_incomplete_fixture_reports_failure_without_publishing(tmp_path, case, code):
    with pytest.raises(SnapshotQualityError) as failure:
        publish_snapshot(tmp_path, *load_fixture(case))
    report = failure.value.report
    assert report.origin == "synthetic" and not report.usable
    assert code in {f.code for f in report.findings}
    if case == "missing_bar":
        assert report.coverage[0].missing_sessions == (date(2024, 7, 5),)
        assert report.coverage[0].observed_bars == 5
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize(
    "problem,code",
    [
        ("duplicate", "bar_order_or_duplicate"),
        ("unordered", "bar_order_or_duplicate"),
        ("holiday", "unknown_session"),
        ("early_close", "session_hours"),
        ("warmup", "insufficient_warmup"),
        ("listing", "listing_coverage"),
        ("before_listing", "unlisted_bar"),
        ("provenance", "bar_provenance"),
        ("retrieval", "retrieval_timing"),
        ("action_duplicate", "action_order_or_duplicate"),
        ("action_holiday", "action_session"),
        ("action_ingestion", "action_retrieval_timing"),
    ],
)
def test_quality_blocks_wrong_sessions_order_listing_and_provenance(tmp_path, problem, code):
    plan, bars, actions = load_fixture()
    if problem == "duplicate":
        bars = (*bars, bars[-1])
    elif problem == "unordered":
        bars = tuple(reversed(bars))
    elif problem == "holiday":
        b = bars[2]
        bars = (
            *bars[:2],
            b.model_copy(
                update={
                    "session": date(2024, 7, 4),
                    **{
                        k: getattr(b, k) + timedelta(days=1)
                        for k in ("interval_start", "interval_end", "available_at")
                    },
                }
            ),
            *bars[3:],
        )
    elif problem == "early_close":
        b = bars[2]
        bars = (
            *bars[:2],
            b.model_copy(
                update={
                    "interval_end": b.interval_end + timedelta(hours=3),
                    "available_at": b.available_at + timedelta(hours=3),
                }
            ),
            *bars[3:],
        )
    elif problem == "warmup":
        plan = plan.model_copy(update={"warmup_sessions": 2})
    elif problem in ("listing", "before_listing"):
        instrument = plan.universe[0].model_copy(update={"listed_on": date(2024, 7, 2)})
        plan = plan.model_copy(update={"universe": (instrument,)})
        if problem == "listing":
            bars = bars[1:]
    elif problem == "provenance":
        bars = (bars[0].model_copy(update={"feed": "another_feed"}), *bars[1:])
    elif problem == "retrieval":
        plan = plan.model_copy(update={"retrieved_at": plan.retrieved_at - timedelta(seconds=1)})
    elif problem == "action_duplicate":
        actions = (*actions, actions[0])
    elif problem == "action_holiday":
        actions = (
            actions[0].model_copy(update={"effective_session": date(2024, 7, 4)}),
            actions[1],
        )
    elif problem == "action_ingestion":
        actions = (
            actions[0].model_copy(
                update={"first_ingested_at": plan.retrieved_at + timedelta(days=1)}
            ),
            actions[1],
        )
    with pytest.raises(SnapshotQualityError) as failure:
        publish_snapshot(tmp_path, plan, bars, actions)
    assert code in {f.code for f in failure.value.report.findings}


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", "NaN"),
        ("close", "Infinity"),
        ("low", "0"),
        ("high", "90"),
        ("volume", -1),
        ("volume", 1.5),
        ("interval_start", "2024-07-01T13:30:00"),
    ],
)
def test_malformed_source_rows_are_recoverable_publish_errors(tmp_path, field, value):
    plan, bars, actions = load_fixture()
    invalid = bars[0].model_dump(mode="json")
    invalid[field] = value
    with pytest.raises(SnapshotError):
        publish_snapshot(tmp_path, plan, (invalid, *bars[1:]), actions)
    assert not (tmp_path / "snapshots").exists()


def test_zero_volume_is_explicit_policy_and_large_gap_is_preserved(tmp_path):
    plan, bars, actions = load_fixture("zero_volume")
    snapshot = publish_snapshot(tmp_path, plan, bars, actions)
    report = inspect_snapshot(tmp_path, snapshot.dataset_id)
    assert report["coverage"][0]["zero_volume_bars"] == 1
    assert any(
        f["code"] == "zero_volume" and f["severity"] == "warning"
        for f in report["quality"]["findings"]
    )
    with pytest.raises(SnapshotQualityError):
        publish_snapshot(
            tmp_path, plan.model_copy(update={"zero_volume_policy": "reject"}), bars, actions
        )
    gap = publish_snapshot(tmp_path, *load_fixture("gap"))
    assert gap.bars[4].open == 80
    assert any(f.code == "large_opening_gap" for f in gap.manifest.quality.findings)


@pytest.mark.parametrize(
    "update",
    [
        {"kind": "special_dividend"},
        {"split_ratio": "2"},
        {"split_ratio": 0.5},
        {"split_ratio": 1},
        {"pay_date": "2024-07-09"},
    ],
)
def test_unsupported_actions_are_rejected(update):
    action = load_fixture()[2][0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        CorporateAction.model_validate(dict(action, **update))


def test_dividend_requires_pay_date_and_empty_actions_require_explicit_coverage(tmp_path):
    plan, bars, actions = load_fixture()
    dividend = actions[1].model_dump(mode="json")
    with pytest.raises(ValidationError):
        CorporateAction.model_validate(dict(dividend, pay_date=None))
    with pytest.raises(SnapshotQualityError):
        publish_snapshot(
            tmp_path, plan.model_copy(update={"corporate_actions_coverage": "unknown"}), bars, ()
        )
    # A different fabricated ordinary-price dataset can explicitly attest no actions.
    constant = tuple(
        MarketBar.model_validate(
            dict(b.model_dump(), open="100", high="101", low="99", close="100")
        )
        for b in bars
    )
    empty = publish_snapshot(
        tmp_path,
        plan.model_copy(
            update={"corporate_actions_source": "Synthetic no-action case; full range covered."}
        ),
        constant,
        (),
    )
    assert read_snapshot(tmp_path, empty.dataset_id).actions == ()


def test_research_adjusts_only_effective_known_splits_and_keeps_raw_prices(tmp_path, snapshot):
    before = research_view(snapshot, cutoff=datetime.fromisoformat("2024-07-02T20:15:00+00:00"))
    after = research_view(snapshot, cutoff=datetime.fromisoformat("2024-07-03T17:15:00+00:00"))
    assert before["origin"] == after["origin"] == "synthetic"
    assert before["bars"][0]["close"] == "105"
    assert before["split_action_ids"] == []
    assert after["bars"][0]["close"] == "52.5"
    assert after["bars"][1]["close"] == "56"
    assert after["bars"][2]["close"] == "57"
    assert snapshot.bars[0].close == 105 and snapshot.bars[1].open == 110
    assert read_snapshot(tmp_path, snapshot.dataset_id).bars == snapshot.bars
    with pytest.raises(SnapshotError):
        research_view(snapshot, cutoff=datetime(2024, 7, 3))
    with pytest.raises(SnapshotError, match="coverage"):
        research_view(snapshot, cutoff=datetime.fromisoformat("2024-07-10T20:00:00+00:00"))
    plan, bars, actions = load_fixture()
    late = actions[0].model_copy(
        update={"available_at": datetime.fromisoformat("2024-07-05T20:00:00+00:00")}
    )
    unknown_at_cutoff = publish_snapshot(tmp_path, plan, bars, (late, actions[1]))
    with pytest.raises(SnapshotError, match="not available"):
        research_view(unknown_at_cutoff, cutoff=datetime.fromisoformat("2024-07-03T17:15:00+00:00"))


def test_origin_is_required_and_production_reports_cannot_inherit_synthetic_labels(tmp_path):
    plan, bars, actions = load_fixture()
    data = plan.model_dump(mode="json")
    del data["origin"]
    with pytest.raises(ValidationError):
        SnapshotPlan.model_validate(data)
    with pytest.raises(ValidationError):
        SnapshotPlan.model_validate(dict(plan.model_dump(), origin="historical"))
    # Fabricated conversion tests the label mechanics, not actual provider data.
    historical = plan.model_copy(
        update={
            "origin": "historical",
            "revision_policy": "unknown",
            "limitations": ("unknown_revision_timing",),
        }
    )
    with pytest.raises(SnapshotQualityError):
        publish_snapshot(tmp_path, historical, bars, actions)
    converted = tuple(b.model_copy(update={"origin": "historical"}) for b in bars)
    saved = publish_snapshot(tmp_path, historical, converted, actions)
    report = inspect_snapshot(tmp_path, saved.dataset_id)
    assert report["origin"] == report["quality"]["origin"] == "historical"
    assert "synthetic_data" not in {f["code"] for f in report["quality"]["findings"]}
    assert "unknown_revision_timing" in report["manifest"]["plan"]["limitations"]


def specification_for(snapshot):
    data = json.loads((ROOT / "examples/contracts/experiment.json").read_text())
    data.update(
        universe=[i.model_dump(mode="json") for i in snapshot.manifest.plan.universe],
        datasets=[snapshot.reference().model_dump(mode="json")],
        language_model=None,
    )
    data["limitations"] = list(set(data["limitations"]) | set(snapshot.manifest.plan.limitations))
    data["strategy"]["numerical_model"] = None
    data["benchmark"]["weights"] = [{"symbol": "BBTEST", "weight": "1"}]
    return ExperimentSpecification.model_validate(data)


def test_experiment_binding_rejects_mismatched_feed_identity_and_insufficient_warmup(snapshot):
    spec = specification_for(snapshot)
    assert validate_snapshot_for_experiment(snapshot, spec) is snapshot
    for update in ({"warmup_sessions": 2}, {"end_session": date(2024, 7, 10)}):
        with pytest.raises(SnapshotError, match="cover"):
            validate_snapshot_for_experiment(snapshot, spec.model_copy(update=update))
    ref = spec.datasets[0]
    for update in ({"feed": "wrong_feed"}, {"dataset_id": "f" * 64}):
        with pytest.raises(SnapshotError, match="reference"):
            validate_snapshot_for_experiment(
                snapshot, spec.model_copy(update={"datasets": (ref.model_copy(update=update),)})
            )


def test_cli_publish_inspect_and_rejection_work_with_network_disabled(tmp_path):
    config = tmp_path / "offline.toml"
    config.write_text('[paths]\ndata="data"\nstate="state"\nartifacts="artifacts"\n')
    script = """
import socket, sys
def denied(*args, **kwargs):
    raise AssertionError('Network disabled for offline snapshot test')
class NoNetworkSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        denied()
socket.socket = NoNetworkSocket
socket.create_connection = denied
socket.getaddrinfo = denied
from buffetbot.cli import main
status = main(sys.argv[1:])
assert not any(k in sys.modules for k in ('lumibot', 'alpaca', 'sklearn'))
raise SystemExit(status)
"""
    env = dict(os.environ, BUFFETBOT_ALPACA_API_KEY="DUMMY_UNUSED_SNAPSHOT_KEY")

    def run(*args):
        return subprocess.run(
            [sys.executable, "-c", script, "datasets", *args, "--config", str(config)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    published = run("fixture")
    assert published.returncode == 0, published.stderr
    report = json.loads(published.stdout)
    inspected = run("inspect", report["dataset_id"])
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout) == report
    rejected = run("fixture", "--case", "missing_bar")
    assert rejected.returncode == 1, rejected.stderr
    assert json.loads(rejected.stdout)["origin"] == "synthetic"
    invalid = run("inspect", "../escape")
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["origin"] == "unverified"
    assert "DUMMY_UNUSED_SNAPSHOT_KEY" not in published.stdout + published.stderr


def test_dst_bars_keep_new_york_hours_while_utc_offsets_change(tmp_path):
    plan, bars, _ = load_fixture()
    plan = plan.model_copy(
        update={
            "coverage_start": date(2024, 11, 1),
            "coverage_end": date(2024, 11, 4),
            "first_execution_session": date(2024, 11, 4),
            "corporate_actions_source": "Synthetic DST fixture; no actions in the full range.",
        }
    )
    dst_bars = []
    for session, offset in [("2024-11-01", "-04:00"), ("2024-11-04", "-05:00")]:
        row = bars[0].model_dump(mode="json")
        row.update(
            session=session,
            interval_start=f"{session}T09:30:00{offset}",
            interval_end=f"{session}T16:00:00{offset}",
            available_at=f"{session}T16:15:00{offset}",
        )
        dst_bars.append(row)
    saved = publish_snapshot(tmp_path, plan, dst_bars, ())
    assert [b.interval_start.hour for b in saved.bars] == [13, 14]
    assert saved.manifest.quality.expected_closures == (date(2024, 11, 2), date(2024, 11, 3))


def test_accounting_fixture_preserves_qualified_source_prices_and_authored_final_ledger():
    _, bars, actions = load_fixture()
    with (ROOT / "qualification/fixtures/daily.csv").open() as stream:
        qualified = list(csv.DictReader(stream))
    for bar, expected in zip(bars, qualified, strict=True):
        assert str(bar.session) == expected["session"]
        assert all(
            getattr(bar, field) == Decimal(expected[field])
            for field in ("open", "high", "low", "close")
        )
    ledger = json.loads((ROOT / "src/buffetbot/fixtures/expected-ledger.json").read_text())
    qualified_final = json.loads(
        (ROOT / "qualification/fixtures/expected.json").read_text(), parse_float=Decimal
    )
    assert ledger["origin"] == "synthetic"
    assert Decimal(ledger["events"][-1]["cash"]) == qualified_final["cash"]
    assert actions[0].split_ratio == 2
    assert (
        str(actions[1].effective_session),
        str(actions[1].pay_date),
        actions[1].cash_amount_usd,
    ) == ("2024-07-05", "2024-07-09", Decimal(1))
