import math

import pytest
import pytest_asyncio

from app.core import constants
from app.core.constants import BUDGET_CEILING_MULTIPLIER
from app.core.models import ExtractedSearchIntent, Listing
from app.core.pricing import calculate_effective_monthly_cost
from app.llm.client import OpenRouterClient
from app.search.scoring import (
    MarketBaselines,
    ScoredListing,
    amenity_utility,
    area_utility,
    commute_utility,
    metro_utility,
    compute_utility,
    cosine_similarity,
    default_weights,
    financial_utility,
    freshness_utility,
    hard_constraint_mask,
    pareto_frontier,
    rank_listings,
    resolve_tabdil,
    resolve_weights,
    soft_utility,
    elevator_penalty,
    structural_penalty,
    value_utility,
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


def test_hard_constraint_keeps_a_walk_up_when_a_lift_was_asked_for():
    # A missing lift is scored down by elevator_penalty, not pruned: a
    # fourth-floor walk-up is a compromise, not a different kind of home.
    listing = make_listing(floor=4, has_elevator=False)
    intent = make_intent(must_have_elevator=True)
    assert hard_constraint_mask(listing, intent) is True


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

    # Non-convertible on purpose: this test is about the ceiling itself. A
    # قابل تبدیل listing is measured at its converted split instead, and the
    # rounding involved in moving along the conversion line makes an exact
    # one-Toman boundary assertion meaningless there.
    just_over = make_listing(
        deposit_toman=0, rent_toman=int(c_target * BUDGET_CEILING_MULTIPLIER) + 1, can_convert=False
    )
    assert hard_constraint_mask(just_over, intent) is False

    at_boundary = make_listing(
        deposit_toman=0, rent_toman=int(c_target * BUDGET_CEILING_MULTIPLIER), can_convert=False
    )
    assert hard_constraint_mask(at_boundary, intent) is True


def test_hard_constraint_passes_with_no_intent_constraints():
    listing = make_listing()
    intent = make_intent()
    assert hard_constraint_mask(listing, intent) is True


# --- Commute utility ---


def test_metro_utility_at_sigmoid_midpoint_is_half():
    # T_walk == midpoint -> sigmoid == 0.5. Metro closeness is its own
    # criterion; the commute term is about the stated workplace alone.
    assert metro_utility(make_listing(metro_walk_mins=8.0)) == pytest.approx(0.5)


def test_commute_utility_without_workplace_is_neutral():
    assert commute_utility(make_listing(), make_intent()) == pytest.approx(1.0)


def test_commute_utility_with_workplace_close_by_scores_higher_than_far():
    close_listing = make_listing(lat=35.700, lon=51.400)
    far_listing = make_listing(lat=35.780, lon=51.550)
    intent = make_intent(workplace_lat=35.702, workplace_lon=51.402, max_commute_mins=30)

    assert commute_utility(close_listing, intent) > commute_utility(far_listing, intent)


# --- Financial utility ---


def test_financial_utility_no_budget_falls_back_to_the_market():
    """No stated budget is not "price does not matter": the corpus median
    stands in for the ceiling the user never typed."""
    market = MarketBaselines(city_monthly_cost=50_000_000.0)
    at_market = make_listing(deposit_toman=0, rent_toman=50_000_000, can_convert=False)
    cheap = make_listing(deposit_toman=0, rent_toman=20_000_000, can_convert=False)
    pricey = make_listing(deposit_toman=0, rent_toman=200_000_000, can_convert=False)

    assert financial_utility(at_market, make_intent(), market) == pytest.approx(0.5)
    assert financial_utility(cheap, make_intent(), market) > 0.5
    assert 0.0 < financial_utility(pricey, make_intent(), market) < 0.5


def test_financial_utility_without_a_corpus_is_neutral():
    assert financial_utility(make_listing(), make_intent(), MarketBaselines()) == 1.0


def test_financial_utility_at_the_cap_is_zero_point_eight():
    intent = make_intent(max_deposit=100_000_000, max_rent=10_000_000)
    c_target = calculate_effective_monthly_cost(100_000_000, 10_000_000)
    listing = make_listing(deposit_toman=100_000_000, rent_toman=c_target - int(100_000_000 * 0.03))
    assert financial_utility(listing, intent, MarketBaselines()) == pytest.approx(0.8, abs=1e-3)


def test_financial_utility_decays_exponentially_past_the_cap():
    intent = make_intent(max_deposit=0, max_rent=10_000_000, can_convert=False)
    c_target = calculate_effective_monthly_cost(0, 10_000_000)
    listing = make_listing(deposit_toman=0, rent_toman=c_target + 1_000_000, can_convert=False)

    ratio = (c_target + 1_000_000) / c_target
    expected = 0.8 * math.exp(-5.0 * (ratio - 1.0))
    assert financial_utility(listing, intent, MarketBaselines()) == pytest.approx(expected)


def test_financial_utility_rewards_being_well_under_budget():
    intent = make_intent(max_deposit=0, max_rent=20_000_000)
    cheap = make_listing(deposit_toman=0, rent_toman=5_000_000, can_convert=False)
    pricey = make_listing(deposit_toman=0, rent_toman=19_000_000, can_convert=False)
    market = MarketBaselines()
    assert financial_utility(cheap, intent, market) > financial_utility(pricey, intent, market)


# --- Value / area / amenity / freshness utilities ---


def test_value_utility_rewards_being_cheaper_than_the_neighborhood_median():
    baselines = MarketBaselines(per_neighborhood={"n1": 200_000.0}, city=200_000.0)
    bargain = make_listing(neighborhood_key="n1", deposit_toman=0, rent_toman=10_000_000, area_sqm=100)
    overpriced = make_listing(neighborhood_key="n1", deposit_toman=0, rent_toman=30_000_000, area_sqm=100)
    assert value_utility(bargain, baselines) > value_utility(overpriced, baselines)
    assert 0.0 <= value_utility(overpriced, baselines) <= 1.0


def test_area_utility_peaks_at_the_midpoint_of_a_stated_range():
    intent = make_intent(min_area_sqm=70, max_area_sqm=90)
    assert area_utility(make_listing(area_sqm=80), intent) == pytest.approx(1.0)
    assert area_utility(make_listing(area_sqm=95), intent) < 1.0


def test_area_utility_does_not_penalise_exceeding_a_bare_minimum():
    intent = make_intent(min_area_sqm=70)
    assert area_utility(make_listing(area_sqm=120), intent) == 1.0
    assert area_utility(make_listing(area_sqm=60), intent) < 1.0


def test_amenity_utility_is_the_weighted_sum():
    everything = make_listing(has_parking=True, has_elevator=True, has_storage=True, has_balcony=True)
    nothing = make_listing(has_parking=False, has_elevator=False, has_storage=False, has_balcony=False)
    assert amenity_utility(everything) == pytest.approx(1.0)
    assert amenity_utility(nothing) == pytest.approx(0.0)


def test_freshness_utility_favours_the_newer_building():
    assert freshness_utility(make_listing(building_age_years=1)) > freshness_utility(
        make_listing(building_age_years=25)
    )


def test_structural_penalty_scales_with_the_floor_of_a_walk_up():
    intent, weights = make_intent(), default_weights().normalized()

    def penalty(**overrides):
        return structural_penalty(make_listing(**overrides), intent, weights)

    # No lift, and the higher the floor the worse it gets -- but never a cliff.
    assert penalty(floor=2, has_elevator=False) > penalty(floor=4, has_elevator=False)
    assert penalty(floor=4, has_elevator=False) > penalty(floor=6, has_elevator=False)
    # A lift, or a floor that needs none, costs nothing at all.
    assert penalty(floor=4, has_elevator=True) == pytest.approx(1.0)
    assert penalty(floor=1, has_elevator=False) == pytest.approx(1.0)
    assert penalty(floor=-1, has_elevator=True) == pytest.approx(0.8)


def test_elevator_penalty_sharpens_when_a_lift_was_required():
    listing = make_listing(floor=4, has_elevator=False)
    weights = default_weights().normalized()
    assert elevator_penalty(listing, make_intent(must_have_elevator=True), weights) < elevator_penalty(
        listing, make_intent(), weights
    )


# --- Tabdil ---


def test_resolve_tabdil_buys_the_deposit_down_to_fit_the_user_cash():
    listing = make_listing(deposit_toman=500_000_000, rent_toman=5_000_000, can_convert=True)
    intent = make_intent(max_deposit=200_000_000)
    deposit, rent = resolve_tabdil(listing, intent)

    assert deposit <= 200_000_000
    assert rent > listing.rent_toman
    # Conversion happens along the rate line, so the total monthly cost is
    # unchanged -- only reachability moves.
    assert calculate_effective_monthly_cost(deposit, rent) == pytest.approx(
        calculate_effective_monthly_cost(listing.deposit_toman, listing.rent_toman), rel=0.01
    )


def test_resolve_tabdil_leaves_a_non_convertible_listing_alone():
    listing = make_listing(deposit_toman=500_000_000, rent_toman=5_000_000, can_convert=False)
    intent = make_intent(max_deposit=200_000_000)
    assert resolve_tabdil(listing, intent) == (500_000_000, 5_000_000)


# --- Weights ---


def test_reachability_dial_at_zero_drops_the_commute_criterion():
    weights = resolve_weights(make_intent(commute_importance=0.0, workplace_lat=35.7, workplace_lon=51.4))
    assert weights.commute == 0.0
    # The dropped share is redistributed, not lost.
    assert weights.total() == pytest.approx(1.0)


def test_reachability_dial_at_maximum_outweighs_the_default():
    at_max = resolve_weights(make_intent(commute_importance=1.0, workplace_lat=35.7, workplace_lon=51.4))
    assert at_max.commute > default_weights().commute


# --- Cosine similarity / semantic soft score ---


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_soft_utility_without_a_stated_preference_is_neutral():
    assert soft_utility(None, make_listing()) == 1.0


async def test_soft_utility_similar_text_scores_higher_than_unrelated(client):
    description = "واحد نوساز با نورگیر عالی، کوچه خلوت و سقف بلند"
    listing = make_listing(description=description)
    listing.embedding = await client.generate_embedding(description)

    close = await client.generate_embedding("نورگیر عالی و کوچه خلوت می‌خواهم")
    far = await client.generate_embedding("پارکینگ دوبل و استخر خصوصی در طبقه آخر")
    assert soft_utility(close, listing) > soft_utility(far, listing)


# --- compute_utility ---


def test_compute_utility_zero_when_hard_mask_fails():
    listing = make_listing(has_parking=False)
    intent = make_intent(must_have_parking=True)
    utility, breakdown = compute_utility(listing, intent, default_weights(), MarketBaselines())
    assert utility == 0.0
    assert breakdown == {}


def test_compute_utility_matches_the_weighted_sum_times_the_penalty():
    listing = make_listing(metro_walk_mins=8.0, building_age_years=1, floor=4, has_elevator=False)
    intent = make_intent()
    weights = default_weights()
    baselines = MarketBaselines(city=200_000.0)

    utility, breakdown = compute_utility(listing, intent, weights, baselines)
    expected = sum(getattr(weights, name) * value for name, value in breakdown.items())
    assert utility == pytest.approx(expected * structural_penalty(listing, intent, weights))


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


async def test_rank_listings_returns_one_ordered_list_with_trade_off_rationales(client, monkeypatch):
    """One list, best first, with the near miss further down explained.

    The head of that list is what a near miss is measured against, so the test
    shrinks it to a single entry rather than inventing sixty filler listings:
    what matters is that the comparison is against the top of the ranking and
    that the sentence goes to a listing below it.
    """
    monkeypatch.setattr(constants, "RANKING_HEAD_SIZE", 1)
    intent = make_intent(max_deposit=0, max_rent=10_000_000, workplace_lat=None, workplace_lon=None)

    best = make_listing(
        id="best",
        deposit_toman=0,
        rent_toman=10_000_000,
        metro_walk_mins=2.0,
        area_sqm=80,
        building_age_years=1,
    )
    # >=25% bigger area than the head, same metro-walk time, and a 10% overrun
    # on the stated rent -- the edge of TRADE_OFF_MAX_BUDGET_INCREASE, so the
    # nudge qualifies. The older building is what keeps it below the head:
    # the price alone no longer can, now that the overrun has to stay inside
    # the band for a rationale to be written at all.
    trade_off_listing = make_listing(
        id="tradeoff",
        deposit_toman=0,
        rent_toman=11_000_000,
        metro_walk_mins=2.0,
        area_sqm=105,
        building_age_years=20,
    )
    pruned_listing = make_listing(id="pruned", floor=5, has_elevator=False)

    intent_with_elevator = intent.model_copy(update={"must_have_elevator": True})
    # keep both scored listings elevator-compliant
    best = best.model_copy(update={"has_elevator": True, "floor": 1})
    trade_off_listing = trade_off_listing.model_copy(update={"has_elevator": True, "floor": 1})

    ranked = await rank_listings(
        client,
        [best, trade_off_listing, pruned_listing],
        intent_with_elevator,
    )

    assert [s.listing.id for s in ranked] == ["best", "tradeoff"]
    # Ordered by score, so the list itself carries the ranking -- there is no
    # second bucket to look in for the weaker match.
    assert ranked[0].utility_score >= ranked[1].utility_score

    tradeoff_result = ranked[1]
    assert tradeoff_result.trade_off_rationale is not None
    assert "متر" in tradeoff_result.trade_off_rationale
    # The overrun is stated against the *user's* budget, not against the
    # reference listing's price, and it is the figure the band admitted.
    assert "۱۰٪ بالاتر از بودجهٔ شماست" in tradeoff_result.trade_off_rationale
    # The head is the reference, not a card that needs explaining.
    assert ranked[0].trade_off_rationale is None

    # Past that band the nudge says nothing at all, rather than dropping the
    # budget clause and presenting what is left as a bargain.
    over_budget = await rank_listings(
        client,
        [best, trade_off_listing.model_copy(update={"rent_toman": 11_800_000}), pruned_listing],
        intent_with_elevator,
    )
    assert next(s for s in over_budget if s.listing.id == "tradeoff").trade_off_rationale is None
