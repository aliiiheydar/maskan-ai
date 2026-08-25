"""Multi-criteria utility scoring, tier stratification, and Pareto trade-off
discovery. Formulas per docs/ALGORITHMS.md SS2-4.
"""

import math
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np

from app.core import constants
from app.core.models import ExtractedSearchIntent, Listing
from app.core.pricing import calculate_effective_monthly_cost
from app.spatial.transit import estimate_commute_time


class EmbeddingClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    generate_embedding method -- lets tests pass a lightweight fake."""

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]: ...


def hard_constraint_mask(listing: Listing, intent: ExtractedSearchIntent) -> bool:
    """I_hard(L|U): elevator, parking, budget ceiling, area (docs/ALGORITHMS.md SS3.1).

    Neighborhood/room filters are query-level pre-filters, not part of this
    formula, so they are intentionally not enforced here.
    """
    if intent.must_have_elevator and listing.floor > 1 and not listing.has_elevator:
        return False

    if intent.must_have_parking and not listing.has_parking:
        return False

    if intent.min_area_sqm is not None and listing.area_sqm < intent.min_area_sqm:
        return False

    if intent.max_deposit is not None or intent.max_rent is not None:
        c_target = calculate_effective_monthly_cost(intent.max_deposit or 0, intent.max_rent or 0)
        c_eff = calculate_effective_monthly_cost(listing.deposit_toman, listing.rent_toman)
        if c_eff > constants.BUDGET_CEILING_MULTIPLIER * c_target:
            return False

    return True


def commute_score(listing: Listing, intent: ExtractedSearchIntent) -> float:
    """S_commute(L,U) = 0.5*S_metro_walk + 0.5*S_workplace_commute.

    If the user gave no workplace, S_workplace_commute defaults to 1.0
    (no commute constraint stated -> treated as fully satisfied).
    """
    s_metro_walk = 1.0 / (
        1.0
        + math.exp(constants.METRO_WALK_SIGMOID_K * (listing.metro_walk_mins - constants.METRO_WALK_SIGMOID_MIDPOINT_MINS))
    )

    if intent.workplace_lat is not None and intent.workplace_lon is not None:
        commute_mins = estimate_commute_time(
            listing.lat, listing.lon, intent.workplace_lat, intent.workplace_lon, mode="transit"
        )
        s_workplace_commute = 1.0 / (
            1.0 + math.exp(constants.WORKPLACE_COMMUTE_SIGMOID_K * (commute_mins - intent.max_commute_mins))
        )
    else:
        s_workplace_commute = 1.0

    return 0.5 * s_metro_walk + 0.5 * s_workplace_commute


def price_score(listing: Listing, intent: ExtractedSearchIntent) -> float:
    """S_price(L,U) = exp(-(deltaC / (0.15*C_target + eps))^2).

    If the user gave no budget cap at all, there is no price preference to
    score against, so this returns 1.0 (fully satisfied) rather than the
    near-zero score the raw formula would produce against a C_target of 0.
    """
    if intent.max_deposit is None and intent.max_rent is None:
        return 1.0

    c_target = calculate_effective_monthly_cost(intent.max_deposit or 0, intent.max_rent or 0)
    c_eff = calculate_effective_monthly_cost(listing.deposit_toman, listing.rent_toman)
    delta_c = max(0, c_eff - c_target)
    denom = constants.PRICE_SCORE_TOLERANCE * c_target + constants.PRICE_SCORE_EPSILON
    return math.exp(-((delta_c / denom) ** 2))


def quality_score(listing: Listing) -> float:
    """S_quality(L): building freshness + amenity heuristic.

    docs/ALGORITHMS.md names this sub-score (w_q = 0.10) but does not define
    its formula, so this is an MVP heuristic pending a documented spec.
    """
    age_component = math.exp(-listing.building_age_years / 15.0)
    amenity_component = 0.5 * float(listing.has_balcony) + 0.5 * float(listing.has_storage)
    return max(0.0, min(1.0, 0.7 * age_component + 0.3 * amenity_component))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    norm_a, norm_b = np.linalg.norm(vec_a), np.linalg.norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


async def semantic_soft_score(client: EmbeddingClient, intent: ExtractedSearchIntent, listing: Listing) -> float:
    """S_soft(L,U): cosine similarity between the soft-preference summary
    embedding and the listing description embedding. 1.0 (neutral) if the
    user stated no soft preferences."""
    if not intent.soft_preference_summary:
        return 1.0

    query_embedding = await client.generate_embedding(intent.soft_preference_summary)
    listing_embedding = await client.generate_embedding(listing.description)
    similarity = cosine_similarity(query_embedding, listing_embedding)
    return max(0.0, min(1.0, similarity))


async def compute_utility(client: EmbeddingClient, listing: Listing, intent: ExtractedSearchIntent) -> float:
    """Utility(L|U) per docs/ALGORITHMS.md SS2. 0.0 if any hard constraint fails."""
    if not hard_constraint_mask(listing, intent):
        return 0.0

    s_commute = commute_score(listing, intent)
    s_price = price_score(listing, intent)
    s_soft = await semantic_soft_score(client, intent, listing)
    s_quality = quality_score(listing)

    return (
        constants.UTILITY_WEIGHT_COMMUTE * s_commute
        + constants.UTILITY_WEIGHT_PRICE * s_price
        + constants.UTILITY_WEIGHT_SOFT * s_soft
        + constants.UTILITY_WEIGHT_QUALITY * s_quality
    )


@dataclass
class ScoredListing:
    listing: Listing
    utility_score: float
    tier: int = 0
    trade_off_rationale: Optional[str] = None


def _dominates(a: Listing, b: Listing) -> bool:
    """True if listing a Pareto-dominates listing b on (cost, metro walk, area)."""
    a_cost = calculate_effective_monthly_cost(a.deposit_toman, a.rent_toman)
    b_cost = calculate_effective_monthly_cost(b.deposit_toman, b.rent_toman)

    at_least_as_good = a_cost <= b_cost and a.metro_walk_mins <= b.metro_walk_mins and a.area_sqm >= b.area_sqm
    strictly_better = a_cost < b_cost or a.metro_walk_mins < b.metro_walk_mins or a.area_sqm > b.area_sqm
    return at_least_as_good and strictly_better


def pareto_frontier(scored: list[ScoredListing]) -> list[ScoredListing]:
    """Listings not strictly dominated by any other listing in the set."""
    return [
        candidate
        for candidate in scored
        if not any(_dominates(other.listing, candidate.listing) for other in scored if other is not candidate)
    ]


def _trade_off_rationale(listing: Listing, reference: Listing, intent: ExtractedSearchIntent) -> Optional[str]:
    """Persian trade-off nudge per docs/ALGORITHMS.md SS4: qualifies when the
    listing is >=25% larger than the Tier 1 reference AND either the budget
    increase is <=10% or the extra metro-walk time is <=7 minutes."""
    if reference.area_sqm <= 0:
        return None

    area_increase = (listing.area_sqm - reference.area_sqm) / reference.area_sqm
    reference_cost = calculate_effective_monthly_cost(reference.deposit_toman, reference.rent_toman)
    listing_cost = calculate_effective_monthly_cost(listing.deposit_toman, listing.rent_toman)
    budget_increase = (listing_cost - reference_cost) / reference_cost if reference_cost > 0 else 0.0
    commute_increase = listing.metro_walk_mins - reference.metro_walk_mins

    qualifies = area_increase >= constants.TRADE_OFF_MIN_AREA_INCREASE and (
        budget_increase <= constants.TRADE_OFF_MAX_BUDGET_INCREASE
        or commute_increase <= constants.TRADE_OFF_MAX_COMMUTE_INCREASE_MINS
    )
    if not qualifies:
        return None

    budget_clause = f"{round(budget_increase * 100)}٪ بالاتر از بودجه است" if budget_increase > 0 else "در محدوده بودجه است"
    area_clause = f"{listing.area_sqm - reference.area_sqm} متر متراژ بزرگتر"
    commute_clause = (
        f"{round(commute_increase)} دقیقه پیاده‌روی بیشتر تا مترو" if commute_increase > 0 else "دسترسی مشابه یا بهتر به مترو"
    )
    return f"این مورد {budget_clause} اما {area_clause} و {commute_clause} دارد."


async def rank_listings(
    client: EmbeddingClient, listings: list[Listing], intent: ExtractedSearchIntent
) -> tuple[list[ScoredListing], list[ScoredListing]]:
    """Score, then stratify into (tier_1_results, tier_2_results) per
    docs/ALGORITHMS.md SS4. Tier 1 is the Pareto-optimal set among
    Utility>=0.70 listings; anything dominated out of Tier 1 falls back into
    Tier 2 alongside the 0.45<=Utility<0.70 band and gets a trade_off_rationale
    relative to the top Tier 1 pick.
    """
    scored: list[ScoredListing] = []
    for listing in listings:
        utility = await compute_utility(client, listing, intent)
        scored.append(ScoredListing(listing=listing, utility_score=utility))

    tier1_candidates = [s for s in scored if s.utility_score >= constants.TIER_1_UTILITY_THRESHOLD]
    tier1 = sorted(pareto_frontier(tier1_candidates), key=lambda s: s.utility_score, reverse=True)
    tier1_ids = {id(s) for s in tier1}

    tier2_pool = [
        s for s in scored if constants.TIER_2_UTILITY_THRESHOLD <= s.utility_score < constants.TIER_1_UTILITY_THRESHOLD
    ]
    tier2_pool += [s for s in tier1_candidates if id(s) not in tier1_ids]
    tier2 = sorted(tier2_pool, key=lambda s: s.utility_score, reverse=True)

    for scored_listing in tier1:
        scored_listing.tier = 1
    for scored_listing in tier2:
        scored_listing.tier = 2

    if tier1:
        reference = tier1[0].listing
        for scored_listing in tier2:
            scored_listing.trade_off_rationale = _trade_off_rationale(scored_listing.listing, reference, intent)

    return tier1, tier2
