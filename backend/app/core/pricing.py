"""Iranian rental financial conversion logic (Tabdil)."""

from typing import Optional


def calculate_effective_monthly_cost(deposit: int, rent: int, conversion_rate: float = 0.03) -> int:
    """C_eff = rent + (deposit * conversion_rate)."""
    return rent + int(deposit * conversion_rate)


def is_budget_compatible(
    deposit: int,
    rent: int,
    max_deposit: Optional[int],
    max_rent: Optional[int],
    tolerance: float = 0.15,
) -> bool:
    """Check whether a listing's effective cost fits within the user's budget cap
    plus a tolerance margin.

    If neither cap is set, always compatible. If only one of max_deposit/max_rent
    is set, the other is treated as 0 when computing the target ceiling (per the
    same C_target formula used elsewhere) -- this can make the ceiling tighter
    than a user might expect when they only specified one axis of their budget.
    """
    if max_deposit is None and max_rent is None:
        return True

    effective_cost = calculate_effective_monthly_cost(deposit, rent)
    target_cost = calculate_effective_monthly_cost(max_deposit or 0, max_rent or 0)
    return effective_cost <= target_cost * (1 + tolerance)
