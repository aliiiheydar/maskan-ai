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
Continuous exponential penalty for listings exceeding the base target budget:

$$\Delta C = \max(0, C_{\text{eff}}(L) - C_{\text{target}}(U))$$

$$S_{\text{price}}(L, U) = \exp\left( - \left( \frac{\Delta C}{0.15 \times C_{\text{target}}(U) + \epsilon} \right)^2 \right)$$

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
If a Tier 2 listing offers $\ge 25\%$ larger area with $\le 10\%$ budget increase or $\le 7\text{ min}$ additional transit time compared to Tier 1 items, the engine tags it with a Persian trade-off rationale:
> *"این مورد ۱۰٪ بالاتر از بودجه است اما ۲۵ متر متراژ بزرگتر و دسترسی مستقیم به خط ۷ مترو دارد."*