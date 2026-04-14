"""Tests for the reusable demo seed workflow."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.database as db
from backend.demo_seed import DEMO_PASSWORD, seed_demo_data


def test_seed_demo_data_populates_users_claims_and_trades(tmp_path: Path):
    db_path = tmp_path / "seeded-market.db"

    result = seed_demo_data(db_path=str(db_path), reset=True)

    assert result["counts"] == {"users": 3, "claims": 3, "trades": 6}
    assert result["password"] == DEMO_PASSWORD

    alice_auth = db.get_user_auth_by_name("alice")
    assert alice_auth is not None
    assert alice_auth["password_hash"] != DEMO_PASSWORD

    claims = db.get_all_claims()
    assert len(claims) == 3
    assert any(claim["q_values"] != [0.0] * len(claim["omega"]) for claim in claims)

    with db.get_connection() as conn:
        trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    assert trade_count == 6


def test_seed_demo_data_requires_empty_db_without_reset(tmp_path: Path):
    db_path = tmp_path / "seeded-market.db"

    seed_demo_data(db_path=str(db_path), reset=True)

    try:
        seed_demo_data(db_path=str(db_path), reset=False)
    except RuntimeError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("Expected seed_demo_data to reject a non-empty database")

    result = seed_demo_data(db_path=str(db_path), reset=True)
    assert result["counts"]["trades"] == 6