"""Durable-job and worker lifecycle behavior, including restart and process isolation."""

import hashlib
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from buffetbot.jobs import JobStore, JobStoreBusy, JobStoreError, UnknownJob
from buffetbot.jobs_models import ArtifactReference, JobRequest
from buffetbot.worker import Worker, WorkerAlreadyRunning, WorkerLock

ROOT = Path(__file__).resolve().parents[1]


def request(*, request_id=None, run_id=None, message="research", delay_ms=0, submitted_at=None):
    return JobRequest(
        schema_version=1,
        request_id=request_id or uuid4(),
        run_id=run_id or uuid4(),
        kind="research_probe",
        payload={"message": message, "delay_ms": delay_ms},
        submitted_at=submitted_at or datetime.now(UTC),
    )


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "state", tmp_path / "artifacts"


def test_submit_is_idempotent_but_request_id_cannot_change_meaning(paths):
    state, _ = paths
    store = JobStore(state)
    original = request()
    first = store.submit(original)
    assert store.submit(original) == first
    assert len(store.list()) == 1
    changed = original.model_copy(update={"payload": {"message": "other", "delay_ms": 0}})
    with pytest.raises(JobStoreError, match="different job"):
        store.submit(changed)
    assert store.get(original.request_id).state == "queued"
    assert [e["state"] for e in store.events(original.request_id)] == ["queued"]


def test_claims_are_transactional_and_ordered(paths):
    state, _ = paths
    start = datetime(2026, 9, 8, tzinfo=UTC)
    store = JobStore(state, clock=lambda: start)
    later = request(submitted_at=start + timedelta(seconds=1))
    earlier = request(submitted_at=start)
    store.submit(later)
    store.submit(earlier)
    first = store.claim("worker-one")
    second = store.claim("worker-two")
    assert {first.request.request_id, second.request.request_id} == {
        earlier.request_id,
        later.request_id,
    }
    assert first.state == "running" and first.progress == 1
    assert second.state == "running" and second.progress == 1
    assert store.claim("worker-three") is None


def test_busy_write_has_three_bounded_attempts(paths):
    state, _ = paths
    sleeps = []
    store = JobStore(state, sleep=sleeps.append)
    store.initialize()
    held = sqlite3.connect(store.database, isolation_level=None)
    held.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(JobStoreBusy):
            store.submit(request())
    finally:
        held.execute("ROLLBACK")
        held.close()
    assert sleeps == [0.05, 0.1]
    assert store.list() == ()


def test_cancel_before_and_during_run_has_honest_state(paths):
    state, _ = paths
    store = JobStore(state)
    queued = store.submit(request())
    assert store.cancel(queued.request.request_id).state == "cancelled"
    assert store.claim("worker") is None
    running = store.submit(request())
    store.claim("worker")
    requested = store.cancel(running.request.request_id)
    assert requested.state == "running" and requested.cancellation_requested
    diagnostic = ArtifactReference(
        relative_path=f"jobs/{running.request.request_id}/diagnostic.json",
        sha256="a" * 64,
        size_bytes=1,
    )
    final = store.finish(
        running.request.request_id, "interrupted", "cancelled_or_shutdown", "stopped", diagnostic
    )
    assert final.state == "interrupted" and final.artifact == diagnostic
    assert store.cancel(running.request.request_id) == final


def test_running_jobs_are_interrupted_on_restart_and_never_reexecuted(paths):
    state, _ = paths
    store = JobStore(state)
    active = store.submit(request())
    store.claim("dead-worker")
    recovered = JobStore(state).recover()
    assert recovered == (str(active.request.request_id),)
    record = store.get(active.request.request_id)
    assert record.state == "interrupted" and record.error_code == "worker_restarted"
    assert JobStore(state).claim("new-worker") is None
    assert "not re-executed" in record.detail


def test_unknown_job_and_invalid_transitions_fail_explicitly(paths):
    state, _ = paths
    store = JobStore(state)
    with pytest.raises(UnknownJob):
        store.get(uuid4())
    queued = store.submit(request())
    artifact = ArtifactReference(
        relative_path=f"jobs/{queued.request.request_id}/result.json", sha256="b" * 64, size_bytes=1
    )
    with pytest.raises(JobStoreError, match="active"):
        store.complete(queued.request.request_id, artifact)
    with pytest.raises(JobStoreError):
        store.finish(queued.request.request_id, "succeeded", "wrong", "wrong")


def test_schema_migration_creates_backup_and_rejects_newer_or_inconsistent_schema(paths):
    state, _ = paths
    state.mkdir()
    database = state / "jobs.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE legacy(value INTEGER)")
    connection.commit()
    connection.close()
    JobStore(state).initialize()
    backup = state / "jobs.pre-v0-to-v1.sqlite3"
    assert backup.exists()
    with sqlite3.connect(backup) as restored:
        assert restored.execute("SELECT name FROM sqlite_master WHERE name='legacy'").fetchone()
    newer = paths[0].parent / "newer"
    newer.mkdir()
    with sqlite3.connect(newer / "jobs.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(JobStoreError, match="newer"):
        JobStore(newer).initialize()
    inconsistent = paths[0].parent / "inconsistent"
    inconsistent.mkdir()
    with sqlite3.connect(inconsistent / "jobs.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(JobStoreError, match="inconsistent"):
        JobStore(inconsistent).initialize()


def test_failed_migration_is_atomic(paths, monkeypatch):
    state, _ = paths
    state.mkdir()
    database = state / "jobs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy(value INTEGER)")
    import buffetbot.jobs as jobs

    monkeypatch.setitem(
        jobs.MIGRATIONS,
        1,
        "CREATE TABLE jobs(request_id TEXT PRIMARY KEY); INSERT INTO missing VALUES(1);",
    )
    with pytest.raises(JobStoreError):
        JobStore(state).initialize()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()


def test_worker_publishes_verified_result_before_success_and_child_has_no_secrets(
    paths, monkeypatch
):
    state, artifacts = paths
    monkeypatch.setenv("BUFFETBOT_ALPACA_API_KEY", "DUMMY_JOB_KEY")
    monkeypatch.setenv("BUFFETBOT_ALPACA_API_SECRET", "DUMMY_JOB_SECRET")
    submitted = JobStore(state).submit(request(message="hello", delay_ms=10))
    result = Worker(state, artifacts).run_once()
    assert result["status"] == "succeeded"
    record = JobStore(state).get(submitted.request.request_id)
    artifact = artifacts / record.artifact.relative_path
    assert record.state == "succeeded" and artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == record.artifact.sha256
    contents = json.loads(artifact.read_bytes())
    assert contents["message"] == "hello"
    assert contents["cpu_limit_seconds"] == 30
    assert "BUFFETBOT_ALPACA_API_KEY" not in contents["environment_keys"]
    assert "BUFFETBOT_ALPACA_API_SECRET" not in contents["environment_keys"]
    assert [e["state"] for e in JobStore(state).events(submitted.request.request_id)] == [
        "queued",
        "running",
        "succeeded",
    ]


def test_result_publish_failure_leaves_diagnostic_and_never_marks_success(paths, monkeypatch):
    state, artifacts = paths
    submitted = JobStore(state).submit(request())
    worker = Worker(state, artifacts)
    real = worker._publish_result

    def failed(*args):
        real(*args)
        raise OSError("simulated artifact failure")

    monkeypatch.setattr(worker, "_publish_result", failed)
    outcome = worker.run_once()
    record = JobStore(state).get(submitted.request.request_id)
    assert outcome["status"] == record.state == "failed"
    assert record.error_code == "artifact_publish_failed"
    assert record.artifact.relative_path.endswith("diagnostic.json")
    assert (artifacts / record.artifact.relative_path).is_file()
    assert (
        not (artifacts / "jobs" / str(submitted.request.request_id) / "result.json").is_file()
        or record.state != "succeeded"
    )


def test_timeout_and_cancellation_terminate_child_and_publish_diagnostics(paths, monkeypatch):
    import buffetbot.worker as workers

    state, artifacts = paths
    monkeypatch.setattr(workers, "CHILD_TIMEOUT_SECONDS", 0.15)
    timed = JobStore(state).submit(request(delay_ms=1_000))
    outcome = Worker(state, artifacts).run_once()
    record = JobStore(state).get(timed.request.request_id)
    assert outcome["status"] == record.state == "interrupted"
    assert record.error_code == "child_timeout"
    assert (artifacts / record.artifact.relative_path).is_file()

    active = JobStore(state).submit(request(delay_ms=1_000))
    worker = Worker(state, artifacts)
    original_sleep = worker._sleep
    calls = [0]

    def cancel_after_poll(seconds):
        calls[0] += 1
        if calls[0] == 1:
            JobStore(state).cancel(active.request.request_id)
        original_sleep(seconds)

    worker._sleep = cancel_after_poll
    worker.run_once()
    cancelled = JobStore(state).get(active.request.request_id)
    assert cancelled.state == "interrupted" and cancelled.error_code == "cancelled_or_shutdown"


def lock_holder(path, ready):
    with WorkerLock(Path(path)):
        ready.send(os.getpid())
        time.sleep(30)


def test_worker_lock_excludes_second_process_and_releases_after_owner_death(paths):
    state, _ = paths
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=lock_holder, args=(str(state), sender))
    process.start()
    sender.close()
    assert receiver.poll(10)
    receiver.recv()
    with pytest.raises(WorkerAlreadyRunning):
        WorkerLock(state).acquire()
    process.kill()
    process.join(timeout=10)
    with WorkerLock(state):
        pass


def test_worker_child_does_not_inherit_lock_after_parent_worker_dies(paths):
    state, artifacts = paths
    submitted = JobStore(state).submit(request(delay_ms=5_000))
    code = """
from pathlib import Path
from buffetbot.worker import Worker
Worker(Path(__import__('sys').argv[1]), Path(__import__('sys').argv[2])).run_once()
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(state), str(artifacts)])
    lock = state / "worker.lock"
    for _ in range(100):
        if lock.exists() and JobStore(state).get(submitted.request.request_id).state == "running":
            break
        time.sleep(0.05)
    else:
        process.kill()
        pytest.fail("Worker did not claim the test job")
    process.kill()
    process.wait(timeout=10)
    # Spawned child cannot retain the parent's flock; a new worker first recovers the orphan.
    outcome = Worker(state, artifacts).run_once()
    assert outcome["recovered"] == [str(submitted.request.request_id)]
    assert JobStore(state).get(submitted.request.request_id).state == "interrupted"


def test_shutdown_stops_new_claims_until_explicit_resume(paths):
    state, artifacts = paths
    store = JobStore(state)
    queued = store.submit(request())
    store.request_shutdown(True)
    assert Worker(state, artifacts).run_once()["status"] == "shutting_down"
    assert store.get(queued.request.request_id).state == "queued"
    store.request_shutdown(False)
    assert Worker(state, artifacts).run_once()["status"] == "succeeded"


def test_cli_jobs_and_worker_commands_are_json_network_free_and_do_not_load_secrets(tmp_path):
    config = tmp_path / "offline.toml"
    config.write_text('[paths]\nstate="state"\ndata="data"\nartifacts="artifacts"\n')
    job = request(message="cli")
    request_path = tmp_path / "request.json"
    request_path.write_text(job.model_dump_json())
    code = """
import socket, sys
class NoNetwork(socket.socket):
    def __init__(self, *a, **k): raise AssertionError('network disabled')
socket.socket = NoNetwork
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network disabled'))
socket.getaddrinfo = socket.create_connection
from buffetbot.cli import main
raise SystemExit(main(sys.argv[1:]))
"""
    environment = dict(
        os.environ,
        BUFFETBOT_ALPACA_API_KEY="DUMMY_JOB_KEY",
        BUFFETBOT_ALPACA_API_SECRET="DUMMY_JOB_SECRET",
    )

    def run(*args):
        return subprocess.run(
            [sys.executable, "-c", code, *args, "--config", str(config)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
        )

    submitted = run("jobs", "submit", "--request", str(request_path))
    assert submitted.returncode == 0 and "DUMMY_JOB_" not in submitted.stdout + submitted.stderr
    duplicate = run("jobs", "submit", "--request", str(request_path))
    assert duplicate.returncode == 0 and len(json.loads(run("jobs", "list").stdout)["jobs"]) == 1
    worked = run("worker", "once")
    assert worked.returncode == 0 and json.loads(worked.stdout)["status"] == "succeeded"
    shown = run("jobs", "show", str(job.request_id))
    assert json.loads(shown.stdout)["job"]["state"] == "succeeded"
    shutdown = run("worker", "shutdown")
    assert json.loads(shutdown.stdout)["status"] == "shutdown_requested"
    assert run("worker", "resume").returncode == 0
    bad = run("jobs", "show", str(uuid4()))
    assert bad.returncode == 2 and json.loads(bad.stdout)["status"] == "not_found"
