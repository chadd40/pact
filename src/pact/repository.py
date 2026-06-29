from __future__ import annotations

import sqlite3
import threading
from datetime import datetime

from pact.models import (
    AccountLink,
    AgentSession,
    CoachingMessage,
    DonationReceipt,
    LinkAccount,
    Pact,
    PactStatus,
    PaymentAttempt,
    Profile,
    Proof,
    ProofReview,
    ReasoningTask,
    Verdict,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        # One shared sqlite3 connection (check_same_thread=False) is accessed from
        # FastAPI's threadpool — and the redesigned UI fires several reads in
        # parallel per page. A single Python sqlite3 connection is NOT safe for
        # concurrent use (even read+read races a shared cursor), so ALL access —
        # reads and writes — is serialized through this reentrant lock. RLock so a
        # write method that internally calls a read on the same thread can't
        # self-deadlock. Cheap and correct for a local-first single-process app.
        self._write_lock = threading.RLock()
        # Ephemeral process state: when a reasoning worker (`/pact serve`) last
        # polled the queue. Used to decide whether to wait for the agent brain or
        # fall back to the stub immediately. Not persisted — presence is liveness,
        # not history.
        self._worker_last_seen: datetime | None = None

    def mark_worker_seen(self, now: datetime) -> None:
        """Record that a reasoning worker just polled the queue (a liveness beat)."""
        with self._write_lock:
            self._worker_last_seen = now

    def worker_seen_within(self, now: datetime, seconds: float) -> bool:
        """True iff a worker polled within the last ``seconds`` (relative to ``now``)."""
        with self._write_lock:
            last = self._worker_last_seen
        if last is None:
            return False
        return (now - last).total_seconds() <= seconds

    def worker_last_seen(self) -> datetime | None:
        """Return the latest reasoning-worker heartbeat timestamp, if any."""
        with self._write_lock:
            return self._worker_last_seen

    def _one(self, sql: str, params: tuple = ()):
        with self._write_lock:
            return self.conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()):
        with self._write_lock:
            return self.conn.execute(sql, params).fetchall()

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

            CREATE TABLE IF NOT EXISTS account_links (
                owner TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_account_links_token ON account_links(token);

            CREATE TABLE IF NOT EXISTS agent_sessions (
                owner TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                token_prefix TEXT NOT NULL,
                revoked_at TEXT,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_token_hash ON agent_sessions(token_hash);

            CREATE TABLE IF NOT EXISTS payment_attempts (
                id TEXT PRIMARY KEY,
                pact_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_ref TEXT,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_payment_attempts_pact ON payment_attempts(pact_id);
            CREATE INDEX IF NOT EXISTS idx_payment_attempts_owner ON payment_attempts(owner);

            CREATE TABLE IF NOT EXISTS proof_reviews (
                id TEXT PRIMARY KEY,
                proof_id TEXT NOT NULL,
                pact_id TEXT NOT NULL,
                status TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proof_reviews_proof ON proof_reviews(proof_id);
            CREATE INDEX IF NOT EXISTS idx_proof_reviews_pact ON proof_reviews(pact_id);

            CREATE TABLE IF NOT EXISTS donation_receipts (
                pact_id TEXT PRIMARY KEY,
                receipt_status TEXT NOT NULL,
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
        row = self._one("SELECT data FROM pacts WHERE id = ?", (pact_id,))
        if row is None:
            return None
        return Pact.model_validate_json(row["data"])

    def update_pact(self, pact: Pact) -> None:
        self.save_pact(pact)

    def list_pacts(self, owner: str | None = None) -> list[Pact]:
        if owner is None:
            rows = self._all("SELECT data FROM pacts")
        else:
            rows = self._all("SELECT data FROM pacts WHERE owner = ?", (owner,))
        return [Pact.model_validate_json(r["data"]) for r in rows]

    def due_active_pacts(self, now: datetime) -> list[Pact]:
        rows = self._all(
            "SELECT data FROM pacts WHERE status = ? AND deadline_at <= ?",
            (PactStatus.active.value, now.isoformat()),
        )
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
        rows = self._all("SELECT data FROM proofs WHERE pact_id = ?", (pact_id,))
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
        row = self._one("SELECT data FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            return None
        return ReasoningTask.model_validate_json(row["data"])

    def pending_tasks(self, capability: str | None = None) -> list[ReasoningTask]:
        from pact.models import TaskStatus

        if capability is None:
            rows = self._all(
                "SELECT data FROM tasks WHERE status = ?", (TaskStatus.pending.value,)
            )
        else:
            rows = self._all(
                "SELECT data FROM tasks WHERE status = ? AND required_capability = ?",
                (TaskStatus.pending.value, capability),
            )
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
        row = self._one("SELECT data FROM verdicts WHERE pact_id = ?", (pact_id,))
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
        row = self._one("SELECT data FROM profiles WHERE owner = ?", (owner,))
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
        row = self._one("SELECT data FROM link_accounts WHERE owner = ?", (owner,))
        if row is None:
            return None
        return LinkAccount.model_validate_json(row["data"])

    # --- AccountLink (agent ↔ account token) ---

    def save_account_link(self, link: AccountLink) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO account_links (owner, token, data) VALUES (?, ?, ?)",
                (link.owner, link.token_hash, link.model_dump_json()),
            )
            self.conn.commit()
        self.save_agent_session(link)

    def get_account_link(self, owner: str) -> AccountLink | None:
        row = self._one("SELECT data FROM account_links WHERE owner = ?", (owner,))
        if row is None:
            return None
        return AccountLink.model_validate_json(row["data"])

    def owner_for_token(self, token: str) -> str | None:
        from pact.accounts import hash_token

        return self.owner_for_token_hash(hash_token(token))

    # --- AgentSession ---

    def save_agent_session(self, session: AgentSession) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO agent_sessions
                    (owner, token_hash, token_prefix, revoked_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.owner,
                    session.token_hash,
                    session.token_prefix,
                    session.revoked_at.isoformat() if session.revoked_at is not None else None,
                    session.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_agent_session(self, owner: str) -> AgentSession | None:
        row = self._one("SELECT data FROM agent_sessions WHERE owner = ?", (owner,))
        if row is None:
            return None
        return AgentSession.model_validate_json(row["data"])

    def owner_for_token_hash(self, token_hash: str) -> str | None:
        row = self._one(
            """
            SELECT owner FROM agent_sessions
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,),
        )
        return row["owner"] if row is not None else None

    def session_for_token_hash(self, token_hash: str) -> AgentSession | None:
        row = self._one(
            """
            SELECT data FROM agent_sessions
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,),
        )
        if row is None:
            return None
        return AgentSession.model_validate_json(row["data"])

    # --- PaymentAttempt ---

    def save_payment_attempt(self, attempt: PaymentAttempt) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO payment_attempts
                    (id, pact_id, owner, status, provider_ref, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.id,
                    attempt.pact_id,
                    attempt.owner,
                    attempt.status,
                    attempt.provider_ref,
                    attempt.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_payment_attempt(self, attempt_id: str) -> PaymentAttempt | None:
        row = self._one("SELECT data FROM payment_attempts WHERE id = ?", (attempt_id,))
        if row is None:
            return None
        return PaymentAttempt.model_validate_json(row["data"])

    def list_payment_attempts(self, pact_id: str) -> list[PaymentAttempt]:
        rows = self._all(
            "SELECT data FROM payment_attempts WHERE pact_id = ? ORDER BY id",
            (pact_id,),
        )
        return [PaymentAttempt.model_validate_json(r["data"]) for r in rows]

    # --- ProofReview ---

    def save_proof_review(self, review: ProofReview) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO proof_reviews (id, proof_id, pact_id, status, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.proof_id,
                    review.pact_id,
                    review.status.value,
                    review.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_proof_review(self, review_id: str) -> ProofReview | None:
        row = self._one("SELECT data FROM proof_reviews WHERE id = ?", (review_id,))
        if row is None:
            return None
        return ProofReview.model_validate_json(row["data"])

    def list_proof_reviews(self, proof_id: str) -> list[ProofReview]:
        rows = self._all(
            "SELECT data FROM proof_reviews WHERE proof_id = ? ORDER BY id",
            (proof_id,),
        )
        return [ProofReview.model_validate_json(r["data"]) for r in rows]

    # --- DonationReceipt ---

    def save_donation_receipt(self, receipt: DonationReceipt) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO donation_receipts (pact_id, receipt_status, data)
                VALUES (?, ?, ?)
                """,
                (
                    receipt.pact_id,
                    receipt.receipt_status,
                    receipt.model_dump_json(),
                ),
            )
            self.conn.commit()

    def get_donation_receipt(self, pact_id: str) -> DonationReceipt | None:
        row = self._one("SELECT data FROM donation_receipts WHERE pact_id = ?", (pact_id,))
        if row is None:
            return None
        return DonationReceipt.model_validate_json(row["data"])

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
        rows = self._all(
            "SELECT data FROM coaching_messages WHERE pact_id = ? ORDER BY sent_at",
            (pact_id,),
        )
        return [CoachingMessage.model_validate_json(r["data"]) for r in rows]

    def get_coaching_message(self, msg_id: str) -> CoachingMessage | None:
        row = self._one("SELECT data FROM coaching_messages WHERE id = ?", (msg_id,))
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
        rows = self._all(
            f"""
            SELECT data FROM coaching_messages
            WHERE pact_id IN ({placeholders})
              AND delivered_at IS NULL
            ORDER BY sent_at
            """,
            tuple(pact_ids),
        )
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
                DELETE FROM agent_sessions;
                DELETE FROM payment_attempts;
                DELETE FROM proof_reviews;
                DELETE FROM donation_receipts;
                DELETE FROM coaching_messages;
                """
            )
            self.conn.commit()
