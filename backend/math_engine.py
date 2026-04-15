"""
Mathematical engine for Probabilize.

Implements the convex cost function market maker based on:
  C(q) = b * log(E_P[e^(q/b)])

with numerical stability via the log-sum-exp trick.
"""

import numpy as np
from typing import List


def log_sum_exp(x: np.ndarray, weights: np.ndarray) -> float:
    """
    Numerically stable computation of log(sum_i weights_i * exp(x_i)).

    Uses the identity:
        log(sum_i w_i * exp(x_i)) = M + log(sum_i w_i * exp(x_i - M))
    where M = max(x_i).
    """
    max_x = float(np.max(x))
    return max_x + float(np.log(np.sum(weights * np.exp(x - max_x))))


def log_partition(q: np.ndarray, probs: np.ndarray, b: float) -> float:
    """
    Compute log(E_P[e^(q/b)]) with numerical stability.
    """
    return log_sum_exp(q / b, probs)


def cost(q: np.ndarray, probs: np.ndarray, b: float) -> float:
    """
    Convex cost function: C(q) = b * log(E_P[e^(q/b)]).

    Args:
        q: Current claim state, shape (n,)
        probs: Probability measure P over Omega, shape (n,), sums to 1
        b: Liquidity parameter, b > 0

    Returns:
        Scalar cost value.
    """
    return b * log_partition(q, probs, b)


def infimum(q: np.ndarray) -> float:
    """
    Infimum (minimum) of q over Omega.
    """
    return float(np.min(q))


def implied_distribution(q: np.ndarray, probs: np.ndarray, b: float) -> np.ndarray:
    """
    Compute the implied Radon-Nikodym derivative dQ/dP:
        (dQ/dP)(omega) = e^(q(omega)/b) / E_P[e^(q/b)]

    The implied probability for outcome i is:
        Q(omega_i) = P(omega_i) * e^(q_i/b) / E_P[e^(q/b)]

    Returns:
        Array of shape (n,) with the Radon-Nikodym derivative values.
        The weighted average sum_i p_i * result_i equals 1.
    """
    x = q / b
    max_x = float(np.max(x))
    exp_x = np.exp(x - max_x)
    denom = float(np.sum(probs * exp_x))
    return exp_x / denom


def implied_probabilities(q: np.ndarray, probs: np.ndarray, b: float) -> np.ndarray:
    """
    Compute the implied probability measure Q over Omega:
        Q(omega_i) = P(omega_i) * e^(q_i/b) / E_P[e^(q/b)]

    Returns:
        Array of shape (n,) that sums to 1.
    """
    rn = implied_distribution(q, probs, b)
    return probs * rn


def compute_trade(
    q: np.ndarray,
    q_t: np.ndarray,
    delta_q: np.ndarray,
    balance: float,
    probs: np.ndarray,
    b: float,
) -> dict:
    """
    Compute trade validation and state updates.

    Validation rule:
        delta_C = C(q + delta_q) - C(q)
        delta_inf = min(0, inf(q_t + delta_q)) - min(0, inf(q_t))
        valid iff balance >= delta_C - delta_inf

    Args:
        q: Current market claim state, shape (n,)
        q_t: Taker's current position, shape (n,)
        delta_q: Taker's proposed position change, shape (n,)
        balance: Taker's current balance
        probs: Probability measure P, shape (n,)
        b: Liquidity parameter

    Returns:
        Dict with trade details and updated state (if valid).
    """
    q_new = q + delta_q
    q_t_new = q_t + delta_q

    current_cost = cost(q, probs, b)
    new_cost = cost(q_new, probs, b)

    delta_c = new_cost - current_cost
    delta_inf = min(0.0, infimum(q_t_new)) - min(0.0, infimum(q_t))
    required_collateral = delta_c - delta_inf
    valid = balance >= required_collateral

    result = {
        "valid": valid,
        "delta_c": float(delta_c),
        "delta_inf": float(delta_inf),
        "required_collateral": float(required_collateral),
        "current_cost": float(current_cost),
        "new_cost": float(new_cost),
        "log_partition_before": float(log_partition(q, probs, b)),
        "log_partition_after": float(log_partition(q_new, probs, b)),
    }

    if valid:
        result["new_balance"] = float(balance - required_collateral)
        result["new_q"] = q_new.tolist()
        result["new_q_t"] = q_t_new.tolist()

    return result
