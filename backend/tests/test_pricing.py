import pytest

from app.core.pricing import calculate_effective_monthly_cost, is_budget_compatible


@pytest.mark.parametrize(
    "deposit, rent, expected",
    [
        (100_000_000, 0, 3_000_000),
        (0, 15_000_000, 15_000_000),
        (200_000_000, 10_000_000, 16_000_000),
        (500_000_000, 25_000_000, 40_000_000),
    ],
)
def test_calculate_effective_monthly_cost_matrix(deposit, rent, expected):
    assert calculate_effective_monthly_cost(deposit, rent) == expected


def test_is_budget_compatible_no_caps_always_true():
    assert is_budget_compatible(deposit=999_999_999, rent=999_999_999, max_deposit=None, max_rent=None) is True


def test_is_budget_compatible_at_tolerance_boundary():
    # target_cost = 20,000,000; effective_cost at exactly 1.15x target should pass.
    max_deposit, max_rent = 0, 20_000_000
    target_cost = calculate_effective_monthly_cost(max_deposit, max_rent)
    boundary_rent = int(target_cost * 1.15)
    assert is_budget_compatible(0, boundary_rent, max_deposit, max_rent) is True


def test_is_budget_compatible_just_over_tolerance():
    max_deposit, max_rent = 0, 20_000_000
    target_cost = calculate_effective_monthly_cost(max_deposit, max_rent)
    over_rent = int(target_cost * 1.15) + 1_000_000
    assert is_budget_compatible(0, over_rent, max_deposit, max_rent) is False


def test_is_budget_compatible_only_max_rent_set_treats_deposit_cap_as_zero():
    # Only max_rent is specified, so the target ceiling collapses to max_rent
    # alone (deposit cap treated as 0) -- documents the None-> 0 semantic.
    max_rent = 10_000_000
    # A listing with zero deposit and rent within max_rent passes.
    assert is_budget_compatible(deposit=0, rent=10_000_000, max_deposit=None, max_rent=max_rent) is True
    # A listing that relies on a large deposit (converted to cost) exceeds the
    # implicit zero-deposit ceiling once tolerance is exhausted.
    assert is_budget_compatible(deposit=500_000_000, rent=0, max_deposit=None, max_rent=max_rent) is False
