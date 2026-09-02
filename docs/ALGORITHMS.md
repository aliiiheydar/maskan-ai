# The Ranking

How a query becomes an ordered list. This document is the specification the
engine in `backend/app/search/scoring.py` implements; where the two disagree,
the code is right and this is a bug.

The shape is a two-stage funnel. **Stage 1** decides which listings the query
is even about — exact predicates enforced exactly, numeric limits enforced at
the edge of a tolerance band. **Stage 2** scores each survivor with a
Multi-Attribute Utility Theory sum and orders the whole set by it.

---

## 1. Financial model: تبدیل

Deposit (ودیعه/رهن) and rent (اجاره) are interchangeable in the Iranian
market at a standard monthly rate **r = 0.03** — 100,000,000 تومان of deposit
is worth about 3,000,000 تومان of monthly rent. Two derived figures carry the
whole model:

$$\text{TMC} = R + (D \times r) \qquad\qquad \text{FDE} = D + \frac{R}{r}$$

`TMC` (total monthly cost, the app's "effective monthly cost") is the single
comparable price of any listing. `FDE` is the same listing expressed as رهن
کامل.

**The critical invariant: تبدیل is cost-neutral.** TMC is unchanged by moving
along the conversion line, so conversion never makes a listing *cheaper* — it
only changes whether that listing is *reachable* for a user with a particular
amount of cash. It is therefore applied in the feasibility check, never in the
price score. Break this and the engine can make any listing look like a
bargain by shuffling two numbers.

### The conversion band

A non-convertible listing is a single point. A convertible one runs from the
advertiser's published ceiling (or full رهن when none was published) down to
`TABDIL_MIN_DEPOSIT_FRACTION × FDE` — 20%.

### Which point on that band

| Situation | Where the engine lands |
| :-- | :-- |
| Advertised deposit exceeds the user's stated ceiling | As far down the band as the advertiser allows, toward what the user actually has |
| `financial_persona = prefer_higher_deposit` | The top of the band (رهن کامل) — protects monthly cash flow |
| `financial_persona = prefer_higher_rent` | The bottom of the band — protects liquidity |
| Nothing the user said calls for it | **The advertised split stands** |

That last row is the one worth defending. The engine never buys rent down on
its own just because a rent ceiling is tight: doing so would silently assume
unlimited cash, and would let *any* convertible listing meet *any* rent budget
by pushing the whole cost into the deposit.

---

## 2. Stage 1 — elastic candidate retrieval

### Exact, no near-miss admitted

Mandated amenities (پارکینگ، انباری، بالکن), "photos only", رهن کامل, قابل
تبدیل, the floor range, the minimum build year, and the drawn search area
(polygon containment on resolved محله keys). These either hold or the listing
is not in this search.

**آسانسور is deliberately not one of them.** A walk-up is a matter of degree,
not a disqualification: a first-floor flat without a lift is exactly as good
as one with a lift, and a second-floor walk-up is a compromise someone who
typed "آسانسور" may well accept. It is priced by a penalty instead (§4).

### Elastic, with a confidence band

A stated numeric filter is a preference, not a specification — someone who
types "at least 80 متر" does not want a 78-متر flat hidden from them.

| Filter | Band |
| :-- | :-- |
| Area | ±8% (`AREA_CONFIDENCE_BAND`) |
| Deposit ceiling, rent ceiling, combined budget | ×1.20 (`BUDGET_CEILING_MULTIPLIER`) |

Nothing extra is needed to keep those near misses in their place: the
sub-utilities already price the distance. `U_area` falls away from the stated
size on a concave curve and `U_financial` decays exponentially past the
budget, so an admitted near miss scores its way *below* the listings that met
the filter outright — and its ٪ badge says so.

Two asymmetries in how budgets are read:

* **Floors are raw, ceilings are converted.** "At least 100 ودیعه" describes
  the advert the user wants to see; a ceiling describes what they can afford,
  which is a post-تبدیل question.
* **A combined budget requires both axes.** Someone who filled in only "ودیعه
  تا ۱۵۰" has said nothing about monthly cash, and folding the missing axis in
  as zero would turn that into a 4.5m/month ceiling that prunes almost the
  whole city. With one axis stated, that axis is enforced and scored on its
  own.

---

## 3. Stage 2 — the utility function

$$S_{\text{total}}(L \mid U) = \left( \sum_k w_k \cdot U_k(L \mid U) \right) \times \prod P(L)$$

with every $U_k \in [0,1]$, $\sum_k w_k = 1$, and $P \in (0,1]$.

### The nine criteria

| $k$ | Default $w_k$ | $U_k$ |
| :-- | --: | :-- |
| `budget` | 0.26 | Cost against the user's stated budget, or against the market |
| `value` | 0.12 | Price per m² against **this listing's own neighborhood** |
| `area` | 0.16 | Closeness to the ideal size |
| `amenity` | 0.09 | Market-weighted amenities present |
| `metro` | 0.07 | Walking minutes to the nearest station |
| `commute` | 0.07 | Reachability of the stated workplace |
| `quality` | 0.10 | How sought-after the neighborhood itself is |
| `freshness` | 0.06 | Building age |
| `soft` | 0.07 | Semantic match with described qualities |

Budget leads because it is the constraint people cannot move. `value` is split
out from it on purpose: **being cheap and being a good deal for the area are
different questions**, and a renter comparing two districts needs both
answered. `quality` is a third, separate question — "is this a محله worth
being in" — which nothing else in the vector can answer.

### 3.1 `U_budget` — cost

*With a stated budget*, on the ratio $\rho = \text{TMC}(L) / \text{TMC}(U)$
(taken on whichever axis was stated, after any تبدیل):

$$U_{\text{budget}} = \begin{cases} 1 - 0.2\rho & \rho \le 1 \\ 0.8\,e^{-5(\rho - 1)} & \rho > 1 \end{cases}$$

Under budget it runs from 1.0 (free) to 0.8 (exactly at the cap), so being
comfortably cheaper is always rewarded. Past the cap the decay is steep enough
that a listing at the very edge of the elastic window cannot outrank one that
genuinely fits.

*With no budget stated*, the market answers in the user's place:

$$U_{\text{budget}} = \frac{C_{\text{median}}}{C_{\text{median}} + \text{TMC}(L)}$$

An empty budget field means "I did not say", not "I do not care" — of two
otherwise identical flats the cheaper one is the better result whether or not
anyone typed a ceiling. A median-priced flat scores 0.5 and the curve falls
off either side; this is a logistic in log-price, which is the scale rents are
actually spread on. The flat at 17× the median (the 99th percentile) scores
0.05 rather than 0, so price pushes it down the list without pretending it
does not exist. The reference is the **city-wide** median, not the
neighborhood's — that is `U_value`'s question, and asking it twice would count
one fact twice while leaving "this is an expensive flat" unsaid.

### 3.2 `U_value` — value for money

$$\text{VMI} = \frac{\text{median TMC/m}^2 \text{ of this neighborhood}}{\text{TMC}(L)/\text{area}(L)} \qquad U_{\text{value}} = \min\left(1, \frac{\text{VMI}}{1.2}\right)$$

20% under the neighborhood's median is already as good a deal as the score can
express. Baselines are computed over the **whole corpus**, never over the
filtered candidate slice: "cheap for this neighborhood" has to be measured
against the neighborhood, not against whatever survived the user's filters.

### 3.3 `U_area` — size

$$U_{\text{area}} = \max\left(0,\; 1 - \left|\frac{\text{area}(L) - \text{area}_{\text{ideal}}}{\text{area}_{\text{ideal}}}\right|^{1.5}\right)$$

The ideal is the midpoint of a stated range, or the stated bound itself when
only one was given — and a listing *bigger* than a stated minimum scores 1.0
rather than being penalised for exceeding it.

### 3.4 `U_amenity` — امکانات

$$U_{\text{amenity}} = \frac{\sum_i \alpha_i I_i}{\sum_i \alpha_i}$$

with market weights $\alpha$: parking 0.40, elevator 0.35, storage 0.15,
balcony 0.10.

Once the user has ticked amenities, **only the ticked ones are scored** and
the sum is renormalised over them. The امکانات dial is then a statement about
*those*; letting a balcony nobody asked for lift a listing above one that has
everything the user did ask for is the dial doing the opposite of what it
says. With nothing ticked, all four are scored at market weight.

Elevator reads through `has_effective_elevator`: a ground- or first-floor flat
counts as having the lift question settled, because a machine its resident
would never press the button of buys them nothing.

### 3.5 `U_metro` and `U_commute` — reachability

$$U_{\text{metro}} = \frac{1}{1 + e^{0.25\,(T_{\text{walk}} - 8)}} \qquad U_{\text{commute}} = \frac{1}{1 + e^{0.20\,(T_{\text{commute}} - T_{\max})}}$$

Two criteria, not one, because they answer different questions and only one of
them can always be answered: every listing has a nearest station, while a
workplace commute exists only once a workplace is named. Walking is 80 m/min.
Transit time is routed leg by leg over the real 359-node metro/BRT graph, not
divided out of a straight line; driving through the congestion zone is
multiplied by 1.4.

Reachability is a **weight, never a filter**. The estimates are approximations,
so how much they should move the ranking is a judgement only the searcher can
make — a 0..1 dial scales `w_commute`, and at 0 the criterion is dropped and
its share redistributed.

### 3.6 `U_quality` — the neighborhood itself

Read from a precomputed 0..1 desirability index
(`app/core/neighborhood_quality.py`); a listing whose neighborhood has no
reading scores the neutral midpoint rather than being punished for our missing
data.

### 3.7 `U_freshness` — building age

$$U_{\text{freshness}} = e^{-\text{age}/15}$$

### 3.8 `U_soft` — described qualities

Cosine similarity between the embedding of the user's soft-preference summary
and the listing's description embedding. 1.0 (neutral) when the user described
no qualities or the listing has no vector. The query is embedded **once per
search**, not once per candidate.

---

## 4. Penalties

Multiplicative, applied after the weighted sum.

**The missing lift** is priced by *how many flights*, because "no elevator" as
a flat yes/no cannot tell a second floor from a sixth:

$$\text{deficit} = \min\left(1, \frac{\text{floor} - 1}{6}\right), \qquad P_{\text{lift}} = 1 - \min(0.85,\; s \cdot e) \cdot \text{deficit}$$

where $s$ is 0.30 normally and 0.60 when the user ticked آسانسور, and $e$
scales with how much they weighted امکانات — so the penalty answers to the
same control as the amenity credit instead of being a fixed rule behind the
user's back. The deficit is 0 on the ground and first floors.

**Basement units** (`floor < 0`) take a flat ×0.80 for daylight. They are real
stock in Tehran and Divar lists them, so they are priced rather than pretended
away.

---

## 5. Weight resolution

The default vector above is the starting point. Two things move it:

* **The panel's importance dials** — three steps per criterion, multiplying
  the default share by 0.4 / 1.0 / 2.2. A slider was rejected: it invites a
  precision the ranking does not have.
* **The conversation** — "مهم‌ترین چیز برام نزدیکی به مترو است، قیمت مهم نیست"
  is a statement about weights, not about filters, and the extractor can
  return a whole vector.

Then criteria this particular search **cannot discriminate on are zeroed and
their share redistributed**: no workplace → `commute`; no area filter →
`area`; no described qualities → `soft`; no quality index built → `quality`.
Leaving them weighted would lift every score toward the top of the range and
flatten the ranking against its ceiling, crowding the ٪ badges into a few
points where they separate nothing.

`budget` is deliberately **not** on that list. It has no stated ceiling half
the time and still discriminates, because §3.1 falls back to the market.

---

## 6. The result list

Everything scoring at or above **`MIN_UTILITY_THRESHOLD` = 0.45** is returned,
ordered by score, best first. That is the whole output shape.

> **Historical note.** This used to be split into `tier_1_results` (≥ 0.70) and
> `tier_2_results` (0.45–0.70). The split was removed: each card already
> carries its own ٪ badge, so a second, coarser statement of the same fact put
> a wall between two listings a hundredth of a point apart and asked the user
> to read the boundary instead of the number. The floor survives, because a
> ranked list still has an end — a listing that passed every hard filter and
> still scores under half answers the question badly.

The number on the card is the listing's own utility, printed as computed —
never stretched across the range of whatever results happen to be loaded. It
means the same thing on card 3 and card 300, it does not move when more
results load, and it falls at the rate the ranking actually falls.

### 6.1 Pareto optimality

A listing is flagged `is_pareto_optimal` when **no other result in the whole
search** beats it on all three of:

* effective monthly cost (lower better),
* metro walk minutes (lower better),
* area (higher better).

Over the whole set, not over the visible page, because the card's tooltip
makes an unqualified claim — «هیچ گزینه‌ی دیگری همزمان ارزان‌تر، نزدیک‌تر به
مترو و بزرگ‌تر نیست» — and that has to be true of the search rather than of
the sixty rows the reader happens to be looking at. Scoped to the first page
it fired on 15 of 60 results in a city-wide search and meant very little; over
the whole set it fires on 3, and each is worth reading.

It is a flag, never a demotion: domination is a statement about trade-offs
between two listings, not about which better answers the search.

Computed as a three-dimensional skyline by sweep rather than pairwise
comparison. The pairwise form is $O(n^2)$ and was, on the ~3,500 strong matches
this used to run over, three quarters of the entire ranking cost (750k
comparisons, ~1.7s); the sweep does all 19,000 results in ~80 ms, which the
pairwise form could not have done at all. Sorting by cost ascending means every listing
already visited costs no more than the current one, so the only open question
is whether any of them also had a metro walk no longer *and* an area no
smaller — which a Fenwick tree of prefix maxima over metro-walk ranks answers
in log time.

### 6.2 The trade-off sentence

A result *below* the head earns a Persian rationale when it is ≥25% larger
than the head's median area and the price of that space is small on every axis
the user actually weighs:

* **Budget** — measured against the *user's own stated ceiling* (post-تبدیل,
  through the same ratio §3.1 uses), never against another listing's price.
  Overrun must be ≤10%. Omitted entirely when no budget was stated.
* **Metro** — at most 7 minutes more walking than the head's median.

The reference is the median of the head rather than the attributes of
`results[0]`: the top-ranked listing wins on *utility*, and its size and metro
walk are incidental to that, so measuring everything against that accident let
two searches differing by one filter describe the same listing quite
differently.

Three things it deliberately does not do:

* It does not call a comparison against another *listing* a comparison against
  the user's *budget*.
* It does not assert a leg that failed. Every axis the user weighs has to hold
  for the sentence to appear at all — a card that stays silent is honest, and
  one that lists a gain while omitting a cost the user cares about is not.
* It does not speak about an axis carrying less than `TRADE_OFF_MIN_AXIS_WEIGHT`
  of the decision. Telling someone who dialled مترو down to کم that a listing
  has "دسترسی مشابه یا بهتر به مترو" spends the one line the card has on the
  one fact they said they do not weigh.

> «این مورد ۲۵ متر بزرگ‌تر است و دسترسی مشابه یا بهتری به مترو دارد، اما ۱۰٪
> بالاتر از بودجهٔ شماست.»

---

## 7. Making it fast

The corpus is 21,377 rows and every keystroke in the panel re-ranks the city,
so this section is not premature optimisation — it is the difference between
a live feed and a spinner.

* **Narrow in SQLite, score in memory.** Exact predicates go to the R*Tree and
  the column indexes; only survivors are hydrated and scored.
* **Precomputed baselines.** Neighborhood median TMC/m² is computed once at
  startup over the whole corpus, never at query time.
* **Per-listing static utilities are cached.** `value`, `metro`, `quality` and
  `freshness` read nothing from the intent, so their answer is the same for
  every search this corpus serves. Together they were about a sixth of the
  cost of ranking the whole city.
* **Ranked pages are cached.** Ranking is a pure function of (corpus, intent,
  viewport). Paging with «بیشتر» is the same search asking for later rows;
  panning back to a viewport just left is the same search again. Only the head
  (600 rows) of each ranking is kept, so an entry costs a few hundred
  references rather than the whole city.
* **The LLM is off the ranking path.** Intent extraction happens on a chat
  turn and writes into the filter state; `/search` consumes the resolved
  intent. A 500–2000 ms generation never blocks a search.
* **Constants of the weighting scheme are not recomputed per row.** Building
  and normalising two Pydantic models per candidate to find the default
  amenity share was once a third of the whole ranking cost.
