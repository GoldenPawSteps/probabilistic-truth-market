"""
Tests for the mathematical engine of the Perpetual Probabilistic Truth Market.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np

from backend.math_engine import (
    log_sum_exp,
    log_partition,
    cost,
    infimum,
    implied_distribution,
    implied_probabilities,
    compute_trade,
)


# ---------------------------------------------------------------------------
# log_sum_exp
# ---------------------------------------------------------------------------


def test_log_sum_exp_uniform():
    """log(sum_i 1/n * exp(x_i)) with all x_i=0 should give log(1)=0."""
    n = 4
    x = np.zeros(n)
    w = np.full(n, 1.0 / n)
    assert abs(log_sum_exp(x, w)) < 1e-10


def test_log_sum_exp_numerical_stability():
    """Should not overflow even for large x values."""
    x = np.array([1000.0, 1001.0, 999.0])
    w = np.array([1 / 3, 1 / 3, 1 / 3])
    result = log_sum_exp(x, w)
    # Should be approximately 1000 + log(exp(-1) + 1 + exp(1)) / 3
    assert np.isfinite(result)
    assert result > 999.0


def test_log_sum_exp_single_element():
    """With one element, log_sum_exp(x, [1]) == x."""
    x = np.array([3.14])
    w = np.array([1.0])
    assert abs(log_sum_exp(x, w) - 3.14) < 1e-10


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


def test_cost_zero_q():
    """C(0) = b * log(E_P[e^0]) = b * log(1) = 0."""
    q = np.zeros(5)
    probs = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    b = 2.0
    assert abs(cost(q, probs, b)) < 1e-10


def test_cost_constant_q():
    """C(q + c) = C(q) + c (shift invariance with constant addition)."""
    q = np.array([1.0, 2.0, 3.0])
    probs = np.array([0.3, 0.4, 0.3])
    b = 1.0
    c = 5.0
    assert abs(cost(q + c, probs, b) - (cost(q, probs, b) + c)) < 1e-8


def test_cost_satisfies_jensen():
    """C(q) >= E_P[q] by Jensen's inequality (since C is convex)."""
    q = np.array([1.0, 0.0, -1.0, 2.0])
    probs = np.array([0.25, 0.25, 0.25, 0.25])
    b = 1.0
    expected_q = float(np.sum(probs * q))
    assert cost(q, probs, b) >= expected_q - 1e-10


def test_cost_path_independent():
    """C is path-independent: order of applying delta_q doesn't matter."""
    q = np.array([0.5, -0.5, 0.0])
    probs = np.array([1 / 3, 1 / 3, 1 / 3])
    b = 1.5
    d1 = np.array([0.3, 0.1, -0.2])
    d2 = np.array([0.1, 0.4, 0.0])
    # Apply d1 then d2
    c_12 = cost(q + d1 + d2, probs, b)
    # Apply d2 then d1
    c_21 = cost(q + d2 + d1, probs, b)
    assert abs(c_12 - c_21) < 1e-12


def test_cost_convexity():
    """C(lambda*q1 + (1-lambda)*q2) <= lambda*C(q1) + (1-lambda)*C(q2)."""
    q1 = np.array([1.0, -1.0, 0.5])
    q2 = np.array([-0.5, 2.0, 0.0])
    probs = np.array([0.3, 0.4, 0.3])
    b = 1.0
    lam = 0.6
    q_mix = lam * q1 + (1 - lam) * q2
    assert cost(q_mix, probs, b) <= lam * cost(q1, probs, b) + (1 - lam) * cost(q2, probs, b) + 1e-10


# ---------------------------------------------------------------------------
# infimum
# ---------------------------------------------------------------------------


def test_infimum_basic():
    q = np.array([3.0, 1.0, 2.0, -1.5])
    assert abs(infimum(q) - (-1.5)) < 1e-12


def test_infimum_all_positive():
    q = np.array([0.5, 1.0, 2.0])
    assert abs(infimum(q) - 0.5) < 1e-12


def test_infimum_single():
    q = np.array([42.0])
    assert abs(infimum(q) - 42.0) < 1e-12


# ---------------------------------------------------------------------------
# implied_distribution
# ---------------------------------------------------------------------------


def test_implied_distribution_zero_q():
    """With q=0, the implied Radon–Nikodym derivative is 1 for each outcome."""
    n = 4
    q = np.zeros(n)
    probs = np.array([0.1, 0.4, 0.3, 0.2])
    b = 1.0
    result = implied_distribution(q, probs, b)
    # e^0 / E_P[e^0] = 1 / 1 = 1
    np.testing.assert_allclose(result, np.ones(n), atol=1e-10)


def test_implied_distribution_expectation_is_one():
    """E_P[dQ/dP] = 1 always."""
    q = np.array([1.0, 2.0, 0.5])
    probs = np.array([0.3, 0.4, 0.3])
    b = 1.0
    rn = implied_distribution(q, probs, b)
    assert abs(np.sum(probs * rn) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# implied_probabilities
# ---------------------------------------------------------------------------


def test_implied_probs_sum_to_one():
    """Implied probability measure Q must sum to 1."""
    q = np.array([0.2, -0.3, 0.5, 0.1])
    probs = np.array([0.25, 0.25, 0.25, 0.25])
    b = 2.0
    q_probs = implied_probabilities(q, probs, b)
    assert abs(np.sum(q_probs) - 1.0) < 1e-10


def test_implied_probs_all_positive():
    """All implied probabilities must be positive."""
    q = np.array([10.0, -10.0, 0.0])
    probs = np.array([0.3, 0.3, 0.4])
    b = 1.0
    q_probs = implied_probabilities(q, probs, b)
    assert np.all(q_probs > 0)


# ---------------------------------------------------------------------------
# compute_trade
# ---------------------------------------------------------------------------


def test_trade_valid_small():
    """A small trade should be valid for a user with balance=1."""
    q = np.zeros(3)
    q_t = np.zeros(3)
    delta_q = np.array([0.1, 0.0, -0.1])
    probs = np.array([1 / 3, 1 / 3, 1 / 3])
    b = 1.0
    balance = 1.0
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    assert result["valid"]
    assert "new_balance" in result
    assert result["new_balance"] < balance  # balance decreases


def test_trade_invalid_insufficient_balance():
    """A very expensive trade should fail with insufficient balance."""
    q = np.zeros(2)
    q_t = np.zeros(2)
    delta_q = np.array([100.0, -100.0])
    probs = np.array([0.5, 0.5])
    b = 1.0
    balance = 0.01
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    assert not result["valid"]
    assert "new_balance" not in result


def test_trade_balance_update():
    """B' = B - (delta_C - delta_inf)."""
    q = np.zeros(3)
    q_t = np.zeros(3)
    delta_q = np.array([0.3, -0.1, -0.2])
    probs = np.array([0.4, 0.3, 0.3])
    b = 1.0
    balance = 1.0
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    if result["valid"]:
        expected_new_balance = balance - (result["delta_c"] - result["delta_inf"])
        assert abs(result["new_balance"] - expected_new_balance) < 1e-10


def test_trade_state_update():
    """q' = q + delta_q and q_t' = q_t + delta_q after valid trade."""
    q = np.array([0.1, -0.1, 0.0])
    q_t = np.array([0.0, 0.2, -0.1])
    delta_q = np.array([0.05, 0.05, 0.05])
    probs = np.array([0.4, 0.3, 0.3])
    b = 1.0
    balance = 1.0
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    assert result["valid"]
    np.testing.assert_allclose(result["new_q"], (q + delta_q).tolist(), atol=1e-12)
    np.testing.assert_allclose(result["new_q_t"], (q_t + delta_q).tolist(), atol=1e-12)


def test_trade_delta_inf_short_collateral():
    """When shorting (creating negative positions), delta_inf adjusts collateral."""
    q = np.zeros(2)
    q_t = np.zeros(2)
    # Sell outcome 0, buy outcome 1 (q_t becomes negative at index 0)
    delta_q = np.array([-1.0, 0.5])
    probs = np.array([0.5, 0.5])
    b = 1.0
    balance = 2.0
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    # delta_inf should be negative (or zero) - we need collateral for short
    # min(0, inf(q_t + delta_q)) - min(0, inf(q_t)) = min(0,-1) - min(0,0) = -1 - 0 = -1
    assert abs(result["delta_inf"] - (-1.0)) < 1e-10


def test_trade_zero_delta_q():
    """Zero trade should have zero cost change."""
    q = np.array([1.0, -0.5, 0.3])
    q_t = np.array([0.1, 0.0, -0.2])
    delta_q = np.zeros(3)
    probs = np.array([0.3, 0.4, 0.3])
    b = 1.0
    balance = 1.0
    result = compute_trade(q, q_t, delta_q, balance, probs, b)
    assert abs(result["delta_c"]) < 1e-10
    assert abs(result["delta_inf"]) < 1e-10
    assert abs(result["required_collateral"]) < 1e-10
    assert result["valid"]
