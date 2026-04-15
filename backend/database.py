"""
SQLite persistence layer for Probabilize.
"""

import sqlite3
import json
import uuid
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

DEFAULT_DB_NAME = "market.db"


def _resolve_db_path() -> str:
    explicit_db_path = os.getenv("DATABASE_PATH")
    if explicit_db_path:
        return explicit_db_path

    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if railway_mount:
        return os.path.join(railway_mount, DEFAULT_DB_NAME)

    # Railway persistent volumes are commonly mounted at /data.
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return os.path.join("/data", DEFAULT_DB_NAME)

    return DEFAULT_DB_NAME


DB_PATH = _resolve_db_path()


def _public_user(d: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(d)
    out.pop("password_hash", None)
    return out


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    global DB_PATH
    if db_path is not None:
        DB_PATH = db_path
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                balance REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                omega TEXT NOT NULL,
                probabilities TEXT NOT NULL,
                q_values TEXT NOT NULL,
                b REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (creator_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS positions (
                user_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                q_t_values TEXT NOT NULL,
                PRIMARY KEY (user_id, claim_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                delta_q_values TEXT NOT NULL,
                required_collateral REAL NOT NULL,
                delta_c REAL NOT NULL,
                delta_inf REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (claim_id) REFERENCES claims(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )

        # Backward-compatible migration for existing databases.
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        col_names = {row["name"] for row in columns}
        if "password_hash" not in col_names:
            conn.execute(
                "ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def create_user(name: str, password_hash: str) -> Dict:
    user_id = str(uuid.uuid4())
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, name, password_hash, balance, created_at) VALUES (?, ?, ?, 1.0, ?)",
            (user_id, name, password_hash, now),
        )
        conn.commit()
    return {"id": user_id, "name": name, "balance": 1.0, "created_at": now}


def get_user(user_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _public_user(dict(row)) if row else None


def get_user_by_name(name: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE name = ?", (name,)
        ).fetchone()
        return _public_user(dict(row)) if row else None


def get_user_auth_by_name(name: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None


def update_user_balance(user_id: str, new_balance: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET balance = ? WHERE id = ?", (new_balance, user_id)
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def create_claim(
    creator_id: str,
    name: str,
    description: str,
    omega: list,
    probabilities: list,
    b: float,
) -> Dict:
    claim_id = str(uuid.uuid4())
    now = _now()
    q_values = [0.0] * len(omega)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO claims
               (id, creator_id, name, description, omega, probabilities, q_values, b, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim_id,
                creator_id,
                name,
                description,
                json.dumps(omega),
                json.dumps(probabilities),
                json.dumps(q_values),
                b,
                now,
            ),
        )
        conn.commit()
    return {
        "id": claim_id,
        "creator_id": creator_id,
        "name": name,
        "description": description,
        "omega": omega,
        "probabilities": probabilities,
        "q_values": q_values,
        "b": b,
        "created_at": now,
    }


def get_claim(claim_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["omega"] = json.loads(d["omega"])
        d["probabilities"] = json.loads(d["probabilities"])
        d["q_values"] = json.loads(d["q_values"])
        return d


def get_all_claims() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM claims ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["omega"] = json.loads(d["omega"])
            d["probabilities"] = json.loads(d["probabilities"])
            d["q_values"] = json.loads(d["q_values"])
            result.append(d)
        return result


def update_claim_q(claim_id: str, q_values: list) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE claims SET q_values = ? WHERE id = ?",
            (json.dumps(q_values), claim_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def get_position(user_id: str, claim_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE user_id = ? AND claim_id = ?",
            (user_id, claim_id),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["q_t_values"] = json.loads(d["q_t_values"])
        return d


def upsert_position(user_id: str, claim_id: str, q_t_values: list) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM positions WHERE user_id = ? AND claim_id = ?",
            (user_id, claim_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE positions SET q_t_values = ? WHERE user_id = ? AND claim_id = ?",
                (json.dumps(q_t_values), user_id, claim_id),
            )
        else:
            conn.execute(
                "INSERT INTO positions (user_id, claim_id, q_t_values) VALUES (?, ?, ?)",
                (user_id, claim_id, json.dumps(q_t_values)),
            )
        conn.commit()


def get_user_positions(user_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.claim_id, p.q_t_values,
                      c.name AS claim_name, c.omega, c.probabilities,
                      c.q_values, c.b
               FROM positions p
               JOIN claims c ON p.claim_id = c.id
               WHERE p.user_id = ?""",
            (user_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["q_t_values"] = json.loads(d["q_t_values"])
            d["omega"] = json.loads(d["omega"])
            d["probabilities"] = json.loads(d["probabilities"])
            d["q_values"] = json.loads(d["q_values"])
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


def get_claim_trades(claim_id: str, limit: int = 25) -> List[Dict]:
    safe_limit = max(1, min(limit, 200))
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT t.id, t.claim_id, t.user_id, u.name AS user_name,
                      t.delta_q_values, t.required_collateral, t.delta_c,
                      t.delta_inf, t.created_at
               FROM trades t
               JOIN users u ON t.user_id = u.id
               WHERE t.claim_id = ?
               ORDER BY t.created_at DESC
               LIMIT ?""",
            (claim_id, safe_limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["delta_q_values"] = json.loads(d["delta_q_values"])
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Atomic trade execution
# ---------------------------------------------------------------------------


def execute_trade_atomic(
    user_id: str,
    claim_id: str,
    expected_q: list,
    expected_q_t: Optional[list],
    expected_balance: float,
    new_q: list,
    new_q_t: list,
    new_balance: float,
    delta_q: list,
    required_collateral: float,
    delta_c: float,
    delta_inf: float,
) -> None:
    """
    Atomically update claim state, user position, and user balance.

    Re-reads claim/position/balance inside a BEGIN IMMEDIATE transaction and
    aborts with RuntimeError if the state has changed since validation was
    performed (compare-and-swap). This prevents lost updates from concurrent
    trades.
    """
    conn = get_connection()
    try:
        conn.isolation_level = None  # manual transaction control
        conn.execute("BEGIN IMMEDIATE")

        claim_row = conn.execute(
            "SELECT q_values FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        user_row = conn.execute(
            "SELECT balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        position_row = conn.execute(
            "SELECT q_t_values FROM positions WHERE user_id = ? AND claim_id = ?",
            (user_id, claim_id),
        ).fetchone()

        if claim_row is None:
            raise ValueError(f"Claim not found: {claim_id}")
        if user_row is None:
            raise ValueError(f"User not found: {user_id}")

        current_q = json.loads(claim_row["q_values"])
        current_q_t = (
            json.loads(position_row["q_t_values"]) if position_row is not None else None
        )
        current_balance = user_row["balance"]

        if (
            current_q != expected_q
            or current_q_t != expected_q_t
            or current_balance != expected_balance
        ):
            conn.execute("ROLLBACK")
            conn.close()
            raise RuntimeError(
                "Concurrent modification detected while executing trade"
            )

        conn.execute(
            "UPDATE claims SET q_values = ? WHERE id = ?",
            (json.dumps(new_q), claim_id),
        )
        if position_row is not None:
            conn.execute(
                "UPDATE positions SET q_t_values = ? WHERE user_id = ? AND claim_id = ?",
                (json.dumps(new_q_t), user_id, claim_id),
            )
        else:
            conn.execute(
                "INSERT INTO positions (user_id, claim_id, q_t_values) VALUES (?, ?, ?)",
                (user_id, claim_id, json.dumps(new_q_t)),
            )
        conn.execute(
            "UPDATE users SET balance = ? WHERE id = ?",
            (new_balance, user_id),
        )
        conn.execute(
            """INSERT INTO trades
               (id, claim_id, user_id, delta_q_values, required_collateral, delta_c, delta_inf, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                claim_id,
                user_id,
                json.dumps(delta_q),
                required_collateral,
                delta_c,
                delta_inf,
                _now(),
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        raise
