# Mathematical Algorithms & Scoring Formulations

## 1. Iranian Real Estate Financial Conversion (*Tabdil*)

The platform converts multi-variable rental structures into a unified **Effective Monthly Cost ($C_{\text{eff}}$)**:

$$C_{\text{eff}}(L) = \text{Rent}(L) + \left( \text{Deposit}(L) \times r_{\text{tabdil}} \right)$$

Where:
* $r_{\text{tabdil}} = 0.03$ (3% per month, corresponding to the standard Iranian 30% annual conversion rule).

### Target User Budget Boundary ($C_{\text{target}}$)
$$C_{\text{target}}(U) = \text{MaxRent}(U) + \left( \text{MaxDeposit}(U) \times 0.03 \right)$$

---

## 2. Multi-Criteria Composite Utility Function

For every listing $L$ and user intent $U$:

$$\text{Utility}(L \mid U) = \mathbb{I}_{\text{hard}}(L \mid U) \times \left[ w_c \cdot S_{\text{commute}}(L, U) + w_p \cdot S_{\text{price}}(L, U) + w_s \cdot S_{\text{soft}}(L, U) + w_q \cdot S_{\text{quality}}(L) \right]$$

### Weights
* $w_c = 0.35$ (Commute & Transit Accessibility)
* $w_p = 0.35$ (Budget Alignment & Price Efficiency)
* $w_s = 0.20$ (Semantic Soft Preference Match)
* $w_q = 0.10$ (Listing Quality & Freshness)

---

## 3. Sub-Score Formulations

### 3.1 Hard Constraint Pruning Mask ($\mathbb{I}_{\text{hard}}$)
$$\mathbb{I}_{\text{hard}}(L \mid U) = \mathbf{1}_{\text{Elevator}}(L, U) \times \mathbf{1}_{\text{Parking}}(L, U) \times \mathbf{1}_{\text{BudgetCeiling}}(L, U) \times \mathbf{1}_{\text{Area}}(L, U)$$

* **Elevator Rule**: If `must_have_elevator == True` and `floor > 1` and `has_elevator == False` $\implies 0$, otherwise $1$.
* **Budget Ceiling**: If $C_{\text{eff}}(L) > 1.20 \times C_{\text{target}}(U) \implies 0$, otherwise $1$.

### 3.2 Commute Accessibility Score ($S_{\text{commute}}$)
Combines walking distance to the nearest Metro/BRT station and multimodal commute time to the user's primary workplace:

$$S_{\text{metro\_walk}}(L) = \frac{1}{1 + \exp\left( 0.25 \times (T_{\text{walk\_mins}}(L) - 8.0) \right)}$$

$$S_{\text{workplace\_commute}}(L, U) = \frac{1}{1 + \exp\left( 0.20 \times (T_{\text{commute\_mins}}(L, U) - T_{\text{max}}(U)) \right)}$$

$$S_{\text{commute}}(L, U) = 0.50 \cdot S_{\text{metro\_walk}}(L) + 0.50 \cdot S_{\text{workplace\_commute}}(L, U)$$

### 3.3 Price Score ($S_{\text{price}}$)
Measured against the user's stated ceiling where there is one, and against the market where there is not. With a budget $C_{\text{target}}(U)$ — the post-تبدیل effective cost of the ودیعه/اجاره pair the user typed — the ratio $\rho = C_{\text{eff}}(L) / C_{\text{target}}(U)$ scores linearly under the cap and decays exponentially over it, so being comfortably cheaper is rewarded and a listing at the edge of the elastic window cannot outrank one that genuinely fits:

$$S_{\text{price}}(L, U) = \begin{cases} 1 - 0.2\rho & \rho \le 1 \\ 0.8 \, e^{-\lambda (\rho - 1)}, \; \lambda = 5 & \rho > 1 \end{cases}$$

With only one axis stated, $\rho$ is taken on that axis alone; a floor (از) is a filter and never a price score.

**With no budget at all**, the corpus median $C_{\text{median}}$ stands in for the ceiling the user never typed. An empty budget field means "I did not say", not "I do not care", so price — the heaviest single criterion — keeps its weight rather than being zeroed:

$$S_{\text{price}}(L) = \frac{C_{\text{median}}}{C_{\text{median}} + C_{\text{eff}}(L)}$$

A median-priced flat scores $0.5$ and the curve falls off either side of it. This is a logistic in log-price, which is the scale rents are actually spread on: the 99th-percentile listing (~17× the median) scores $0.05$ rather than $0$, so price pushes it down the list without pretending it does not exist. The reference is the **city-wide** median, not the neighborhood's — how a listing prices against its own neighborhood is $S_{\text{value}}$'s question, and asking it twice would count one fact twice while leaving "this is an expensive flat" unsaid.

### 3.4 Semantic Soft Preference Score ($S_{\text{soft}}$)
Cosine similarity between the OpenRouter embedding of the user's soft preference summary and the listing description:

$$S_{\text{soft}}(L, U) = \frac{\mathbf{E}(Q_{\text{soft}}) \cdot \mathbf{E}(D_{\text{listing}})}{\|\mathbf{E}(Q_{\text{soft}})\| \|\mathbf{E}(D_{\text{listing}})\|}$$

---

## 4. Stratification & Pareto Trade-Off Optimization

Listings passing the hard mask are partitioned into two tiers:

```
                          ┌────────────────────────┐
                          │    Filtered Results    │
                          └───────────┬────────────┘
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                         ▼
   ┌───────────────────────────┐             ┌───────────────────────────┐
   │ Tier 1: Primary Picks     │             │ Tier 2: Trade-Off Picks   │
   │  Utility(L) >= 0.70       │             │  0.45 <= Utility(L) < 0.70│
   │  - Pareto-optimal set     │             │  - Relaxed bounds         │
   │  - Detailed AI summary    │             │  - Actionable rationale   │
   └───────────────────────────┘             └───────────────────────────┘
```

### Trade-Off Nudge Identifier
A Tier 2 listing earns a Persian trade-off rationale when it offers $\ge 25\%$ larger area than the **median** Tier 1 pick and the price of that space is small on every axis the user actually weighs:

* **Budget** — measured against the *user's own stated ceiling* (post-تبدیل, via the same ratio the financial sub-utility uses), never against another listing's price. Overrun must be $\le 10\%$. Omitted entirely when no budget was stated.
* **Metro** — $\le 7\text{ min}$ additional walk versus the median Tier 1 pick.

An axis carrying less than `TRADE_OFF_MIN_AXIS_WEIGHT` of the resolved ranking weights is one the user dialled down (کم) or never engaged: it is neither named in the sentence nor allowed to disqualify the nudge. An axis that *is* weighed and falls outside its band suppresses the rationale altogether, rather than being dropped from the sentence and leaving a one-sided claim.

> *"این مورد ۲۵ متر بزرگ‌تر است و دسترسی مشابه یا بهتری به مترو دارد، اما ۱۰٪ بالاتر از بودجهٔ شماست."*