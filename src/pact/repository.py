from __future__ import annotations

import sqlite3
import threading
from datetime import datetime

from pact.models import (
    CoachingMessage,
    LinkAccount,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ReasoningTask,
    Verdict,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        # One shared sqlite3 connection (check_same_thread=False) is written from
        # FastAPI's threadpool. SQLite serializes statements but interleaved
        # execute+commit from two threads can still corrupt/race; a process-local
        # lock makes each write method atomic. Reads stay lock-free.
        self._write_lock = threading.Lock()

    @classmethod
    def connect(cls, path: str) -> "Repository":
        conn = sqlite3.connect(path, check_same_thread=False)
        return cls(conn)

    def init_schema(self) -> None:
        with self._write_lock:
            self._init_schema_locked()

    def _init_schema_locked(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pacts (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pacts_owner ON pacts(owner);
            CREATE INDEX IF NOT EXISTS idx_pacts_status ON pacts(status);
            CREATE INDEX IF NOT EXISTS idx_pacts_deadline ON pacts(deadline_at);

            CREATE TABLE IF NOT EXISTS proofs (
                id TEXT PRIMARY KEY,
                pact_id TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proofs_pact ON proofs(pact_id);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                pact_id TEXT,
                status TEXT NOT NULL,
                required_capability TEXT,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_capability ON tasks(required_capability);

            CREATE TABLE IF NOT EXISTS verdicts (
                pact_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profiles (
                owner TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS link_accounts (
                owner TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS coaching_messages (
                id TEXT PRIMARY KEY,
                pact_id TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                delivered_at TEXT,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_coaching_pact ON coaching_messages(pact_id);
            CREATE INDEX IF NOT EXISTS idx_coaching_sent ON coaching_messages(sent_at);
            CREATE INDEX IF NOT EXISTS idx_coaching_delivered ON coaching_messages(delivered_at);
            """
        )
        # Migration: add delivered_at column to coaching_messages if it was created
        # without it (pre-Day-3 schema). ALTER TABLE ADD COLUMN is a no-op-safe
        # SQLite operation when the column already exists on modern versions, but
        # older SQLite raises OperationalError, so we guard explicitly.
        existing_cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(coaching_messages)")
        }
        if "delivered_at" not in existing_cols:
            self.conn.execute(
                "ALTER TABLE coaching_messages ADD COLUMN delivered_at TEXT"
            )
        self.conn.commit()

    # --- Pact ---

    def save_pact(self, pact: Pact) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO pacts (id, owner, status, deadline_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    pact.id,
                    pact.owner,
                    pact.status.value,
                    pact.deadline_at.isoformat(),
                    pact.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_pact(self, pact_id: str) -> Pact | None:
        row = self.conn.execute(
            "SELECT data FROM pacts WHERE id = ?", (pact_id,)
        ).fetchone()
        if row is None:
            return None
        return Pact.model_validate_json(row["data"])

    def update_pact(self, pact: Pact) -> None:
        self.save_pact(pact)

    def list_pacts(self, owner: str | None = None) -> list[Pact]:
        if owner is None:
            rows = self.conn.execute("SELECT data FROM pacts").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM pacts WHERE owner = ?", (owner,)
            ).fetchall()
        return [Pact.model_validate_json(r["data"]) for r in rows]

    def due_active_pacts(self, now: datetime) -> list[Pact]:
        rows = self.conn.execute(
            "SELECT data FROM pacts WHERE status = ? AND deadline_at <= ?",
            (PactStatus.active.value, now.isoformat()),
        ).fetchall()
        return [Pact.model_validate_json(r["data"]) for r in rows]

    # --- Proof ---

    def save_proof(self, proof: Proof) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO proofs (id, pact_id, data)
                VALUES (?, ?, ?)
                """,
                (proof.id, proof.pact_id, proof.model_dump_json()),
            )
            self.conn.commit()

    def list_proofs(self, pact_id: str) -> list[Proof]:
        rows = self.conn.execute(
            "SELECT data FROM proofs WHERE pact_id = ?", (pact_id,)
        ).fetchall()
        return [Proof.model_validate_json(r["data"]) for r in rows]

    # --- ReasoningTask ---

    def save_task(self, task: ReasoningTask) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tasks (id, pact_id, status, required_capability, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.pact_id,
                    task.status.value,
                    task.required_capability,
                    task.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_task(self, task_id: str) -> ReasoningTask | None:
        row = self.conn.execute(
            "SELECT data FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return ReasoningTask.model_validate_json(row["data"])

    def pending_tasks(self, capability: str | None = None) -> list[ReasoningTask]:
        from pact.models import TaskStatus

        if capability is None:
            rows = self.conn.execute(
                "SELECT data FROM tasks WHERE status = ?",
                (TaskStatus.pending.value,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM tasks WHERE status = ? AND required_capability = ?",
                (TaskStatus.pending.value, capability),
            ).fetchall()
        return [ReasoningTask.model_validate_json(r["data"]) for r in rows]

    def update_task(self, task: ReasoningTask) -> None:
        self.save_task(task)

    # --- Verdict ---

    def save_verdict(self, verdict: Verdict) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO verdicts (pact_id, status, data)
                VALUES (?, ?, ?)
                """,
                (verdict.pact_id, verdict.status.value, verdict.model_dump_json()),
            )
            self.conn.commit()

    def get_verdict(self, pact_id: str) -> Verdict | None:
        row = self.conn.execute(
            "SELECT data FROM verdicts WHERE pact_id = ?", (pact_id,)
        ).fetchone()
        if row is None:
            return None
        return Verdict.model_validate_json(row["data"])

    # --- Profile ---

    def save_profile(self, profile: Profile) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO profiles (owner, data)
                VALUES (?, ?)
                """,
                (profile.owner, profile.model_dump_json()),
            )
            self.conn.commit()

    def get_profile(self, owner: str) -> Profile | None:
        row = self.conn.execute(
            "SELECT data FROM profiles WHERE owner = ?", (owner,)
        ).fetchone()
        if row is None:
            return None
        return Profile.model_validate_json(row["data"])

    # --- LinkAccount ---

    def save_link_account(self, acct: LinkAccount) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO link_accounts (owner, data) VALUES (?, ?)",
                (acct.owner, acct.model_dump_json()),
            )
            self.conn.commit()

    def get_link_account(self, owner: str) -> LinkAccount | None:
        row = self.conn.execute(
            "SELECT data FROM link_accounts WHERE owner = ?", (owner,)
        ).fetchone()
        if row is None:
            return None
        return LinkAccount.model_validate_json(row["data"])

    # --- CoachingMessage ---

    def save_coaching_message(self, msg: CoachingMessage) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO coaching_messages (id, pact_id, sent_at, delivered_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.pact_id,
                    msg.sent_at.isoformat(),
                    msg.delivered_at.isoformat() if msg.delivered_at is not None else None,
                    msg.model_dump_json(),
                ),
            )
            self.conn.commit()

    def list_coaching_messages(self, pact_id: str) -> list[CoachingMessage]:
        rows = self.conn.execute(
            "SELECT data FROM coaching_messages WHERE pact_id = ? ORDER BY sent_at",
            (pact_id,),
        ).fetchall()
        return [CoachingMessage.model_validate_json(r["data"]) for r in rows]

    def get_coaching_message(self, msg_id: str) -> CoachingMessage | None:
        row = self.conn.execute(
            "SELECT data FROM coaching_messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if row is None:
            return None
        return CoachingMessage.model_validate_json(row["data"])

    def outbox(self, owner: str) -> list[CoachingMessage]:
        """Return undelivered outbound coaching messages across all of the owner's pacts.

        Messages are returned ordered by sent_at ascending (oldest first). Only
        outbound messages with delivered_at = None are included — these are the
        nudges the Hermes agent should relay then mark delivered.
        """
        pacts = self.list_pacts(owner=owner)
        if not pacts:
            return []
        pact_ids = [p.id for p in pacts]
        placeholders = ",".join("?" * len(pact_ids))
        # Filter by delivered_at IS NULL at the DB level; direction is in the JSON
        # blob so we filter on it in Python after deserialization.
        rows = self.conn.execute(
            f"""
            SELECT data FROM coaching_messages
            WHERE pact_id IN ({placeholders})
              AND delivered_at IS NULL
            ORDER BY sent_at
            """,
            pact_ids,
        ).fetchall()
        msgs = [CoachingMessage.model_validate_json(r["data"]) for r in rows]
        return [m for m in msgs if m.direction == "outbound"]

    def close(self) -> None:
        self.conn.close()

    # --- Demo reset ---

    def reset_all(self) -> None:
        with self._write_lock:
            self.conn.executescript(
                """
                DELETE FROM pacts;
                DELETE FROM proofs;
                DELETE FROM tasks;
                DELETE FROM verdicts;
                DELETE FROM profiles;
                DELETE FROM coaching_messages;
                """
            )
            self.conn.commit()
