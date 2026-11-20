import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import BoxError


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "jobs.sqlite"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    config TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    progress REAL NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    interruptions INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_fingerprint ON jobs(fingerprint)
                    WHERE status IN ('queued','running','succeeded');
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, job_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise BoxError("job_not_found", "Trabalho inexistente.", 3)
        return dict(row)

    def list(self, limit: int = 50, status: str | None = None,
             since: float | None = None, until: float | None = None) -> list:
        """Mais recentes primeiro. `since` é inclusivo e `until` exclusivo (epoch, sobre created_at)."""
        conditions, values = [], []
        if status is not None:
            conditions.append("status=?")
            values.append(status)
        if since is not None:
            conditions.append("created_at>=?")
            values.append(since)
        if until is not None:
            conditions.append("created_at<?")
            values.append(until)
        where = ("WHERE " + " AND ".join(conditions) + " ") if conditions else ""
        with self.connection() as db:
            rows = db.execute(f"SELECT * FROM jobs {where}ORDER BY created_at DESC, id DESC LIMIT ?",
                              (*values, max(1, int(limit)))).fetchall()
        return [dict(row) for row in rows]

    def enqueue(self, job_id, fingerprint, input_hash, input_path, source_name, config, is_valid=None):
        """Enfileira ou reutiliza o job equivalente.

        `is_valid(job)` verifica a saída de um job `succeeded` antes da reutilização: False invalida
        o job antigo (`output_lost`) e cria um novo; None (erro transitório de E/S) mantém o antigo.
        """
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE fingerprint=? AND status!='failed'", (fingerprint,)
            ).fetchone()
            if row:
                if row["status"] != "succeeded" or is_valid is None or is_valid(dict(row)) is not False:
                    return row["id"], True
                db.execute(
                    """UPDATE jobs SET status='failed', error_code='output_lost', error_message=?
                    WHERE id=?""",
                    ("Saída ausente ou alterada; a mídia foi reenviada e reprocessada.", row["id"]),
                )
            db.execute(
                """INSERT INTO jobs
                (id,fingerprint,input_hash,input_path,source_name,config,status,created_at)
                VALUES (?,?,?,?,?,?,'queued',?)""",
                (job_id, fingerprint, input_hash, input_path, source_name,
                 json.dumps(config, sort_keys=True), time.time()),
            )
        return job_id, False

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            db.execute(
                """UPDATE jobs SET status='running', attempts=attempts+1,
                started_at=?, finished_at=NULL, progress=0, error_code=NULL, error_message=NULL
                WHERE id=?""", (time.time(), row["id"])
            )
        return self.get(row["id"])

    def running(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs WHERE status='running'")]

    def recover(self, job_id):
        with self.connection() as db:
            db.execute(
                """UPDATE jobs SET
                status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
                error_code=CASE WHEN attempts>=3 THEN 'interrupted_limit' ELSE 'interrupted' END,
                error_message='Worker interrompido durante o processamento.',
                interruptions=interruptions+1 WHERE id=? AND status='running'""", (job_id,)
            )

    def progress(self, job_id, seconds):
        with self.connection() as db:
            db.execute("UPDATE jobs SET progress=? WHERE id=?", (seconds, job_id))

    def finish(self, job_id, error: BoxError | None = None):
        with self.connection() as db:
            db.execute(
                """UPDATE jobs SET status=?,finished_at=?,error_code=?,error_message=? WHERE id=?""",
                ("failed" if error else "succeeded", time.time(),
                 error.code if error else None, str(error) if error else None, job_id),
            )
