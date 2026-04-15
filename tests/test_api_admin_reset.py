"""Integration tests for protected admin reset endpoint."""

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


def _count_rows() -> dict:
    with db.get_connection() as conn:
        return {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "claims": conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
            "trades": conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        }


def test_admin_reset_requires_configured_token(tmp_path: Path):
    db_path = tmp_path / "test-market.db"
    _use_temp_db(db_path)

    os.environ.pop("ADMIN_RESET_TOKEN", None)

    with TestClient(app) as client:
        resp = client.post("/api/admin/reset", json={"seed_demo": True})

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_admin_reset_rejects_invalid_token(tmp_path: Path):
    db_path = tmp_path / "test-market.db"
    _use_temp_db(db_path)

    os.environ["ADMIN_RESET_TOKEN"] = "secret-token"

    with TestClient(app) as client:
        resp = client.post(
            "/api/admin/reset",
            headers={"x-admin-token": "wrong"},
            json={"seed_demo": True},
        )

    assert resp.status_code == 401


def test_admin_reset_seeded_and_empty_modes(tmp_path: Path):
    db_path = tmp_path / "test-market.db"
    _use_temp_db(db_path)

    os.environ["ADMIN_RESET_TOKEN"] = "secret-token"

    with TestClient(app) as client:
        seeded = client.post(
            "/api/admin/reset",
            headers={"x-admin-token": "secret-token"},
            json={"seed_demo": True},
        )
        assert seeded.status_code == 200
        seeded_payload = seeded.json()
        assert seeded_payload["mode"] == "seeded"
        assert seeded_payload["counts"] == {"users": 3, "claims": 3, "trades": 6}

        counts_after_seed = _count_rows()
        assert counts_after_seed == {"users": 3, "claims": 3, "trades": 6}

        empty = client.post(
            "/api/admin/reset",
            headers={"x-admin-token": "secret-token"},
            json={"seed_demo": False},
        )
        assert empty.status_code == 200
        empty_payload = empty.json()
        assert empty_payload["mode"] == "empty"
        assert empty_payload["counts"] == {"users": 0, "claims": 0, "trades": 0}

        counts_after_empty = _count_rows()
        assert counts_after_empty == {"users": 0, "claims": 0, "trades": 0}
