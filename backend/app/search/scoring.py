"""Multi-Attribute Utility Theory ranking engine.

Implements the two-stage funnel from "architectural suggestion.md":

  Stage 1 -- elastic candidate retrieval. Hard requirements (search area,
  mandated amenities, رهن کامل) are enforced exactly; numeric limits are
  enforced at the edge of a confidence band instead of at the stated figure,
  because someone who typed "at least 80 متر" does not want a 78-متر flat
  hidden from them.

  Stage 2 -- fine-grained utility scoring. Each surviving listing gets
  S_total = (sum_k w_k * U_k) * prod(penalties), with the sub-utilities
  defined in SS5.1 of that document: financial fit, value-for-money against
  the listing's own neighborhood, area fit, amenities, reachability,
  building freshness, and semantic match with the described qualities.

Two design points are worth stating because they are easy to undo by accident:

  * Tabdil (تبدیل) conversion is cost-neutral. TMC = rent + deposit*r is
    invariant under converting one into the other at rate r, so conversion
    never changes how *expensive* a listing is -- it changes whether the
    listing is *reachable* for a user with a particular amount of cash. It is
    therefore applied in the feasibility check, not in the price score.

  * Tier membership follows from the score alone, so the tier a listing is
    shown in always agrees with the match percentage printed next to it.
"""

import math
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import median
from typing import Callable, Iterable, Mapping, Optional, Protocol

import numpy as np

from app.core import constants, neighborhood_quality
from app.core.models import CriteriaWeights, ExtractedSearchIntent, Listing
from app.core.pricing import calculate_effective_monthly_cost
from app.spatial import neighborhoods
from app.spatial.transit import estimate_commute_time


class EmbeddingClient(Protocol):
    """Structural type for anything with an OpenRouterClient-shaped
    generate_embedding method -- lets tests pass a lightweight fake."""

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> list[float]: ...


# --------------------------------------------------------------------------
# Market baselines
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketBaselines:
    """Median total monthly cost per square metre, per neighborhood.

    Precomputed once when the repository is seeded rather than derived per
    request ("architectural suggestion.md" SS7.2): U_value needs a baseline for
    every candidate, and recomputing a median over the whole corpus inside the
    scoring loop is the difference between a 5 ms and a 5 s search.
    """

    per_neighborhood: Mapping[str, float] = field(default_factory=dict)
    city: float = 0.0
    # Memo for the sub-utilities that depend only on the listing and on this
    # baseline set -- never on what the user asked for. Filled lazily by
    # _static_utilities and keyed by listing id. It lives here, rather than in
    # a module-level dict, so its lifetime is exactly the corpus it describes:
    # a new corpus brings new baselines and therefore an empty memo, and there
    # is no way for one to be read against the other.
    _static: dict = field(default_factory=dict, repr=False, compare=False)

    def for_listing(self, listing: Listing) -> float:
        """The comparison price for this listing: its own neighborhood's
        median where we have one, the city median otherwise."""
        if listing.neighborhood_key:
            local = self.per_neighborhood.get(listing.neighborhood_key)
            if local:
                return local
        return self.city

    @classmethod
    def from_listings(cls, listings: Iterable[Listing]) -> "MarketBaselines":
        samples: dict[str, list[float]] = {}
        everything: list[float] = []
        for listing in listings:
            if listing.area_sqm <= 0:
                continue
            per_sqm = total_monthly_cost(listing.deposit_toman, listing.rent_toman) / listing.area_sqm
            everything.append(per_sqm)
            if listing.neighborhood_key:
                samples.setdefault(listing.neighborhood_key, []).append(per_sqm)
        return cls(
            # A median over two or three listings is noise, not a market rate;
            # those neighborhoods fall back to the city figure.
            per_neighborhood={key: median(values) for key, values in samples.items() if len(values) >= 5},
            city=median(everything) if everything else 0.0,
        )


# --------------------------------------------------------------------------
# Financial mechanics (Tabdil)
# --------------------------------------------------------------------------


def total_monthly_cost(deposit: int, rent: int) -> int:
    """TMC = R + D*r -- deposit and rent unified into one comparable figure."""
    return calculate_effective_monthly_cost(deposit, rent)


def full_deposit_equivalent(deposit: int, rent: int) -> int:
    """FDE = D + R/r -- the same listing expressed as رهن کامل."""
    return int(deposit + rent / constants.TABDIL_RATE)


def tabdil_band(listing: Listing) -> tuple[int, int]:
    """(min deposit, max deposit) the advertiser will accept.

    A non-convertible listing is a single point. A convertible one runs up to
    the advertised ceiling -- or, when none was published, up to full رهن --
    and down to a fraction of the full-deposit equivalent.
    """
    fde = full_deposit_equivalent(listing.deposit_toman, listing.rent_toman)
    if not listing.can_convert:
        return listing.deposit_toman, listing.deposit_toman
    upper = listing.convertible_deposit_max_toman or fde
    lower = int(constants.TABDIL_MIN_DEPOSIT_FRACTION * fde)
    upper = max(upper, listing.deposit_toman)
    lower = min(lower, listing.deposit_toman)
    return lower, upper


def _cap(value: Optional[int]) -> Optional[int]:
    """A stated ceiling, or None.

    A zero cap is treated as "not stated" rather than as a literal ceiling of
    zero: callers use `max_deposit=0` to mean "I only gave you a rent budget",
    and reading it literally would prune every listing in the city.
    """
    return value if value else None


def resolve_tabdil(listing: Listing, intent: ExtractedSearchIntent) -> tuple[int, int]:
    """The (deposit, rent) point on the listing's conversion line that best
    fits this user, per "architectural suggestion.md" SS4.2.

    A cash-constrained user is pushed toward the low-deposit end to protect
    their liquidity; an income-constrained one toward رهن کامل to minimise
    monthly outgoings. Because the move happens along the conversion line, the
    total monthly cost is identical at every point -- only feasibility moves.
    """
    lower, upper = tabdil_band(listing)
    if lower == upper:
        return listing.deposit_toman, listing.rent_toman

    max_deposit = _cap(intent.max_deposit)
    if max_deposit is not None and listing.deposit_toman > max_deposit:
        # Cash-constrained: buy the deposit down as far as the advertiser's
        # band allows, toward what the user actually has.
        target = max(lower, min(upper, max_deposit))
    elif intent.financial_persona == "prefer_higher_deposit":
        target = upper
    elif intent.financial_persona == "prefer_higher_rent":
        target = lower
    else:
        # Nothing the user said calls for a conversion, so the advertised
        # split stands. In particular we never buy the rent down on our own
        # just because a rent ceiling is tight: that would silently assume the
        # user has unlimited cash, and would let any convertible listing meet
        # any rent budget by moving the whole cost into the deposit.
        return listing.deposit_toman, listing.rent_toman

    fde = full_deposit_equivalent(listing.deposit_toman, listing.rent_toman)
    rent = max(0, int((fde - target) * constants.TABDIL_RATE))
    return int(target), rent


def user_target_cost(intent: ExtractedSearchIntent) -> Optional[int]:
    """TMC of the budget the user stated, or None.

    Deliberately requires *both* axes. Someone who fills in only "ودیعه تا ۱۵۰"
    has said nothing about what they can pay monthly, and folding the missing
    axis in as a zero turns that into a 4.5m/month ceiling that prunes almost
    the whole city -- a filter the user never asked for. With one axis stated,
    that axis is enforced on its own (see hard_constraint_mask) and scored on
    its own (see financial_utility).
    """
    max_deposit, max_rent = _cap(intent.max_deposit), _cap(intent.max_rent)
    if max_deposit is None or max_rent is None:
        return None
    return total_monthly_cost(max_deposit, max_rent)


def _budget_ratio(listing: Listing, intent: ExtractedSearchIntent) -> Optional[float]:
    """How far the listing sits against whichever budget the user stated:
    both axes -> the ratio of total monthly costs; one axis -> the ratio on
    that axis alone, measured after any تبدیل."""
    deposit, rent = resolve_tabdil(listing, intent)
    target = user_target_cost(intent)
    if target is not None:
        return total_monthly_cost(deposit, rent) / target if target > 0 else None

    max_deposit, max_rent = _cap(intent.max_deposit), _cap(intent.max_rent)
    if max_rent is not None:
        return rent / max_rent
    if max_deposit is not None:
        return deposit / max_deposit
    return None


# --------------------------------------------------------------------------
# Stage 1: elastic candidate retrieval
# --------------------------------------------------------------------------


def _area_band(intent: ExtractedSearchIntent) -> tuple[Optional[float], Optional[float]]:
    """(admitted_min, admitted_max) square metres: the stated limits widened
    by delta_A."""
    low = intent.min_area_sqm * (1 - constants.AREA_CONFIDENCE_BAND) if intent.min_area_sqm is not None else None
    high = intent.max_area_sqm * (1 + constants.AREA_CONFIDENCE_BAND) if intent.max_area_sqm is not None else None
    return low, high


def hard_constraint_mask(listing: Listing, intent: ExtractedSearchIntent) -> bool:
    """I_hard(L|U): the requirements that admit no near-miss.

    Booleans the user mandated, the search area they drew, and the deal shape
    they asked for (رهن کامل, قابل تبدیل) are absolute. Numbers are enforced at
    the edge of their confidence band, and how far into that margin a listing
    sits is then priced into its utility by the sub-scores below.

    The room filter stays a query-level pre-filter and is intentionally not
    enforced here.
    """
    # آسانسور is deliberately absent: a walk-up is a matter of degree, not a
    # disqualification, so it is priced by elevator_penalty below instead of
    # removing the listing. A first-floor flat with no lift is not a near
    # miss at all -- it is exactly as good as one with a lift.
    if intent.must_have_parking and not listing.has_parking:
        return False
    if intent.must_have_storage and not listing.has_storage:
        return False
    if intent.must_have_balcony and not listing.has_balcony:
        return False
    if intent.must_have_images and listing.image_count <= 0:
        return False
    if intent.full_rahn_only and not listing.is_full_rahn:
        return False
    if intent.convertible_only and not listing.can_convert:
        return False

    if intent.min_floor is not None and listing.floor < intent.min_floor:
        return False
    if intent.max_floor is not None and listing.floor > intent.max_floor:
        return False
    if intent.min_build_year is not None:
        if listing.build_year is None or listing.build_year < intent.min_build_year:
            return False

    if intent.target_neighborhood_keys and not neighborhoods.contains_any(
        listing.lat, listing.lon, intent.target_neighborhood_keys
    ):
        return False

    area_min, area_max = _area_band(intent)
    if area_min is not None and listing.area_sqm < area_min:
        return False
    if area_max is not None and listing.area_sqm > area_max:
        return False

    # Floors are stated on the raw advertised figures: "at least 100 ودیعه"
    # describes the ad the user wants to see, not a converted equivalent.
    if intent.min_deposit is not None and listing.deposit_toman < intent.min_deposit:
        return False
    if intent.min_rent is not None and listing.rent_toman < intent.min_rent:
        return False

    # Ceilings are stated on the *converted* figures, because a قابل تبدیل
    # listing whose advertised deposit is out of reach may be perfectly
    # affordable once the deposit is bought down into rent.
    # One budget tolerance, not two: the per-axis ceilings use the same
    # multiplier as the combined one below, so a listing can never be admitted
    # by the combined check and then rejected by an axis of it.
    deposit, rent = resolve_tabdil(listing, intent)
    elastic = constants.BUDGET_CEILING_MULTIPLIER
    max_deposit, max_rent = _cap(intent.max_deposit), _cap(intent.max_rent)
    if max_deposit is not None and deposit > max_deposit * elastic:
        return False
    if max_rent is not None and rent > max_rent * elastic:
        return False

    target = user_target_cost(intent)
    if target is not None and total_monthly_cost(deposit, rent) > constants.BUDGET_CEILING_MULTIPLIER * target:
        return False

    return True


# --------------------------------------------------------------------------
# Stage 2: sub-utilities
# --------------------------------------------------------------------------


def financial_utility(listing: Listing, intent: ExtractedSearchIntent) -> float:
    """U_financial: how the listing's total monthly cost sits against the
    user's budget, decaying exponentially once it goes over.

    Under budget the score runs from 1.0 (free) down to 0.8 (exactly at the
    cap), so being comfortably cheaper is always rewarded; past the cap it
    falls away at lambda=5, which is steep enough that a listing at the very
    edge of the elastic window cannot outrank a listing that genuinely fits.
    """
    ratio = _budget_ratio(listing, intent)
    if ratio is None:
        return 1.0
    if ratio <= 1.0:
        return 1.0 - 0.2 * ratio
    return 0.8 * math.exp(-constants.FINANCIAL_DECAY_LAMBDA * (ratio - 1.0))


def value_utility(listing: Listing, baselines: MarketBaselines) -> float:
    """U_value: the Value-for-Money Index -- the neighborhood's median cost
    per square metre over this listing's own.

    This is what separates "cheap" from "a good deal": a small flat in a
    cheap district is not automatically better value than a large one in an
    expensive district, and only a per-neighborhood comparison can say which.
    """
    baseline = baselines.for_listing(listing)
    if baseline <= 0 or listing.area_sqm <= 0:
        return 0.5
    per_sqm = total_monthly_cost(listing.deposit_toman, listing.rent_toman) / listing.area_sqm
    if per_sqm <= 0:
        return 1.0
    return max(0.0, min(1.0, (baseline / per_sqm) / constants.VALUE_INDEX_CAP))


def area_utility(listing: Listing, intent: ExtractedSearchIntent) -> float:
    """U_area: a concave curve centred on the user's ideal size.

    The ideal is the midpoint when they gave a range, and the stated bound
    itself when they gave only one -- a listing bigger than a stated minimum
    is not penalised for it, only one smaller.
    """
    low, high = intent.min_area_sqm, intent.max_area_sqm
    if low is None and high is None:
        return 1.0
    if low is not None and high is not None:
        ideal = (low + high) / 2
    elif high is not None:
        ideal = float(high)
    else:
        ideal = float(low)
        if listing.area_sqm >= ideal:
            return 1.0
    if ideal <= 0:
        return 1.0
    deviation = abs(listing.area_sqm - ideal) / ideal
    return max(0.0, 1.0 - deviation**1.5)


def has_effective_elevator(listing: Listing) -> bool:
    """Whether the lift question is settled for this home.

    True when there is a lift -- and equally true on the ground or first
    floor, where there is nothing for one to do. Scoring those homes as
    lift-less penalised them for not owning a machine their resident would
    never press the button of.
    """
    return listing.has_elevator or listing.floor <= 1


# (what the user ticked, what the listing has, what the market pays for it).
# Elevator reads through has_effective_elevator, so a ground-floor flat is not
# marked down for lacking a machine it has no use for.
_AMENITY_TERMS: tuple[tuple[str, Callable[[Listing], bool], float], ...] = (
    ("must_have_parking", lambda l: l.has_parking, constants.AMENITY_WEIGHT_PARKING),
    ("must_have_elevator", has_effective_elevator, constants.AMENITY_WEIGHT_ELEVATOR),
    ("must_have_storage", lambda l: l.has_storage, constants.AMENITY_WEIGHT_STORAGE),
    ("must_have_balcony", lambda l: l.has_balcony, constants.AMENITY_WEIGHT_BALCONY),
)


def amenity_utility(listing: Listing, intent: Optional[ExtractedSearchIntent] = None) -> float:
    """U_amenity: market-weighted sum of the amenities present.

    Once the user has ticked amenities in the panel, only the ticked ones are
    scored -- the امکانات dial is then a statement about *those*, and letting a
    balcony nobody asked for lift a listing above one that has everything the
    user did ask for is the dial doing the opposite of what it says. The sum is
    renormalised over the terms in play so a one-amenity search still spans the
    same 0..1 as the market-weighted default.

    With nothing ticked there is no stated preference to honour, so it falls
    back to the market weighting across all four.
    """
    terms = [term for term in _AMENITY_TERMS if intent is not None and getattr(intent, term[0])]
    if not terms:
        terms = list(_AMENITY_TERMS)
    total = sum(weight for _, _, weight in terms)
    if total <= 0:
        return 0.0
    return sum(weight * float(present(listing)) for _, present, weight in terms) / total


def metro_utility(listing: Listing) -> float:
    """U_metro: how close the nearest metro station is on foot.

    Its own criterion rather than half of the commute term, because it is the
    half that can always be answered -- every listing has a nearest station,
    while a workplace commute exists only once the user names a workplace --
    and because the panel now lets the user weight the two separately.
    """
    return 1.0 / (
        1.0
        + math.exp(
            constants.METRO_WALK_SIGMOID_K * (listing.metro_walk_mins - constants.METRO_WALK_SIGMOID_MIDPOINT_MINS)
        )
    )


def commute_utility(listing: Listing, intent: ExtractedSearchIntent) -> float:
    """U_commute: S_workplace_commute. Neutral with no workplace set, where
    resolve_weights drops the criterion's weight entirely rather than letting
    every listing collect it for free."""
    if intent.workplace_lat is None or intent.workplace_lon is None:
        return 1.0

    commute_mins = estimate_commute_time(
        listing.lat, listing.lon, intent.workplace_lat, intent.workplace_lon, mode=intent.commute_mode
    )
    return 1.0 / (1.0 + math.exp(constants.WORKPLACE_COMMUTE_SIGMOID_K * (commute_mins - intent.max_commute_mins)))


def quality_utility(listing: Listing) -> float:
    """U_quality: how sought-after the listing's own neighborhood is, 0..1.

    Read from the precomputed index rather than derived here -- it is a
    corpus-wide aggregate (see app/core/neighborhood_quality.py), and a
    listing whose neighborhood we have no reading for scores the neutral
    midpoint instead of being penalised for our missing data.
    """
    return neighborhood_quality.score_for(listing.neighborhood_key)


def freshness_utility(listing: Listing) -> float:
    """U_freshness: exponential decay on building age."""
    return math.exp(-max(0, listing.building_age_years) / constants.FRESHNESS_DECAY_YEARS)


def elevator_deficit(listing: Listing) -> float:
    """How much of a walk-up this home is, 0..1.

    0 whenever the lift question is settled (see has_effective_elevator),
    then rising one flight at a time and saturating at
    ELEVATOR_DEFICIT_TOP_FLOOR. A second floor without a lift is a minor
    inconvenience and a sixth is a different way of living; one flat number
    for "no lift" could not say that.
    """
    if has_effective_elevator(listing):
        return 0.0
    return min(1.0, (listing.floor - 1) / float(constants.ELEVATOR_DEFICIT_TOP_FLOOR - 1))


def elevator_penalty(listing: Listing, intent: ExtractedSearchIntent, weights: CriteriaWeights) -> float:
    """The multiplier a missing lift costs, given the floor and how much the
    user said amenities matter.

    Two dials feed it. Ticking آسانسور in the panel roughly doubles the
    strength -- the user asked, and a fifth-floor walk-up is not what they
    asked for -- and weighting امکانات کم or زیاد scales it further, so the
    penalty answers to the same control as the amenity credit rather than
    being a fixed rule sitting behind the user's back.
    """
    deficit = elevator_deficit(listing)
    if deficit <= 0.0:
        return 1.0

    strength = (
        constants.ELEVATOR_PENALTY_STRENGTH_REQUIRED
        if intent.must_have_elevator
        else constants.ELEVATOR_PENALTY_STRENGTH_DEFAULT
    )
    # The baseline share is a constant of the weighting scheme, not of this
    # listing: computing it per row meant building and normalising two Pydantic
    # models for every candidate, which was a third of the whole ranking cost.
    baseline = _default_amenity_share()
    emphasis = min(2.0, max(0.5, weights.amenity / baseline)) if baseline > 0 else 1.0
    return 1.0 - min(constants.ELEVATOR_PENALTY_MAX, strength * emphasis) * deficit


def structural_penalty(listing: Listing, intent: ExtractedSearchIntent, weights: CriteriaWeights) -> float:
    """prod(P): multiplicative penalties for the things that make an otherwise
    good listing hard to live in -- stairs with no lift, or a basement unit
    with no daylight."""
    penalty = elevator_penalty(listing, intent, weights)
    if listing.floor < 0:
        penalty *= constants.PENALTY_BASEMENT
    return penalty


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    norm_a, norm_b = np.linalg.norm(vec_a), np.linalg.norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def soft_utility(query_embedding: Optional[list[float]], listing: Listing) -> float:
    """U_soft: cosine similarity between the soft-preference summary and the
    listing description. 1.0 (neutral) when the user described no qualities.

    The query is embedded once per search by the caller rather than once per
    candidate -- embedding it inside the loop turned one API call into one per
    listing, which is the single most expensive mistake available here.
    """
    if query_embedding is None or listing.embedding is None:
        return 1.0
    return max(0.0, min(1.0, cosine_similarity(query_embedding, listing.embedding)))


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _default_amenity_share() -> float:
    """امکانات's share of the default weighting, normalised. Fixed for the
    life of the process -- the default weights come from constants."""
    return default_weights().normalized().amenity


def default_weights() -> CriteriaWeights:
    return CriteriaWeights(
        budget=constants.UTILITY_WEIGHT_BUDGET,
        value=constants.UTILITY_WEIGHT_VALUE,
        area=constants.UTILITY_WEIGHT_AREA,
        amenity=constants.UTILITY_WEIGHT_AMENITY,
        metro=constants.UTILITY_WEIGHT_METRO,
        commute=constants.UTILITY_WEIGHT_COMMUTE,
        quality=constants.UTILITY_WEIGHT_QUALITY,
        freshness=constants.UTILITY_WEIGHT_FRESHNESS,
        soft=constants.UTILITY_WEIGHT_SOFT,
    )


#: The classic panel expresses importance in three steps rather than as a
#: continuous dial, because a slider invites a precision the ranking does not
#: have. "زیاد" is a little over double the default share and "کم" a little
#: under half, which is enough to visibly reorder results without letting one
#: criterion swamp the other seven.
IMPORTANCE_MULTIPLIERS: dict[str, float] = {"low": 0.4, "normal": 1.0, "high": 2.2}


def weights_from_importance(levels: dict[str, str]) -> CriteriaWeights:
    """The documented default weights, scaled by the user's per-criterion
    importance. Criteria the user said nothing about keep their default
    share; resolve_weights still zeroes the ones this search cannot score."""
    base = default_weights()
    return CriteriaWeights(
        **{
            name: getattr(base, name) * IMPORTANCE_MULTIPLIERS.get(levels.get(name, "normal"), 1.0)
            # Read off the instance: pydantic exposes an underscore class
            # attribute as a ModelPrivateAttr descriptor on the class itself.
            for name in base._FIELDS
        }
    )


def resolve_weights(intent: ExtractedSearchIntent) -> CriteriaWeights:
    """The weight vector this search ranks with.

    Starts from the user's own weights when the conversation inferred a set,
    otherwise from the documented defaults, then scales the commute term by
    the reachability dial and renormalizes. At importance 0 the commute
    criterion contributes nothing and its share is redistributed across the
    remaining criteria, so scores stay comparable between searches instead of
    every listing simply losing 15 points.
    """
    base = default_weights()
    if intent.weights is not None and intent.weights.total() > 0:
        base = intent.weights

    # A criterion the user said nothing about cannot separate one listing from
    # another -- every candidate scores the neutral 1.0 on it. Leaving those
    # criteria weighted would lift every score toward the top of the range and
    # make the tier thresholds meaningless: with no budget stated, a listing
    # would carry the full budget weight for free. Their share is redistributed
    # over the criteria that actually discriminate.
    update: dict[str, float] = {}
    # Without a workplace there is no commute to score: every listing would
    # take the neutral 1.0 and the criterion would separate nothing.
    if intent.workplace_lat is None or intent.workplace_lon is None:
        update["commute"] = 0.0
    else:
        update["commute"] = base.commute * (intent.commute_importance / constants.COMMUTE_IMPORTANCE_DEFAULT)
    if _cap(intent.max_deposit) is None and _cap(intent.max_rent) is None:
        update["budget"] = 0.0
    if intent.min_area_sqm is None and intent.max_area_sqm is None:
        update["area"] = 0.0
    if not intent.soft_preference_summary:
        update["soft"] = 0.0
    # Without a built index every listing scores the same neutral 0.5, which
    # separates nothing and would just compress the whole score range.
    if not neighborhood_quality.is_available():
        update["quality"] = 0.0

    normalized = base.model_copy(update=update).normalized()
    return normalized if normalized.total() > 0 else default_weights()


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


@dataclass
class ScoredListing:
    listing: Listing
    utility_score: float
    tier: int = 0
    trade_off_rationale: Optional[str] = None
    is_pareto_optimal: bool = False
    # The (deposit, rent) split actually scored, which is not the advertised
    # one whenever a تبدیل made the listing fit. The UI shows it so the user
    # can see *why* an apparently out-of-budget listing was surfaced.
    suggested_deposit_toman: Optional[int] = None
    suggested_rent_toman: Optional[int] = None
    score_breakdown: dict[str, float] = field(default_factory=dict)


def _static_utilities(listing: Listing, baselines: MarketBaselines) -> tuple[float, float, float, float]:
    """(value, metro, quality, freshness) for one listing.

    None of the four reads the intent: they describe the property and the
    market it sits in, so their answer is the same for every search this
    corpus serves and is worth computing once. Together they were about a
    sixth of the cost of ranking the whole city on every keystroke.

    U_amenity used to be cached here too and no longer can be: it now depends
    on which amenities the user ticked, so it is recomputed per search.
    """
    cached = baselines._static.get(listing.id)
    if cached is None:
        cached = (
            value_utility(listing, baselines),
            metro_utility(listing),
            quality_utility(listing),
            freshness_utility(listing),
        )
        baselines._static[listing.id] = cached
    return cached


def compute_utility(
    listing: Listing,
    intent: ExtractedSearchIntent,
    weights: CriteriaWeights,
    baselines: MarketBaselines,
    query_embedding: Optional[list[float]] = None,
) -> tuple[float, dict[str, float]]:
    """S_total(L|U) and the sub-utilities behind it. 0.0 if a hard constraint
    fails."""
    if not hard_constraint_mask(listing, intent):
        return 0.0, {}

    value, metro, quality, freshness = _static_utilities(listing, baselines)
    breakdown = {
        "budget": financial_utility(listing, intent),
        "value": value,
        "area": area_utility(listing, intent),
        "amenity": amenity_utility(listing, intent),
        "metro": metro,
        "commute": commute_utility(listing, intent),
        "quality": quality,
        "freshness": freshness,
        "soft": soft_utility(query_embedding, listing),
    }
    weighted = sum(getattr(weights, name) * value for name, value in breakdown.items())
    return weighted * structural_penalty(listing, intent, weights), breakdown


class _PrefixMax:
    """Fenwick tree of prefix maxima -- the sweep's "best area seen at or
    below this metro-walk rank" query, in O(log n) instead of O(n)."""

    __slots__ = ("_tree",)

    def __init__(self, size: int) -> None:
        self._tree = [float("-inf")] * (size + 1)

    def update(self, index: int, value: float) -> None:
        index += 1
        while index < len(self._tree):
            if self._tree[index] < value:
                self._tree[index] = value
            index += index & -index

    def prefix_max(self, index: int) -> float:
        index += 1
        best = float("-inf")
        while index > 0:
            if self._tree[index] > best:
                best = self._tree[index]
            index -= index & -index
        return best


def _pareto_key(listing: Listing) -> tuple[float, float, float]:
    """The three axes domination is judged on: effective monthly cost (less is
    better), metro walk (less is better), area (more is better)."""
    return (
        total_monthly_cost(listing.deposit_toman, listing.rent_toman),
        float(listing.metro_walk_mins),
        float(listing.area_sqm),
    )


def pareto_frontier(scored: list[ScoredListing]) -> list[ScoredListing]:
    """Listings not strictly dominated by any other listing in the set.

    A three-dimensional skyline, computed by a sweep rather than by comparing
    every pair: the pairwise form is O(n^2) and was, on a city-wide search of
    ~3,500 tier-1 results, three quarters of the entire ranking cost (750k
    comparisons, ~1.7s). Sorting by cost ascending -- then metro ascending,
    then area descending -- means every listing already visited has a cost no
    higher than the current one, so the only question left is whether any of
    them also had a metro walk no longer *and* an area no smaller. A Fenwick
    tree of prefix maxima over metro-walk ranks answers exactly that in
    logarithmic time.

    Domination is decided on *distinct* (cost, metro, area) triples: two
    listings with identical coordinates cannot dominate each other (nothing is
    strictly better), and deduplicating is what lets the sweep treat "some
    earlier point is at least as good" as domination outright.
    """
    if len(scored) <= 1:
        return list(scored)

    keys = [_pareto_key(entry.listing) for entry in scored]
    distinct = sorted(set(keys), key=lambda key: (key[0], key[1], -key[2]))
    metro_ranks = {value: rank for rank, value in enumerate(sorted({key[1] for key in distinct}))}

    tree = _PrefixMax(len(metro_ranks))
    undominated: set[tuple[float, float, float]] = set()
    for cost, metro, area in distinct:
        rank = metro_ranks[metro]
        if tree.prefix_max(rank) < area:
            undominated.add((cost, metro, area))
        tree.update(rank, area)

    return [entry for entry, key in zip(scored, keys) if key in undominated]


def _trade_off_rationale(listing: Listing, reference: Listing, intent: ExtractedSearchIntent) -> Optional[str]:
    """Persian trade-off nudge per docs/ALGORITHMS.md SS4: qualifies when the
    listing is >=25% larger than the Tier 1 reference AND either the budget
    increase is <=10% or the extra metro-walk time is <=7 minutes."""
    if reference.area_sqm <= 0:
        return None

    area_increase = (listing.area_sqm - reference.area_sqm) / reference.area_sqm
    reference_cost = total_monthly_cost(reference.deposit_toman, reference.rent_toman)
    listing_cost = total_monthly_cost(listing.deposit_toman, listing.rent_toman)
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
    client: EmbeddingClient,
    listings: list[Listing],
    intent: ExtractedSearchIntent,
    baselines: Optional[MarketBaselines] = None,
) -> tuple[list[ScoredListing], list[ScoredListing]]:
    """Score, then stratify into (tier_1_results, tier_2_results).

    Tier membership is decided by the score alone -- Tier 1 is >=0.70, Tier 2
    is 0.45..0.70 -- so the two tiers never overlap and the tier a listing
    lands in always agrees with the match percentage shown next to it.

    Pareto optimality is reported as a flag on the Tier 1 entries it applies
    to, never as a demotion: domination is a statement about (cost, metro
    walk, area) trade-offs between two listings, not about which one better
    fits what the user asked for.
    """
    if baselines is None:
        baselines = MarketBaselines.from_listings(listings)

    query_embedding = (
        await client.generate_embedding(intent.soft_preference_summary) if intent.soft_preference_summary else None
    )
    weights = resolve_weights(intent)

    scored: list[ScoredListing] = []
    for listing in listings:
        utility, breakdown = compute_utility(listing, intent, weights, baselines, query_embedding)
        deposit, rent = resolve_tabdil(listing, intent) if breakdown else (listing.deposit_toman, listing.rent_toman)
        scored.append(
            ScoredListing(
                listing=listing,
                utility_score=utility,
                suggested_deposit_toman=deposit if deposit != listing.deposit_toman else None,
                suggested_rent_toman=rent if deposit != listing.deposit_toman else None,
                # Kept raw. Rounding is presentation, and rounding here meant
                # rounding nine numbers for every listing in the city to show
                # them for the sixty on the page (see _to_result).
                score_breakdown=breakdown,
            )
        )

    tier1 = sorted(
        (s for s in scored if s.utility_score >= constants.TIER_1_UTILITY_THRESHOLD),
        key=lambda s: s.utility_score,
        reverse=True,
    )
    tier2 = sorted(
        (
            s
            for s in scored
            if constants.TIER_2_UTILITY_THRESHOLD <= s.utility_score < constants.TIER_1_UTILITY_THRESHOLD
        ),
        key=lambda s: s.utility_score,
        reverse=True,
    )

    for scored_listing in tier1:
        scored_listing.tier = 1
    for scored_listing in pareto_frontier(tier1):
        scored_listing.is_pareto_optimal = True
    for scored_listing in tier2:
        scored_listing.tier = 2

    if tier1:
        reference = tier1[0].listing
        for scored_listing in tier2:
            scored_listing.trade_off_rationale = _trade_off_rationale(scored_listing.listing, reference, intent)

    return tier1, tier2
