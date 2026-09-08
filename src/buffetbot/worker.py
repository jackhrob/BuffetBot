"""Single-owner local worker for bounded, secret-free research child processes."""

import fcntl
import hashlib
import json
import multiprocessing
import os
import resource
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from buffetbot.jobs import JobStore, JobStoreError
from buffetbot.jobs_models import ArtifactReference, JobRecord

MAX_CHILDREN = 1
CHILD_TIMEOUT_SECONDS = 35
CHILD_CPU_SECONDS = 30
POLL_SECONDS = 0.1
SAFE_ENVIRONMENT = ("LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TERM", "TZ")


class WorkerError(ValueError):
    pass


class WorkerAlreadyRunning(WorkerError):
    pass


@dataclass
class WorkerLock:
    state_dir: Path
    handle: object | None = None

    @property
    def path(self):
        return self.state_dir / "worker.lock"

    def acquire(self):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("a+", encoding="utf-8")
            os.set_inheritable(self.handle.fileno(), False)
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(
                json.dumps({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}) + "\n"
            )
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except (BlockingIOError, OSError):
            self.release()
            raise WorkerAlreadyRunning("Another worker owns this state directory.") from None

    def release(self):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def _child_entry(connection, payload, inherited_environment):
    """The only child handler available in BB-006; it receives no storage/broker authority."""
    try:
        os.environ.clear()
        os.environ.update(inherited_environment)
        resource.setrlimit(resource.RLIMIT_CPU, (CHILD_CPU_SECONDS, CHILD_CPU_SECONDS + 1))
        delay = payload["delay_ms"] / 1000
        time.sleep(delay)
        result = json.dumps(
            {
                "schema_version": 1,
                "kind": "research_probe",
                "message": payload["message"],
                "delay_ms": payload["delay_ms"],
                "cpu_limit_seconds": CHILD_CPU_SECONDS,
                "environment_keys": sorted(os.environ),
                "completed_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        connection.send(("ok", result))
    except BaseException:
        connection.send(("failed", b"Child research probe failed."))
    finally:
        connection.close()


class Worker:
    def __init__(
        self,
        state_dir: Path,
        artifacts_dir: Path,
        *,
        clock=lambda: datetime.now(UTC),
        sleep=time.sleep,
    ):
        self.store = JobStore(state_dir, clock=clock, sleep=sleep)
        self.state_dir, self.artifacts_dir = Path(state_dir), Path(artifacts_dir)
        self._clock, self._sleep = clock, sleep
        self.worker_id = f"worker-{uuid4().hex}"
        self._stop = False

    def _allowed_environment(self):
        return {key: os.environ[key] for key in SAFE_ENVIRONMENT if key in os.environ}

    def status(self):
        self.store.initialize()
        stored_counts = self.store.state_counts()
        counts = {
            state: stored_counts.get(state, 0)
            for state in ("queued", "running", "succeeded", "failed", "interrupted", "cancelled")
        }
        return {
            "schema_version": 1,
            "worker_id": self.worker_id,
            "shutdown_requested": self.store.shutdown_requested(),
            "max_research_children": MAX_CHILDREN,
            "research_child_timeout_seconds": CHILD_TIMEOUT_SECONDS,
            "research_child_cpu_limit_seconds": CHILD_CPU_SECONDS,
            "jobs": counts,
        }

    def run_once(self):
        self.store.initialize()
        with WorkerLock(self.state_dir):
            recovered = self.store.recover()
            if self.store.shutdown_requested():
                return {"status": "shutting_down", "recovered": list(recovered), "job": None}
            job = self.store.claim(self.worker_id)
            if job is None:
                return {"status": "idle", "recovered": list(recovered), "job": None}
            final = self._execute(job)
            return {
                "status": final.state,
                "recovered": list(recovered),
                "job": final.model_dump(mode="json"),
            }

    def serve(self, *, poll_seconds=0.25):
        if not 0.05 <= poll_seconds <= 5:
            raise WorkerError("Worker polling interval must be between 0.05 and 5 seconds.")
        self.store.initialize()
        with WorkerLock(self.state_dir):
            recovered = self.store.recover()
            completed = []
            previous_handlers = self._install_signal_handlers()
            try:
                while not self._stop and not self.store.shutdown_requested():
                    job = self.store.claim(self.worker_id)
                    if job is None:
                        self._sleep(poll_seconds)
                        continue
                    completed.append(self._execute(job).request.request_id)
            finally:
                self._restore_signal_handlers(previous_handlers)
            return {
                "status": "stopped",
                "recovered": list(recovered),
                "completed": [str(x) for x in completed],
            }

    def _install_signal_handlers(self):
        def stop(*_):
            self._stop = True

        return {
            signal.SIGINT: signal.signal(signal.SIGINT, stop),
            signal.SIGTERM: signal.signal(signal.SIGTERM, stop),
        }

    def _restore_signal_handlers(self, handlers):
        for signum, previous in handlers.items():
            signal.signal(signum, previous)

    def _execute(self, job: JobRecord):
        parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
        process = multiprocessing.get_context("spawn").Process(
            target=_child_entry,
            args=(child, job.request.payload.model_dump(), self._allowed_environment()),
            daemon=False,
        )
        process.start()
        child.close()
        started = time.monotonic()
        result = None
        state, code, detail = (
            "failed",
            "child_failed",
            "Research child ended without a valid result.",
        )
        try:
            while process.is_alive():
                if (
                    self._stop
                    or self.store.shutdown_requested()
                    or self.store.get(job.request.request_id).cancellation_requested
                ):
                    state, code, detail = (
                        "interrupted",
                        "cancelled_or_shutdown",
                        "Research child stopped before completion.",
                    )
                    process.terminate()
                    break
                if time.monotonic() - started > CHILD_TIMEOUT_SECONDS:
                    state, code, detail = (
                        "interrupted",
                        "child_timeout",
                        "Research child exceeded its 35-second bound.",
                    )
                    process.terminate()
                    break
                self._sleep(POLL_SECONDS)
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if state == "failed" and parent.poll():
                status, payload = parent.recv()
                if status == "ok":
                    result = payload
                else:
                    detail = "Research child reported failure."
            if result is not None:
                try:
                    artifact = self._publish_result(job, result)
                    return self.store.complete(job.request.request_id, artifact)
                except (OSError, WorkerError, JobStoreError):
                    code, detail = (
                        "artifact_publish_failed",
                        "Research result could not be published safely.",
                    )
            artifact = self._publish_diagnostic(job, code, detail)
            return self.store.finish(job.request.request_id, state, code, detail, artifact)
        finally:
            parent.close()
            if process.is_alive():
                process.kill()
                process.join(timeout=2)

    def _job_directory(self, job):
        directory = self.artifacts_dir / "jobs" / str(job.request.request_id)
        if directory.is_symlink():
            raise WorkerError("Artifact directory must not be a symlink.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory

    def _atomic_artifact(self, job, name, contents):
        directory = self._job_directory(job)
        final = directory / name
        temporary = directory / f".{name}.staging-{uuid4().hex}"
        try:
            with temporary.open("xb") as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            if final.exists():
                if final.is_symlink() or final.read_bytes() != contents:
                    raise WorkerError("Job artifact already exists with different contents.")
            else:
                os.replace(temporary, final)
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            verified = final.read_bytes()
            if verified != contents:
                raise WorkerError("Published job artifact could not be verified.")
            return ArtifactReference(
                relative_path=f"jobs/{job.request.request_id}/{name}",
                sha256=hashlib.sha256(verified).hexdigest(),
                size_bytes=len(verified),
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _publish_result(self, job, contents):
        return self._atomic_artifact(job, "result.json", contents)

    def _publish_diagnostic(self, job, code, detail):
        contents = json.dumps(
            {
                "schema_version": 1,
                "request_id": str(job.request.request_id),
                "code": code,
                "detail": detail,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self._atomic_artifact(job, "diagnostic.json", contents)
