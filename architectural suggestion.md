# Architectural Specification: Intelligent Real Estate Rental Ranking & Filtering Engine

## 1. Executive Summary & Core Objective
Conventional real estate platforms (e.g., Divar, Zillow) rely on rigid boolean filters and naive sorting (e.g., sort by latest date or absolute price). This approach creates a significant product bottleneck:
1. **The Edge-Case Dropoff:** High-value listings that marginally miss a strict filter threshold (e.g., 5% over budget, 3 square meters smaller) are completely excluded.
2. **Lack of Holistic Utility:** Users must manually weigh trade-offs between location, price per square meter, amenities, and floor level.

This document specifies a two-stage retrieval and ranking engine tailored for an active dataset of approximately **10,000 rental listings**. It combines elastic boundary filtering, real estate market financial conversion mechanics, Multi-Attribute Utility Theory (MAUT), and dynamic weight extraction via Large Language Models (LLMs).

---

## 2. Two-Stage Funnel Architecture

To balance search recall with computational efficiency, the system implements a two-stage retrieval process:

* **Stage 1: Elastic Candidate Retrieval (Database Level)**
  Reduces the ~10,000 active listings down to a manageable candidate pool of 200–500 listings using relaxed bounds on soft constraints while strictly enforcing critical hard constraints.
* **Stage 2: Fine-Grained Utility Scoring & Ranking (Application/In-Memory Level)**
  Computes a normalized composite score ($S_{\text{total}} \in [0, 100]$) for each candidate listing based on personalized preference weights extracted from user conversation or inputs.

---

## 3. Stage 1: Elastic Candidate Retrieval & Confidence Intervals

### 3.1 Hard Constraints vs. Soft Constraints
* **Hard Constraints (Strict Filtering):** Binary requirements that cannot be compromised (e.g., geographical boundaries/cities, absolute requirement for an elevator when moving with a disabled family member, or explicit landlord policies like pet permissions).
* **Soft Constraints (Elastic Boundaries):** Criteria where users are typically flexible within a margin of negotiation or trade-off.

### 3.2 Mathematical Formulation of Confidence Margins ($\delta$)
Instead of querying exact user bounds $[A_{\min}, A_{\max}]$ and $[B_{\min}, B_{\max}]$, Stage 1 expands the search window by a configurable expansion factor $\delta$:

$$\text{Elastic Area Window} = \left[ A_{\min} \times (1 - \delta_A) \, , \, A_{\max} \times (1 + \delta_A) \right]$$

$$\text{Elastic Budget Window} = \left[ B_{\min} \times (1 - \delta_B) \, , \, B_{\max} \times (1 + \delta_B) \right]$$

* **Recommended Parameters for the Iranian Rental Market:**
  * $\delta_A = 0.08$ (8% tolerance on area).
  * $\delta_B = 0.15$ (15% tolerance on budget, reflecting standard negotiation room at closing).

---

## 4. Market Financial Modeling & Conversion Optimization

### 4.1 Total Equivalent Monthly Cost (TMC)
In markets with flexible deposit-to-rent conversions (such as the Iranian market), listings often have interchangeable deposit (*Vadieh*) and monthly rent (*Ejareh*). The standard market monthly conversion rate is denoted by $r$ (typically $r = 0.03$ or 30,000 Tomans per 1,000,000 Tomans of deposit).

The Total Equivalent Monthly Cost ($TMC$) unifies deposit ($D$) and monthly rent ($R$) into a single comparable financial metric:

$$TMC = R + (D \times r)$$

Similarly, the Total Full-Deposit Equivalent ($FDE$) is calculated as:

$$FDE = D + \frac{R}{r}$$

### 4.2 Handling Convertible Listings (*Ghabele Tabdil*)
When a listing allows conversion within bounds $[D_{\min\_prop}, D_{\max\_prop}]$, the engine finds the optimal point $(D^*, R^*)$ that minimizes the friction with the user's specific financial profile:

1. **Cash-Constrained User Profile (Low Deposit, High Income):**
   The algorithm shifts $(D^*, R^*)$ toward $D_{\min\_prop}$ to protect user liquidity.
2. **Income-Constrained User Profile (High Deposit, Fixed Monthly Budget):**
   The algorithm shifts $(D^*, R^*)$ toward $D_{\max\_prop}$ (Full Mortgage / *Rahn-e Kamel*) to minimize ongoing monthly overhead.

If a listing falls within the user's financial capacity only after conversion, it is retained; otherwise, an out-of-budget penalty is applied.

---

## 5. Stage 2: Multi-Attribute Utility Theory (MAUT) Scoring

Each listing in the candidate pool is evaluated across multiple sub-utility dimensions, yielding a final composite score:

$$S_{\text{total}} = \left( \sum_{k} w_k \cdot U_k \right) \times \prod P_{\text{penalties}}$$

Where:
* $w_k$ is the normalized weight of criterion $k$ ($\sum w_k = 1.0$).
* $U_k \in [0, 1]$ is the normalized sub-utility score for criterion $k$.
* $P_{\text{penalties}} \in (0, 1]$ represents composite penalty multipliers for sub-optimal properties.

### 5.1 Sub-Utility Formulations

#### 1. Financial Fit Utility ($U_{\text{financial}}$)
Evaluates how well the listing matches the user's target budget, applying exponential decay when exceeding the preferred limit into the confidence interval:

$$U_{\text{financial}} = 
\begin{cases} 
1.0 - 0.2 \left(\frac{TMC_{\text{prop}}}{TMC_{\text{user}}}\right) & \text{if } TMC_{\text{prop}} \le TMC_{\text{user}} \\
0.8 \times \exp\left(-\lambda \frac{TMC_{\text{prop}} - TMC_{\text{user}}}{TMC_{\text{user}}}\right) & \text{if } TMC_{\text{prop}} > TMC_{\text{user}} 
\end{cases}$$

*(Parameter $\lambda \approx 5.0$ enforces a steep decline in ranking for listings near the upper limit of the elastic boundary).*

#### 2. Value-for-Money Index Utility ($U_{\text{value}}$)
Evaluates whether a property is priced below the average market rate of its specific neighborhood:

$$\text{VMI} = \frac{\text{Neighborhood\_Avg\_TMC\_Per\_Sqm}}{\left(\frac{TMC_{\text{prop}}}{\text{Area}_{\text{prop}}}\right)}$$

$$U_{\text{value}} = \min\left(1.0 \, , \, \frac{\text{VMI}}{1.2}\right)$$

A listing priced below the neighborhood average yields $\text{VMI} > 1.0$, boosting its competitive ranking.

#### 3. Area Utility ($U_{\text{area}}$)
Applies a concave marginal utility curve centered around the user's ideal area:

$$U_{\text{area}} = \max\left(0.0 \, , \, 1.0 - \left| \frac{\text{Area}_{\text{prop}} - \text{Area}_{\text{ideal}}}{\text{Area}_{\text{ideal}}} \right|^{1.5} \right)$$

#### 4. Amenity Utility ($U_{\text{amenity}}$)
Calculates a weighted linear combination of available amenities:

$$U_{\text{amenity}} = \sum_{i} \alpha_i \cdot I_i$$

Where $I_i \in \{0, 1\}$ indicates the presence of an amenity, and $\alpha_i$ represents market importance weights:
* Parking: $\alpha = 0.40$
* Elevator: $\alpha = 0.35$
* Storage Unit (*Anbari*): $\alpha = 0.15$
* Balcony: $\alpha = 0.10$

#### 5. Conditional Structural Penalties ($P_{\text{penalties}}$)
Applies non-linear penalties for unfavorable combinations:
* **High Floor without Elevator:** If $\text{Floor} \ge 3$ and $\text{Has\_Elevator} = \text{False}$, apply $P_{\text{floor}} = 0.50$.
* **Low Light / Basement Unit:** If $\text{Floor} < 0$, apply $P_{\text{basement}} = 0.80$.

---

## 6. LLM Conversational Preference & Weight Extraction

The conversational AI interface parses natural language dialogue to construct a structured preference payload.

### 6.1 Extracted Target Schema
The LLM extracts a structured JSON containing:
1. **Hard Constraints:** Explicit non-negotiables (neighborhood names, minimum bedroom count, strict amenity mandates).
2. **Financial Persona:** Maximum available deposit, maximum monthly cash flow, and trade-off orientation (`prefer_higher_rent`, `prefer_higher_deposit`, or `balanced`).
3. **Dynamic Weight Vector ($W$):** A normalized set of weights ($w_{\text{budget}}, w_{\text{value}}, w_{\text{area}}, w_{\text{amenities}}, w_{\text{freshness}}$) reflecting explicit and implicit user priorities.

### 6.2 Context-to-Weight Mapping Rules
* Statements emphasizing budget urgency (e.g., *"I have limited savings, cannot afford high deposit"*) increase $w_{\text{budget}}$ to $\ge 0.40$ and set persona to `prefer_higher_rent`.
* Statements emphasizing spaciousness for families increase $w_{\text{area}}$ to $\ge 0.35$ while lowering $w_{\text{freshness}}$ and building age sensitivity.
* Statements prioritizing deal quality or investment efficiency boost $w_{\text{value}}$.

---

## 7. Performance Optimization & Latency Reduction Best Practices (~10,000 Listings Scale)

For a dataset of ~10,000 active listings, high-throughput, sub-50ms response times can be achieved with targeted optimizations:

### 7.1 In-Memory Candidate Filtering & Vectorized Scoring
* **Complete In-Memory Representation:** 10,000 listings occupy only 5–15 MB of RAM. Rather than making heavy, repeated database queries for the ranking phase, load essential listing attributes into an in-memory cache (e.g., Redis, or internal memory structures using columnar arrays/typed buffers).
* **Vectorized Array Operations:** Compute sub-utility equations ($U_{\text{financial}}, U_{\text{area}}, U_{\text{amenity}}$) across the filtered candidate slice (200–500 items) using vectorized operations or SIMD-accelerated array iterations, reducing score calculation time to under 5 milliseconds.

### 7.2 Precomputation and Caching of Aggregates
* **Neighborhood Price Baselines:** Precompute the median and mean price per square meter ($\text{TMC}/\text{m}^2$) for every neighborhood asynchronously on an hourly or daily schedule. Store these baseline values in an in-memory Key-Value store. Do not compute neighborhood averages at query time.
* **Pre-calculated Amenity Bitmasks:** Store binary amenities (parking, elevator, storage, balcony) as a single integer bitmask per listing. Amenity matching can then be performed using fast bitwise operations.

### 7.3 Database Indexing Strategy (Stage 1 Acceleration)
* **Compound B-Tree Indexes:** Create composite indexes on `(city_id, neighborhood_id, total_monthly_cost, area)` to make Stage 1 range scans extremely fast.
* **Spatial Indexing:** For map-based radius searches, use dedicated spatial indexes (such as PostGIS `GIST` indexing) to retrieve listings within geographic polygons prior to candidate ranking.

### 7.4 Decoupling LLM Inference from the Ranking Pipeline
* **Asynchronous Intent Extraction:** Run the LLM weight extraction step asynchronously. When a user sends a message, extract and update the user's preference state in cache.
* **Cached Session Vectors:** The ranking and filtering engine consumes the pre-parsed preference vector directly from the session cache, preventing the latency of LLM text generation (often 500ms–2000ms) from blocking the listing search and ranking endpoint.