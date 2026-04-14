"""Integration tests for claim trade history API."""

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.database as db
import backend.app as app_module

app = app_module.app


def _use_temp_db(db_path: Path) -> None:
    # Keep both imports aligned to the same SQLite file.
    db.DB_PATH = str(db_path)
    app_module.db.DB_PATH = str(db_path)
    app_module.db.init_db(str(db_path))


def test_trade_is_persisted_and_returned_in_claim_trades(tmp_path: Path):
    db_path = tmp_path / "test-market.db"
    _use_temp_db(db_path)

    with TestClient(app) as client:
        reg = client.post(
            "/api/register",
            json={"name": "alice", "password": "password123"},
        )
        assert reg.status_code == 201
        user = reg.json()

        create_claim = client.post(
            "/api/claims",
            json={
                "user_id": user["id"],
                "name": "Will test pass?",
                "description": "integration test claim",
                "omega": ["Yes", "No"],
                "probabilities": [0.5, 0.5],
                "b": 1.0,
            },
        )
        assert create_claim.status_code == 201
        claim = create_claim.json()

        trade = client.post(
            f"/api/claims/{claim['id']}/trade",
            json={"user_id": user["id"], "delta_q": [0.2, -0.2]},
        )
        assert trade.status_code == 200

        trades = client.get(f"/api/claims/{claim['id']}/trades?limit=10")
        assert trades.status_code == 200
        payload = trades.json()
        assert len(payload) == 1

        row = payload[0]
        assert row["claim_id"] == claim["id"]
        assert row["user_id"] == user["id"]
        assert row["user_name"] == "alice"
        assert row["delta_q_values"] == [0.2, -0.2]
        assert row["required_collateral"] > 0
        assert "created_at" in row


def test_claim_trades_limit_validation(tmp_path: Path):
    db_path = tmp_path / "test-market.db"
    _use_temp_db(db_path)

    with TestClient(app) as client:
        reg = client.post(
            "/api/register",
            json={"name": "bob", "password": "password123"},
        )
        assert reg.status_code == 201
        user = reg.json()

        create_claim = client.post(
            "/api/claims",
            json={
                "user_id": user["id"],
                "name": "Limit check",
                "description": "",
                "omega": ["A", "B"],
                "probabilities": [0.5, 0.5],
                "b": 1.0,
            },
        )
        assert create_claim.status_code == 201
        claim = create_claim.json()

        bad = client.get(f"/api/claims/{claim['id']}/trades?limit=0")
        assert bad.status_code == 422
