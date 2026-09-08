"""Small SQLite job store with explicit migrations and bounded write contention."""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from buffetbot.jobs_models import ArtifactReference, JobRecord, JobRequest

SCHEMA_VERSION = 1
BUSY_ATTEMPTS = 3
BUSY_DELAYS = (0.05, 0.1)


class JobStoreError(ValueError):
    """Recoverable durable-state failure without raw database or filesystem details."""


class JobStoreBusy(JobStoreError):
    pass


class UnknownJob(JobStoreError):
    pass


def now():
    return datetime.now(UTC)


def utc_text(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


MIGRATIONS = {
    1: """
        CREATE TABLE jobs (
            request_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind = 'research_probe'),
            payload_json TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN
                ('queued','running','succeeded','failed','interrupted','cancelled')),
            progress INTEGER NOT NULL CHECK(progress BETWEEN 0 AND 100),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            worker_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_code TEXT,
            detail TEXT,
            artifact_path TEXT,
            artifact_sha256 TEXT,
            artifact_size_bytes INTEGER,
            cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK(
                cancellation_requested IN (0,1)),
            CHECK((artifact_path IS NULL AND artifact_sha256 IS NULL AND
                artifact_size_bytes IS NULL) OR (artifact_path IS NOT NULL AND
                artifact_sha256 IS NOT NULL AND artifact_size_bytes > 0))
        );
        CREATE INDEX jobs_claimable ON jobs(state, cancellation_requested, created_at);
        CREATE TABLE job_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL REFERENCES jobs(request_id),
            at TEXT NOT NULL,
            state TEXT NOT NULL,
            detail TEXT NOT NULL
        );
        CREATE TABLE worker_control (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            shutdown_requested INTEGER NOT NULL CHECK(shutdown_requested IN (0,1)),
            updated_at TEXT NOT NULL
        );
        INSERT INTO worker_control(singleton, shutdown_requested, updated_at)
        VALUES(1, 0, '1970-01-01T00:00:00.000000Z');
    """,
}


class JobStore:
    def __init__(self, state_dir: Path, *, clock=now, sleep=time.sleep):
        self.state_dir = Path(state_dir)
        self.database = self.state_dir / "jobs.sqlite3"
        self._clock, self._sleep = clock, sleep

    def initialize(self):
        try:
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.state_dir.is_symlink() or not self.state_dir.is_dir():
                raise JobStoreError("State directory must be a real local directory.")
            existed = self.database.exists()
            with self._connection() as connection:
                current = self._schema_version(connection)
                if current > SCHEMA_VERSION:
                    raise JobStoreError("State database uses a newer unsupported schema version.")
                if current < SCHEMA_VERSION and existed:
                    self._backup(connection, current)
                for version in range(current + 1, SCHEMA_VERSION + 1):
                    # `executescript` runs each statement in autocommit mode
                    # unless the script owns its transaction.  Keep a failed
                    # migration from exposing a partially-created schema.
                    connection.executescript(
                        f"BEGIN IMMEDIATE;\n{MIGRATIONS[version]}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;"
                    )
        except JobStoreError:
            raise
        except (OSError, sqlite3.DatabaseError):
            raise JobStoreError(
                "Cannot initialize durable job state; check state storage."
            ) from None

    def _backup(self, connection, version):
        path = self.state_dir / f"jobs.pre-v{version}-to-v{SCHEMA_VERSION}.sqlite3"
        if path.exists():
            raise JobStoreError(
                "Migration backup path already exists; inspect state before retrying."
            )
        destination = sqlite3.connect(path)
        try:
            connection.backup(destination)
        finally:
            destination.close()
        os.chmod(path, 0o600)

    def _schema_version(self, connection):
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        # A future database must be rejected as such even if it does not happen
        # to contain this version's tables.  Calling it an inconsistent marker
        # would encourage an operator to repair a database we cannot understand.
        if version > SCHEMA_VERSION:
            return version
        if not tables and version:
            raise JobStoreError("State database schema marker is inconsistent.")
        return version

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database, timeout=0, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 0")
            yield connection
        finally:
            connection.close()

    def _write(self, operation):
        for attempt in range(BUSY_ATTEMPTS):
            try:
                with self._connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    value = operation(connection)
                    connection.execute("COMMIT")
                    return value
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower() and "busy" not in str(error).lower():
                    raise JobStoreError("Durable job state could not be updated.") from None
                if attempt == BUSY_ATTEMPTS - 1:
                    raise JobStoreBusy(
                        "Job state is busy after three short retries; try again."
                    ) from None
                self._sleep(BUSY_DELAYS[attempt])
            except JobStoreError:
                raise
            except (OSError, sqlite3.DatabaseError):
                raise JobStoreError("Durable job state could not be updated.") from None
        raise AssertionError("Write retry loop must return or raise")

    def submit(self, request: JobRequest):
        self.initialize()
        request = JobRequest.model_validate(request)
        created = utc_text(self._clock())

        def operation(connection):
            existing = connection.execute(
                "SELECT * FROM jobs WHERE request_id = ?", (str(request.request_id),)
            ).fetchone()
            if existing is not None:
                if (
                    existing["run_id"] != str(request.run_id)
                    or existing["kind"] != request.kind
                    or existing["payload_json"] != request.payload.model_dump_json()
                ):
                    raise JobStoreError("Request ID already belongs to a different job request.")
                return self._record(existing)
            connection.execute(
                """INSERT INTO jobs(
                       request_id, run_id, kind, payload_json, submitted_at, state, progress,
                       created_at, updated_at, cancellation_requested
                   ) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, 0)""",
                (
                    str(request.request_id),
                    str(request.run_id),
                    request.kind,
                    request.payload.model_dump_json(),
                    utc_text(request.submitted_at),
                    created,
                    created,
                ),
            )
            self._event(connection, request.request_id, created, "queued", "submitted")
            return self._get(connection, request.request_id)

        return self._write(operation)

    def _event(self, connection, request_id, at, state, detail):
        connection.execute(
            "INSERT INTO job_events(request_id, at, state, detail) VALUES (?, ?, ?, ?)",
            (str(request_id), at, state, detail),
        )

    def _get(self, connection, request_id):
        row = connection.execute(
            "SELECT * FROM jobs WHERE request_id = ?", (str(request_id),)
        ).fetchone()
        if row is None:
            raise UnknownJob("Job request ID was not found.")
        return self._record(row)

    def get(self, request_id):
        self.initialize()
        try:
            with self._connection() as connection:
                return self._get(connection, request_id)
        except JobStoreError:
            raise
        except (OSError, sqlite3.DatabaseError):
            raise JobStoreError("Cannot read durable job state.") from None

    def list(self, *, limit=100):
        self.initialize()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise JobStoreError("Job list limit must be an integer from 1 through 100.")
        try:
            with self._connection() as connection:
                return tuple(
                    self._record(row)
                    for row in connection.execute(
                        "SELECT * FROM jobs ORDER BY created_at DESC, request_id DESC LIMIT ?",
                        (limit,),
                    )
                )
        except (OSError, sqlite3.DatabaseError):
            raise JobStoreError("Cannot read durable job state.") from None

    def state_counts(self):
        """Return exact state totals without loading a bounded recent-job view."""
        self.initialize()
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT state, COUNT(*) AS total FROM jobs GROUP BY state"
                )
                return {row["state"]: row["total"] for row in rows}
        except (OSError, sqlite3.DatabaseError):
            raise JobStoreError("Cannot read durable job state.") from None

    def claim(self, worker_id):
        self.initialize()
        claimed_at = utc_text(self._clock())

        def operation(connection):
            row = connection.execute(
                """SELECT * FROM jobs WHERE state='queued' AND cancellation_requested=0
                   ORDER BY created_at, request_id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                """UPDATE jobs SET state='running', progress=1, worker_id=?, started_at=?,
                   updated_at=?
                   WHERE request_id=? AND state='queued' AND cancellation_requested=0""",
                (worker_id, claimed_at, claimed_at, row["request_id"]),
            ).rowcount
            if changed != 1:
                raise JobStoreBusy("A worker claimed this job first; try again.")
            self._event(connection, row["request_id"], claimed_at, "running", "claimed")
            return self._get(connection, row["request_id"])

        return self._write(operation)

    def cancel(self, request_id):
        self.initialize()
        changed_at = utc_text(self._clock())

        def operation(connection):
            record = self._get(connection, request_id)
            if record.state in ("succeeded", "failed", "interrupted", "cancelled"):
                return record
            if record.state == "queued":
                connection.execute(
                    """UPDATE jobs SET state='cancelled', progress=100, finished_at=?,
                       updated_at=? WHERE request_id=?""",
                    (changed_at, changed_at, str(request_id)),
                )
                self._event(
                    connection, request_id, changed_at, "cancelled", "cancelled before start"
                )
            else:
                connection.execute(
                    "UPDATE jobs SET cancellation_requested=1, updated_at=? WHERE request_id=?",
                    (changed_at, str(request_id)),
                )
                self._event(connection, request_id, changed_at, "running", "cancellation requested")
            return self._get(connection, request_id)

        return self._write(operation)

    def complete(self, request_id, artifact: ArtifactReference):
        self.initialize()
        artifact = ArtifactReference.model_validate(artifact)
        changed_at = utc_text(self._clock())

        def operation(connection):
            record = self._get(connection, request_id)
            if record.state != "running" or record.cancellation_requested:
                raise JobStoreError("Only an active, uncancelled job can be marked successful.")
            connection.execute(
                """UPDATE jobs SET state='succeeded', progress=100, finished_at=?, updated_at=?,
                   artifact_path=?, artifact_sha256=?, artifact_size_bytes=?, detail='completed'
                   WHERE request_id=?""",
                (
                    changed_at,
                    changed_at,
                    artifact.relative_path,
                    artifact.sha256,
                    artifact.size_bytes,
                    str(request_id),
                ),
            )
            self._event(
                connection, request_id, changed_at, "succeeded", "artifact verified and published"
            )
            return self._get(connection, request_id)

        return self._write(operation)

    def finish(self, request_id, state, code, detail, artifact=None):
        self.initialize()
        if state not in ("failed", "interrupted", "cancelled"):
            raise JobStoreError("Only failed, interrupted or cancelled states can finish a job.")
        changed_at = utc_text(self._clock())

        def operation(connection):
            record = self._get(connection, request_id)
            if record.state != "running":
                return record
            connection.execute(
                """UPDATE jobs SET state=?, progress=100, finished_at=?, updated_at=?,
                   error_code=?, detail=?,
                   artifact_path=?, artifact_sha256=?, artifact_size_bytes=? WHERE request_id=?""",
                (
                    state,
                    changed_at,
                    changed_at,
                    code,
                    detail,
                    artifact.relative_path if artifact else None,
                    artifact.sha256 if artifact else None,
                    artifact.size_bytes if artifact else None,
                    str(request_id),
                ),
            )
            self._event(connection, request_id, changed_at, state, detail)
            return self._get(connection, request_id)

        return self._write(operation)

    def recover(self):
        self.initialize()
        changed_at = utc_text(self._clock())

        def operation(connection):
            rows = tuple(connection.execute("SELECT request_id FROM jobs WHERE state='running'"))
            for row in rows:
                connection.execute(
                    """UPDATE jobs SET state='interrupted', progress=100, finished_at=?,
                       updated_at=?, error_code='worker_restarted',
                       detail='Worker restarted; research job was not re-executed.'
                       WHERE request_id=?""",
                    (changed_at, changed_at, row["request_id"]),
                )
                self._event(
                    connection,
                    row["request_id"],
                    changed_at,
                    "interrupted",
                    "worker restart recovery",
                )
            return tuple(row["request_id"] for row in rows)

        return self._write(operation)

    def request_shutdown(self, requested):
        self.initialize()
        changed_at = utc_text(self._clock())

        def operation(connection):
            connection.execute(
                "UPDATE worker_control SET shutdown_requested=?, updated_at=? WHERE singleton=1",
                (int(requested), changed_at),
            )
            return bool(requested)

        return self._write(operation)

    def shutdown_requested(self):
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT shutdown_requested FROM worker_control WHERE singleton=1"
            ).fetchone()
            return bool(row[0])

    def events(self, request_id):
        self.get(request_id)
        with self._connection() as connection:
            return tuple(
                dict(
                    sequence=row["sequence"], at=row["at"], state=row["state"], detail=row["detail"]
                )
                for row in connection.execute(
                    "SELECT * FROM job_events WHERE request_id=? ORDER BY sequence",
                    (str(request_id),),
                )
            )

    def _record(self, row):
        try:
            artifact = None
            if row["artifact_path"] is not None:
                artifact = ArtifactReference(
                    relative_path=row["artifact_path"],
                    sha256=row["artifact_sha256"],
                    size_bytes=row["artifact_size_bytes"],
                )
            request = JobRequest(
                schema_version=1,
                request_id=row["request_id"],
                run_id=row["run_id"],
                kind=row["kind"],
                payload=json.loads(row["payload_json"]),
                submitted_at=row["submitted_at"],
            )
            return JobRecord(
                schema_version=1,
                request=request,
                state=row["state"],
                progress=row["progress"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                worker_id=row["worker_id"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                error_code=row["error_code"],
                detail=row["detail"],
                artifact=artifact,
                cancellation_requested=bool(row["cancellation_requested"]),
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
            raise JobStoreError(
                "Stored job state is invalid or unsupported; restore from backup."
            ) from None
