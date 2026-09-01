"""Tehran domain constants: geospatial bounds, Tabdil rate, speed/penalty assumptions.

Physical/legal facts about the Tehran market, as distinct from config.py's
deployment settings -- these never come from the environment.
"""

from typing import NamedTuple


class BBox(NamedTuple):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


# Tehran city bounding box (WGS84).
TEHRAN_BBOX = BBox(min_lat=35.5500, max_lat=35.8500, min_lon=51.1000, max_lon=51.6000)

# Approximate central-Tehran congestion-pricing zone (Tarh-e Terafik), roughly the
# Vali-e-Asr / Enghelab / Ferdowsi corridor. This is an MVP bounding-box
# simplification, NOT the legally exact odd/even-day polygon.
TARH_TERAFIK_BBOX = BBox(min_lat=35.7000, max_lat=35.7350, min_lon=51.3900, max_lon=51.4350)

# Tabdil (deposit <-> rent conversion).
TABDIL_RATE: float = 0.03

# Walking speed used for metro/BRT walk-time estimates.
WALK_SPEED_MPM: float = 80.0

# Multiplier applied to driving time when a trip touches the congestion zone.
CONGESTION_PENALTY: float = 1.4

# Average speed assumption for driving. Public transport has no equivalent
# figure any more: it is routed leg by leg over the real network instead of
# averaged over a straight line (see app/spatial/routing.py).
AVG_DRIVE_SPEED_KMH: float = 22.0

# --- Multi-criteria utility scoring (docs/ALGORITHMS.md) ---

# Hard budget-ceiling multiplier for I_hard: C_eff(L) > this * C_target(U) -> pruned.
# docs/ALGORITHMS.md SS3.1 states 1.20x; docs/TESTING_GUIDE.md SS2.2 states 1.25x for
# its mandatory test case. Resolved in favor of ALGORITHMS.md (1.20x) per explicit
# user decision -- TESTING_GUIDE.md's figure is stale.
BUDGET_CEILING_MULTIPLIER: float = 1.20

# --- MAUT weights ("architectural suggestion.md" SS5) ---
#
# S_total = (sum_k w_k * U_k) * prod(penalties). The weights below are the
# defaults used when the conversation has not expressed priorities of its own;
# they sum to 1.0 and are renormalized after any per-user adjustment.
#
# Budget dominates because it is the constraint people actually cannot move,
# and `value` (price relative to the neighborhood's own median) is separated
# out from it: being cheap and being a good deal for the area are different
# things, and a renter comparing two districts cares about both.
UTILITY_WEIGHT_BUDGET: float = 0.26
UTILITY_WEIGHT_VALUE: float = 0.12
UTILITY_WEIGHT_AREA: float = 0.16
UTILITY_WEIGHT_AMENITY: float = 0.09
# Reachability is two separate questions with two separate dials: how close
# the metro is (always answerable) and how far the stated workplace is (only
# answerable once a workplace is set). They used to be one 0.14 criterion.
UTILITY_WEIGHT_METRO: float = 0.07
UTILITY_WEIGHT_COMMUTE: float = 0.07
UTILITY_WEIGHT_QUALITY: float = 0.10
UTILITY_WEIGHT_FRESHNESS: float = 0.06
UTILITY_WEIGHT_SOFT: float = 0.07

# U_quality: how sought-after the neighborhood itself is, from
# app/core/neighborhood_quality.py. Separate from `value` on purpose -- value
# asks "is this cheap for this محله", quality asks "is this a محله worth being
# in". A renter comparing زعفرانیه with a cheaper district is asking the second
# question, and no other criterion can answer it. It sits below budget and
# area because it is a preference, not a constraint: nobody is excluded from a
# home by the reputation of its street.

# How much reachability counts, on a 0..1 dial the user controls directly.
# Travel-time estimates here are straight-line approximations, not routed
# times, so how much they should move the ranking is a judgement only the
# searcher can make -- at 0 the commute criterion is dropped entirely and its
# weight is redistributed over the others.
COMMUTE_IMPORTANCE_DEFAULT: float = 0.5

# U_financial: exponential decay once the listing passes the user's budget.
FINANCIAL_DECAY_LAMBDA: float = 5.0
# U_value = min(1, VMI / this). A listing priced 20% under its neighborhood's
# median TMC/m2 is already "as good a deal as the score can express".
VALUE_INDEX_CAP: float = 1.2

# U_amenity = sum(alpha_i * I_i): market importance of each amenity.
AMENITY_WEIGHT_PARKING: float = 0.40
AMENITY_WEIGHT_ELEVATOR: float = 0.35
AMENITY_WEIGHT_STORAGE: float = 0.15
AMENITY_WEIGHT_BALCONY: float = 0.10

# Structural penalties (multiplicative, applied after the weighted sum).
PENALTY_BASEMENT: float = 0.80

# --- Walking up: the missing lift ---
#
# A missing lift is not a yes/no fault, it is a flight of stairs repeated
# every day, so it is priced by how many flights. On the ground or first
# floor there is nothing to price: those homes score exactly as if they had a
# lift, including for the امکانات credit, because the amenity buys their
# resident nothing. Above that the deficit grows with the floor and saturates
# here, by which point the walk-up is as bad as it is going to get.
ELEVATOR_DEFICIT_TOP_FLOOR: int = 7

# How much utility a fully saturated deficit costs. Asking for a lift in the
# filters roughly doubles it -- but it still scales the score rather than
# removing the listing, because a second-floor walk-up is a compromise
# somebody who typed "آسانسور" may well accept, and hiding it outright was
# the old behaviour people complained about.
ELEVATOR_PENALTY_STRENGTH_DEFAULT: float = 0.30
ELEVATOR_PENALTY_STRENGTH_REQUIRED: float = 0.60
# Weighting امکانات as زیاد sharpens the penalty and کم softens it, within
# these bounds -- the penalty answers to the same dial the amenity credit
# does, so the two cannot contradict each other.
ELEVATOR_PENALTY_MAX: float = 0.85

# Building freshness: U_freshness = exp(-age_years / this).
FRESHNESS_DECAY_YEARS: float = 15.0

# S_metro_walk(L) = 1 / (1 + exp(k * (T_walk_mins(L) - midpoint)))
METRO_WALK_SIGMOID_K: float = 0.25
METRO_WALK_SIGMOID_MIDPOINT_MINS: float = 8.0

# S_workplace_commute(L,U) = 1 / (1 + exp(k * (T_commute_mins(L,U) - T_max(U))))
WORKPLACE_COMMUTE_SIGMOID_K: float = 0.20

# S_price(L,U) = exp(-(deltaC / (tolerance*C_target(U) + eps))^2)
PRICE_SCORE_TOLERANCE: float = 0.15
PRICE_SCORE_EPSILON: float = 1.0

# --- Filter confidence bands ---
#
# A stated filter is a preference, not a specification: someone who types "at
# least 80 متر" does not want a 78-متر flat hidden from them. Numeric filters
# therefore admit a margin beyond the stated limit, and listings inside that
# margin enter the ranking with their Utility scaled down in proportion to how
# far outside they sit (see scoring.constraint_fit_score). They land in Tier 2
# by scoring their way there, so the tier a result is shown in still agrees
# with its match percentage.
#
# The area/rooms bands are fractions of the stated value; the price band reuses
# BUDGET_CEILING_MULTIPLIER so there is one budget tolerance, not two.
# delta_A per "architectural suggestion.md" SS3.2 -- 8% is the tolerance a
# renter actually negotiates on area, narrower than the budget band below.
AREA_CONFIDENCE_BAND: float = 0.08
ROOMS_CONFIDENCE_BAND: int = 1
# Weight of the fit factor: at the very edge of every band a listing keeps this
# fraction of its Utility. Not 0 -- an edge case should rank last, not vanish.
CONSTRAINT_FIT_FLOOR: float = 0.55

# Tier stratification thresholds.
TIER_1_UTILITY_THRESHOLD: float = 0.70
TIER_2_UTILITY_THRESHOLD: float = 0.45

# Tabdil conversion band assumed for a قابل تبدیل listing whose advertiser did
# not publish an explicit ceiling: the deposit may move anywhere from a fifth
# of the full-deposit equivalent up to the full رهن. Conversion at TABDIL_RATE
# leaves the total monthly cost unchanged -- what it changes is whether the
# listing fits the user's cash position at all.
TABDIL_MIN_DEPOSIT_FRACTION: float = 0.20

# Trade-off nudge identifier: Tier 2 vs. the top Tier 1 reference listing.
TRADE_OFF_MIN_AREA_INCREASE: float = 0.25
TRADE_OFF_MAX_BUDGET_INCREASE: float = 0.10
TRADE_OFF_MAX_COMMUTE_INCREASE_MINS: float = 7.0


# --- Public-transport routing (app/spatial/routing.py) ---
#
# The point-to-point transit model is built from Tehran operating figures
# rather than an average network speed: a trip is walk -> wait -> ride ->
# (transfer) -> ride -> walk, and each of those legs has its own cost. Riding
# is flat per station hop because Tehran's inter-station spacing is fairly
# even and dwell time dominates the difference.
METRO_RIDE_MINS_PER_STATION: float = 2.5
BRT_RIDE_MINS_PER_STATION: float = 2.0

# Mean wait = half the headway. BRT headways are uniform enough across the
# corridors to take one figure; metro headways are not -- lines 6 and 7 are
# the newest and run the sparsest service, and a rider on line 6 really does
# wait almost twice as long as one on line 1.
BRT_WAIT_MINS: float = 5.0
METRO_WAIT_MINS_BY_LINE: dict[str, float] = {
    "1": 4.0,
    "2": 4.0,
    "3": 4.0,
    "4": 4.0,
    "5": 6.0,
    "6": 7.5,
    "7": 6.0,
}
# Any metro line not named above (line extensions, data that names a line we
# have no headway for) is charged the most common headway rather than free.
METRO_WAIT_MINS_DEFAULT: float = 4.0

# Changing line inside a single interchange station: the walk along the
# passage between platforms. The wait for the new line is charged separately
# on top of this, because it is a separate thing that happens.
METRO_LINE_CHANGE_MINS: float = 1.0

# Two stations count as walkable transfers (metro <-> BRT, or BRT corridor to
# BRT corridor) only within this far apart on the street grid. Beyond it the
# router would happily "transfer" across half a district on foot.
MAX_TRANSFER_WALK_METERS: float = 700.0

# Street-grid detour factor is not applied on top of the Manhattan distance:
# the Manhattan distance *is* the detour model. Walking legs are
# manhattan_distance_meters / WALK_SPEED_MPM throughout.
