"""
FastAPI application for Probabilize.
"""

import os
import math
from contextlib import asynccontextmanager
import numpy as np
from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db
from demo_seed import reset_database_files, seed_demo_data
from auth import hash_password, verify_password
from math_engine import (
    cost,
    infimum,
    implied_distribution,
    implied_probabilities,
    compute_trade,
    log_partition,
)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="Probabilize",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    name: str
    password: str

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("password")
    @classmethod
    def password_must_be_long_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class CreateClaimRequest(BaseModel):
    user_id: str
    name: str
    description: str = ""
    omega: List[str]
    probabilities: List[float]
    b: float

    @field_validator("b")
    @classmethod
    def b_must_be_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("b must be a finite positive number")
        return v

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("name must not be empty")
        return name

    @field_validator("omega")
    @classmethod
    def omega_must_not_be_empty(cls, v: List[str]) -> List[str]:
        if len(v) < 2:
            raise ValueError("omega must have at least 2 outcomes")
        cleaned = [item.strip() for item in v]
        if any(not item for item in cleaned):
            raise ValueError("omega labels must not be empty")
        lower_set = {item.lower() for item in cleaned}
        if len(lower_set) != len(cleaned):
            raise ValueError("omega labels must be unique")
        return cleaned

    @field_validator("probabilities")
    @classmethod
    def probs_must_sum_to_one(cls, v: List[float]) -> List[float]:
        if any(not math.isfinite(p) or p <= 0 for p in v):
            raise ValueError("all probabilities must be finite and positive")
        total = sum(v)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"probabilities must sum to 1, got {total}")
        return v

    @model_validator(mode="after")
    def lengths_must_match(self):
        if len(self.omega) != len(self.probabilities):
            raise ValueError("omega and probabilities must have the same length")
        return self


class TradeRequest(BaseModel):
    user_id: str
    delta_q: List[float]

    @field_validator("delta_q")
    @classmethod
    def delta_q_must_be_finite(cls, v: List[float]) -> List[float]:
        if not all(math.isfinite(x) for x in v):
            raise ValueError("delta_q values must be finite (no NaN or inf)")
        return v


class AdminResetRequest(BaseModel):
    seed_demo: bool = True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _enrich_claim(claim: dict) -> dict:
    """Add derived statistics to a claim dict."""
    q = np.array(claim["q_values"], dtype=float)
    probs = np.array(claim["probabilities"], dtype=float)
    b = claim["b"]

    claim["current_cost"] = float(cost(q, probs, b))
    claim["log_partition"] = float(log_partition(q, probs, b))
    claim["implied_rn"] = implied_distribution(q, probs, b).tolist()
    claim["implied_probs"] = implied_probabilities(q, probs, b).tolist()
    return claim


def _require_admin_reset_token(token: Optional[str]) -> None:
    configured = os.getenv("ADMIN_RESET_TOKEN", "")
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_RESET_TOKEN is not configured",
        )
    if token != configured:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.post("/api/register", status_code=201)
def register(req: RegisterRequest) -> dict:
    existing = db.get_user_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")
    user = db.create_user(req.name, hash_password(req.password))
    return user


@app.post("/api/login")
def login(req: RegisterRequest) -> dict:
    user_auth = db.get_user_auth_by_name(req.name)
    if not user_auth or not verify_password(req.password, user_auth.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return db.get_user(user_auth["id"])


@app.get("/api/users/{user_id}")
def get_user(user_id: str) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["positions"] = db.get_user_positions(user_id)
    return user


@app.get("/api/claims")
def list_claims() -> list:
    claims = db.get_all_claims()
    return [_enrich_claim(c) for c in claims]


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str) -> dict:
    claim = db.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return _enrich_claim(claim)


@app.get("/api/claims/{claim_id}/trades")
def get_claim_trades(claim_id: str, limit: int = 25) -> list:
    claim = db.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    return db.get_claim_trades(claim_id, limit)


@app.post("/api/claims", status_code=201)
def create_claim(req: CreateClaimRequest) -> dict:
    user = db.get_user(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Normalize probabilities to ensure exact sum-to-1
    probs = [p / sum(req.probabilities) for p in req.probabilities]
    claim = db.create_claim(
        creator_id=req.user_id,
        name=req.name,
        description=req.description,
        omega=req.omega,
        probabilities=probs,
        b=req.b,
    )
    return _enrich_claim(claim)


@app.post("/api/claims/{claim_id}/preview")
def preview_trade(claim_id: str, req: TradeRequest) -> dict:
    """Preview a trade without executing it."""
    claim = db.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    user = db.get_user(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    n = len(claim["omega"])
    if len(req.delta_q) != n:
        raise HTTPException(
            status_code=422,
            detail=f"delta_q must have length {n}",
        )

    q = np.array(claim["q_values"], dtype=float)
    probs = np.array(claim["probabilities"], dtype=float)
    b = claim["b"]

    position = db.get_position(req.user_id, claim_id)
    q_t = np.array(position["q_t_values"] if position else [0.0] * n, dtype=float)

    delta_q = np.array(req.delta_q, dtype=float)
    result = compute_trade(q, q_t, delta_q, user["balance"], probs, b)

    # Add implied distribution preview
    if result["valid"]:
        q_new = np.array(result["new_q"], dtype=float)
        result["new_implied_probs"] = implied_probabilities(q_new, probs, b).tolist()

    result["current_balance"] = user["balance"]
    return result


@app.post("/api/claims/{claim_id}/trade")
def execute_trade(claim_id: str, req: TradeRequest) -> dict:
    """Execute a trade atomically."""
    claim = db.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    user = db.get_user(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    n = len(claim["omega"])
    if len(req.delta_q) != n:
        raise HTTPException(
            status_code=422,
            detail=f"delta_q must have length {n}",
        )

    q = np.array(claim["q_values"], dtype=float)
    probs = np.array(claim["probabilities"], dtype=float)
    b = claim["b"]

    position = db.get_position(req.user_id, claim_id)
    q_t = np.array(position["q_t_values"] if position else [0.0] * n, dtype=float)

    # Capture pre-trade state for compare-and-swap in execute_trade_atomic
    expected_q = claim["q_values"]
    expected_q_t = position["q_t_values"] if position else None
    expected_balance = user["balance"]

    delta_q = np.array(req.delta_q, dtype=float)
    result = compute_trade(q, q_t, delta_q, user["balance"], probs, b)

    if not result["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Insufficient balance for this trade",
                "required_collateral": result["required_collateral"],
                "current_balance": user["balance"],
                "delta_c": result["delta_c"],
                "delta_inf": result["delta_inf"],
            },
        )

    try:
        db.execute_trade_atomic(
            user_id=req.user_id,
            claim_id=claim_id,
            expected_q=expected_q,
            expected_q_t=expected_q_t,
            expected_balance=expected_balance,
            new_q=result["new_q"],
            new_q_t=result["new_q_t"],
            new_balance=result["new_balance"],
            delta_q=req.delta_q,
            required_collateral=result["required_collateral"],
            delta_c=result["delta_c"],
            delta_inf=result["delta_inf"],
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail="Trade rejected due to concurrent modification. Please retry.",
        ) from exc

    updated_claim = db.get_claim(claim_id)
    return {
        "success": True,
        "trade": result,
        "claim": _enrich_claim(updated_claim),
        "new_balance": result["new_balance"],
    }


@app.post("/api/admin/reset")
def admin_reset(
    req: AdminResetRequest,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict:
    """Reset the configured SQLite DB, optionally reseeding demo data."""
    _require_admin_reset_token(x_admin_token)

    target_path = db.DB_PATH
    if req.seed_demo:
        result = seed_demo_data(db_path=target_path, reset=True)
        return {
            "success": True,
            "mode": "seeded",
            "db_path": result["db_path"],
            "counts": result["counts"],
            "demo_password": result["password"],
        }

    reset_database_files(target_path)
    db.init_db(target_path)
    return {
        "success": True,
        "mode": "empty",
        "db_path": target_path,
        "counts": {"users": 0, "claims": 0, "trades": 0},
    }


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
