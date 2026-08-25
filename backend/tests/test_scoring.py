import math

import pytest
import pytest_asyncio

from app.core.constants import BUDGET_CEILING_MULTIPLIER
from app.core.models import ExtractedSearchIntent, Listing
from app.core.pricing import calculate_effective_monthly_cost
from app.llm.client import OpenRouterClient
from app.search.scoring import (
    ScoredListing,
    commute_score,
    compute_utility,
    cosine_similarity,
    hard_constraint_mask,
    pareto_frontier,
    price_score,
    quality_score,
    rank_listings,
    semantic_soft_score,
)


def make_listing(**overrides) -> Listing:
    defaults = dict(
        id="teh-1",
        title="آپارتمان تست",
        description="واحد نوساز با نورگیر عالی و کوچه خلوت",
        neighborhood="یوسف‌آباد",
        deposit_toman=100_000_000,
        rent_toman=10_000_000,
        effective_monthly_cost=13_000_000,
        area_sqm=80,
        rooms=2,
        floor=2,
        has_elevator=True,
        has_parking=True,
        has_balcony=True,
        has_storage=True,
        building_age_years=2,
        lat=35.72,
        lon=51.40,
        h3_index="8829a1c8a3fffff",
        nearest_metro_id="metro-1-01",
        nearest_metro_name="تجریش",
        dist_to_metro_meters=400.0,
        metro_walk_mins=5.0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def make_intent(**overrides) -> ExtractedSearchIntent:
    return ExtractedSearchIntent(**overrides)


@pytest_asyncio.fixture
async def client():
    c = OpenRouterClient()
    yield c
    await c.close()


# --- Hard constraint mask (docs/TESTING_GUIDE.md SS2.2) ---


def test_hard_constraint_elevator_required_and_missing_prunes():
    listing = make_listing(floor=4, has_elevator=False)
    intent = make_intent(must_have_elevator=True)
    assert hard_constraint_mask(listing, intent) is False


def test_hard_constraint_ground_floor_not_pruned_without_elevator():
    listing = make_listing(floor=0, has_elevator=False)
    intent = make_intent(must_have_elevator=True)
    assert hard_constraint_mask(listing, intent) is True


def test_hard_constraint_parking_required_and_missing_prunes():
    listing = make_listing(has_parking=False)
    intent = make_intent(must_have_parking=True)
    assert hard_constraint_mask(listing, intent) is False


def test_hard_constraint_area_below_minimum_prunes():
    listing = make_listing(area_sqm=50)
    intent = make_intent(min_area_sqm=70)
    assert hard_constraint_mask(listing, intent) is False


def test_hard_constraint_budget_ceiling_pruned_above_multiplier():
    # docs/ALGORITHMS.md SS3.1 states 1.20x C_target for the hard prune (the
    # figure implemented here); docs/TESTING_GUIDE.md SS2.2 states a stale
    # 1.25x for its example -- resolved in favor of ALGORITHMS.md per explicit
    # user decision.
    intent = make_intent(max_deposit=0, max_rent=10_000_000)
    c_target = calculate_effective_monthly_cost(0, 10_000_000)

    just_over = make_listing(deposit_toman=0, rent_toman=int(c_target * BUDGET_CEILING_MULTIPLIER) + 1)
    assert hard_constraint_mask(just_over, intent) is False

    at_boundary = make_listing(deposit_toman=0, rent_toman=int(c_target * BUDGET_CEILING_MULTIPLIER))
    assert hard_constraint_mask(at_boundary, intent) is True


def test_hard_constraint_passes_with_no_intent_constraints():
    listing = make_listing()
    intent = make_intent()
    assert hard_constraint_mask(listing, intent) is True


# --- Commute score ---


def test_commute_score_no_workplace_uses_metro_walk_only():
    listing = make_listing(metro_walk_mins=8.0)
    intent = make_intent()
    score = commute_score(listing, intent)
    # T_walk == midpoint -> sigmoid == 0.5; no workplace -> S_workplace defaults to 1.0
    assert score == pytest.approx(0.5 * 0.5 + 0.5 * 1.0)


def test_commute_score_with_workplace_close_by_scores_higher_than_far():
    close_listing = make_listing(lat=35.700, lon=51.400)
    far_listing = make_listing(lat=35.780, lon=51.550)
    intent = make_intent(workplace_lat=35.702, workplace_lon=51.402, max_commute_mins=30)

    assert commute_score(close_listing, intent) > commute_score(far_listing, intent)


# --- Price score ---


def test_price_score_no_budget_returns_neutral():
    listing = make_listing()
    intent = make_intent()
    assert price_score(listing, intent) == 1.0


def test_price_score_at_target_is_one():
    intent = make_intent(max_deposit=100_000_000, max_rent=10_000_000)
    c_target = calculate_effective_monthly_cost(100_000_000, 10_000_000)
    listing = make_listing(deposit_toman=100_000_000, rent_toman=c_target - int(100_000_000 * 0.03))
    assert price_score(listing, intent) == pytest.approx(1.0)


def test_price_score_decays_with_overage():
    intent = make_intent(max_deposit=0, max_rent=10_000_000)
    c_target = calculate_effective_monthly_cost(0, 10_000_000)
    listing = make_listing(deposit_toman=0, rent_toman=c_target + 3_000_000)

    delta_c = 3_000_000
    expected = math.exp(-((delta_c / (0.15 * c_target + 1.0)) ** 2))
    assert price_score(listing, intent) == pytest.approx(expected)


# --- Quality score ---


def test_quality_score_new_building_with_amenities_beats_old_bare_one():
    fresh = make_listing(building_age_years=1, has_balcony=True, has_storage=True)
    old = make_listing(building_age_years=25, has_balcony=False, has_storage=False)
    assert quality_score(fresh) > quality_score(old)
    assert 0.0 <= quality_score(fresh) <= 1.0
    assert 0.0 <= quality_score(old) <= 1.0


# --- Cosine similarity / semantic soft score ---


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


async def test_semantic_soft_score_no_preference_returns_neutral(client):
    listing = make_listing()
    intent = make_intent(soft_preference_summary="")
    assert await semantic_soft_score(client, intent, listing) == 1.0


async def test_semantic_soft_score_similar_text_scores_higher_than_unrelated(client):
    listing = make_listing(description="واحد نوساز با نورگیر عالی، کوچه خلوت و سقف بلند")
    close_intent = make_intent(soft_preference_summary="نورگیر عالی و کوچه خلوت می‌خواهم")
    far_intent = make_intent(soft_preference_summary="پارکینگ دوبل و استخر خصوصی در طبقه آخر")

    close_score = await semantic_soft_score(client, close_intent, listing)
    far_score = await semantic_soft_score(client, far_intent, listing)
    assert close_score > far_score


# --- compute_utility ---


async def test_compute_utility_zero_when_hard_mask_fails(client):
    listing = make_listing(floor=4, has_elevator=False)
    intent = make_intent(must_have_elevator=True)
    assert await compute_utility(client, listing, intent) == 0.0


async def test_compute_utility_matches_weighted_sum_with_neutral_components(client):
    listing = make_listing(metro_walk_mins=8.0, building_age_years=1, has_balcony=True, has_storage=True)
    intent = make_intent()  # no budget, no workplace, no soft preferences -> price/soft neutral

    utility = await compute_utility(client, listing, intent)
    expected = (
        0.35 * commute_score(listing, intent)
        + 0.35 * price_score(listing, intent)
        + 0.20 * 1.0
        + 0.10 * quality_score(listing)
    )
    assert utility == pytest.approx(expected)


# --- Pareto frontier ---


def test_pareto_frontier_removes_dominated_listing():
    cheaper_closer_bigger = ScoredListing(
        listing=make_listing(id="a", deposit_toman=0, rent_toman=10_000_000, metro_walk_mins=5.0, area_sqm=90),
        utility_score=0.8,
    )
    dominated = ScoredListing(
        listing=make_listing(id="b", deposit_toman=0, rent_toman=12_000_000, metro_walk_mins=8.0, area_sqm=80),
        utility_score=0.75,
    )
    frontier = pareto_frontier([cheaper_closer_bigger, dominated])
    assert frontier == [cheaper_closer_bigger]


# --- rank_listings ---


async def test_rank_listings_splits_tiers_and_attaches_trade_off_rationale(client):
    intent = make_intent(max_deposit=0, max_rent=10_000_000, workplace_lat=None, workplace_lon=None)

    tier1_listing = make_listing(
        id="tier1",
        deposit_toman=0,
        rent_toman=10_000_000,
        metro_walk_mins=2.0,
        area_sqm=80,
        building_age_years=1,
    )
    # >=25% bigger area than tier1, same metro-walk time (qualifies via the
    # commute leg of the OR even though its 18% budget overage alone would not),
    # and its higher price score pulls utility below the 0.70 tier-1 cutoff.
    trade_off_listing = make_listing(
        id="tradeoff",
        deposit_toman=0,
        rent_toman=11_800_000,
        metro_walk_mins=2.0,
        area_sqm=105,
        building_age_years=1,
    )
    pruned_listing = make_listing(id="pruned", floor=5, has_elevator=False)

    intent_with_elevator = intent.model_copy(update={"must_have_elevator": True})
    # keep tier1/trade_off listings elevator-compliant
    tier1_listing = tier1_listing.model_copy(update={"has_elevator": True, "floor": 1})
    trade_off_listing = trade_off_listing.model_copy(update={"has_elevator": True, "floor": 1})

    tier1, tier2 = await rank_listings(
        client, [tier1_listing, trade_off_listing, pruned_listing], intent_with_elevator
    )

    assert [s.listing.id for s in tier1] == ["tier1"]
    assert any(s.listing.id == "tradeoff" for s in tier2)
    assert all(s.listing.id != "pruned" for s in tier1 + tier2)

    tradeoff_result = next(s for s in tier2 if s.listing.id == "tradeoff")
    assert tradeoff_result.trade_off_rationale is not None
    assert "متر" in tradeoff_result.trade_off_rationale
