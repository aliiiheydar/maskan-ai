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

# Average speed assumptions for commute-time estimation (Tehran MVP placeholders).
AVG_DRIVE_SPEED_KMH: float = 22.0
AVG_TRANSIT_SPEED_KMH: float = 28.0
TRANSIT_TRANSFER_BUFFER_MINS: float = 5.0

# --- Multi-criteria utility scoring (docs/ALGORITHMS.md) ---

# Hard budget-ceiling multiplier for I_hard: C_eff(L) > this * C_target(U) -> pruned.
# docs/ALGORITHMS.md SS3.1 states 1.20x; docs/TESTING_GUIDE.md SS2.2 states 1.25x for
# its mandatory test case. Resolved in favor of ALGORITHMS.md (1.20x) per explicit
# user decision -- TESTING_GUIDE.md's figure is stale.
BUDGET_CEILING_MULTIPLIER: float = 1.20

# Utility(L|U) = I_hard(L|U) * [w_c*S_commute + w_p*S_price + w_s*S_soft + w_q*S_quality]
UTILITY_WEIGHT_COMMUTE: float = 0.35
UTILITY_WEIGHT_PRICE: float = 0.35
UTILITY_WEIGHT_SOFT: float = 0.20
UTILITY_WEIGHT_QUALITY: float = 0.10

# S_metro_walk(L) = 1 / (1 + exp(k * (T_walk_mins(L) - midpoint)))
METRO_WALK_SIGMOID_K: float = 0.25
METRO_WALK_SIGMOID_MIDPOINT_MINS: float = 8.0

# S_workplace_commute(L,U) = 1 / (1 + exp(k * (T_commute_mins(L,U) - T_max(U))))
WORKPLACE_COMMUTE_SIGMOID_K: float = 0.20

# S_price(L,U) = exp(-(deltaC / (tolerance*C_target(U) + eps))^2)
PRICE_SCORE_TOLERANCE: float = 0.15
PRICE_SCORE_EPSILON: float = 1.0

# Tier stratification thresholds.
TIER_1_UTILITY_THRESHOLD: float = 0.70
TIER_2_UTILITY_THRESHOLD: float = 0.45

# Trade-off nudge identifier: Tier 2 vs. the top Tier 1 reference listing.
TRADE_OFF_MIN_AREA_INCREASE: float = 0.25
TRADE_OFF_MAX_BUDGET_INCREASE: float = 0.10
TRADE_OFF_MAX_COMMUTE_INCREASE_MINS: float = 7.0
