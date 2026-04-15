"""Reset and seed the local SQLite database with reusable demo data."""

import argparse
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from backend import database as db
from backend.auth import hash_password
from backend.math_engine import compute_trade

DEMO_PASSWORD = "demo-pass-123"

DEMO_USERS = [
    {"name": "alice"},
    {"name": "bob"},
    {"name": "carol"},
]

DEMO_CLAIMS = [
    {
        "name": "Will the city deploy autonomous buses by 2027?",
        "description": "Municipal pilot announcement and public service launch count as success.",
        "omega": ["Yes", "No"],
        "probabilities": [0.35, 0.65],
        "b": 1.1,
    },
    {
        "name": "What share of the grid will be solar at year end?",
        "description": "Bucketed outcome market for the national solar generation share.",
        "omega": ["Below 20%", "20%-25%", "Above 25%"],
        "probabilities": [0.25, 0.5, 0.25],
        "b": 1.3,
    },
    {
        "name": "Which launch window will Mars Probe III hit?",
        "description": "Outcome resolves to the first successful launch window officially announced.",
        "omega": ["Q3 2026", "Q4 2026", "2027 or later"],
        "probabilities": [0.3, 0.45, 0.25],
        "b": 1.0,
    },
]

DEMO_TRADES = [
    {
        "user": "alice",
        "claim": "Will the city deploy autonomous buses by 2027?",
        "delta_q": [0.6, -0.6],
    },
    {
        "user": "bob",
        "claim": "Will the city deploy autonomous buses by 2027?",
        "delta_q": [-0.2, 0.2],
    },
    {
        "user": "carol",
        "claim": "What share of the grid will be solar at year end?",
        "delta_q": [-0.1, 0.35, -0.25],
    },
    {
        "user": "alice",
        "claim": "What share of the grid will be solar at year end?",
        "delta_q": [-0.15, -0.05, 0.2],
    },
    {
        "user": "bob",
        "claim": "Which launch window will Mars Probe III hit?",
        "delta_q": [0.1, 0.15, -0.25],
    },
    {
        "user": "carol",
        "claim": "Which launch window will Mars Probe III hit?",
        "delta_q": [-0.1, 0.2, -0.1],
    },
]


def reset_database_files(db_path: str) -> None:
    path = Path(db_path)
    for suffix in ("", "-shm", "-wal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def _table_counts() -> Dict[str, int]:
    with db.get_connection() as conn:
        return {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "claims": conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
            "trades": conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        }


def _ensure_empty_database() -> None:
    counts = _table_counts()
    if any(counts.values()):
        raise RuntimeError(
            "Database is not empty. Reset it first or run demo_seed with --reset."
        )


def _seed_users() -> Dict[str, Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for spec in DEMO_USERS:
        user = db.create_user(spec["name"], hash_password(DEMO_PASSWORD))
        users[spec["name"]] = user
    return users


def _seed_claims(users: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    claims: Dict[str, Dict[str, Any]] = {}
    creator_id = users["alice"]["id"]
    for spec in DEMO_CLAIMS:
        claim = db.create_claim(
            creator_id=creator_id,
            name=spec["name"],
            description=spec["description"],
            omega=spec["omega"],
            probabilities=spec["probabilities"],
            b=spec["b"],
        )
        claims[spec["name"]] = claim
    return claims


def _execute_seed_trade(user: Dict[str, Any], claim: Dict[str, Any], delta_q_values: List[float]) -> None:
    q = np.array(claim["q_values"], dtype=float)
    probs = np.array(claim["probabilities"], dtype=float)
    position = db.get_position(user["id"], claim["id"])
    q_t = np.array(position["q_t_values"] if position else [0.0] * len(q), dtype=float)
    result = compute_trade(
        q=q,
        q_t=q_t,
        delta_q=np.array(delta_q_values, dtype=float),
        balance=user["balance"],
        probs=probs,
        b=claim["b"],
    )
    if not result["valid"]:
        raise RuntimeError("Demo trade is invalid; seed data is inconsistent.")

    db.execute_trade_atomic(
        user_id=user["id"],
        claim_id=claim["id"],
        expected_q=claim["q_values"],
        expected_q_t=position["q_t_values"] if position else None,
        expected_balance=user["balance"],
        new_q=result["new_q"],
        new_q_t=result["new_q_t"],
        new_balance=result["new_balance"],
        delta_q=delta_q_values,
        required_collateral=result["required_collateral"],
        delta_c=result["delta_c"],
        delta_inf=result["delta_inf"],
    )

    claim["q_values"] = result["new_q"]
    user["balance"] = result["new_balance"]


def seed_demo_data(db_path: str | None = None, reset: bool = False) -> Dict[str, Any]:
    target_path = db_path or db.DB_PATH
    if reset:
        reset_database_files(target_path)

    db.init_db(target_path)
    _ensure_empty_database()

    users = _seed_users()
    claims = _seed_claims(users)

    for spec in DEMO_TRADES:
        _execute_seed_trade(
            user=users[spec["user"]],
            claim=claims[spec["claim"]],
            delta_q_values=spec["delta_q"],
        )

    counts = _table_counts()
    return {
        "db_path": target_path,
        "password": DEMO_PASSWORD,
        "users": [{"name": name, "id": user["id"]} for name, user in users.items()],
        "claims": [{"name": name, "id": claim["id"]} for name, claim in claims.items()],
        "counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local market.db with demo data.")
    parser.add_argument("--db-path", help="SQLite database path to seed.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the database file and WAL sidecars before seeding.",
    )
    args = parser.parse_args()

    result = seed_demo_data(db_path=args.db_path, reset=args.reset)
    print(f"Seeded demo data into {result['db_path']}")
    print(
        f"Created {result['counts']['users']} users, {result['counts']['claims']} claims, "
        f"and {result['counts']['trades']} trades."
    )
    print(f"Login password for all demo users: {result['password']}")
    print("Users:")
    for user in result["users"]:
        print(f"- {user['name']}")


if __name__ == "__main__":
    main()