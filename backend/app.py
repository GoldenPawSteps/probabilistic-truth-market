"""
FastAPI application for the Perpetual Probabilistic Truth Market.
"""

import os
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from typing import List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db
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

app = FastAPI(title="Perpetual Probabilistic Truth Market", version="1.0.0")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
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
        if v <= 0:
            raise ValueError("b must be positive")
        return v

    @field_validator("omega")
    @classmethod
    def omega_must_not_be_empty(cls, v: List[str]) -> List[str]:
        if len(v) < 2:
            raise ValueError("omega must have at least 2 outcomes")
        return v

    @field_validator("probabilities")
    @classmethod
    def probs_must_sum_to_one(cls, v: List[float]) -> List[float]:
        if any(p <= 0 for p in v):
            raise ValueError("all probabilities must be positive")
        total = sum(v)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"probabilities must sum to 1, got {total}")
        return v


class TradeRequest(BaseModel):
    user_id: str
    delta_q: List[float]


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


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.post("/api/register", status_code=201)
def register(req: RegisterRequest) -> dict:
    existing = db.get_user_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")
    user = db.create_user(req.name)
    return user


@app.post("/api/login")
def login(req: RegisterRequest) -> dict:
    user = db.get_user_by_name(req.name)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


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


@app.post("/api/claims", status_code=201)
def create_claim(req: CreateClaimRequest) -> dict:
    if len(req.omega) != len(req.probabilities):
        raise HTTPException(
            status_code=422,
            detail="omega and probabilities must have the same length",
        )
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

    db.execute_trade_atomic(
        user_id=req.user_id,
        claim_id=claim_id,
        new_q=result["new_q"],
        new_q_t=result["new_q_t"],
        new_balance=result["new_balance"],
    )

    updated_claim = db.get_claim(claim_id)
    return {
        "success": True,
        "trade": result,
        "claim": _enrich_claim(updated_claim),
        "new_balance": result["new_balance"],
    }


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
