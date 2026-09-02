# Testing

```bash
cd backend  && pytest -q                 # 147 tests, ~23s
cd frontend && npm test                  # 34 tests, <1s
cd frontend && npx tsc --noEmit          # typecheck
cd frontend && npx next lint --dir src   # lint
```

**Do not run `npm run build` while `next dev` is running.** They share
`.next/` and the build corrupts the dev server's cache. `npx tsc --noEmit` is
the check you want during development.

---

## 1. Backend — `backend/tests/`

Flat, one file per subject, `pytest` + `pytest-asyncio` + `httpx.AsyncClient`.
The API tests run against the **real corpus** through the real app, not a
fixture: a synthetic-only suite cannot catch the kind of thing that actually
breaks here, which is a Persian string that does not match or a filter that
silently returns the whole city.

| File | | Covers |
| :-- | --: | :-- |
| `test_api.py` | 25 | Every endpoint end-to-end: response shape, ranking order, filter enforcement, pagination, the 503s when no key is configured |
| `test_scoring.py` | 33 | Tabdil resolution, the hard mask, each sub-utility, penalties, weight resolution, the Pareto sweep, the trade-off sentence |
| `test_shared_living.py` | 37 | The room/bed/flatmate and parking classifiers — and, as importantly, the apartments they must **not** match |
| `test_clustering.py` | 10 | Server-side map clustering: counts add up, cells cover the viewport |
| `test_isochrone.py` | 8 | Reachability geometry for all three modes |
| `test_spatial.py` | 10 | Distance, walk time, transit routing, congestion penalty |
| `test_pricing.py` | 8 | Tabdil arithmetic |
| `test_normalizer.py` | 6 | Persian character and digit normalisation |
| `test_migration.py` | 6 | Gaining a column and a re-run classifier without re-crawling |
| `test_intent.py` | 4 | Intent extraction against a mocked LLM |

### What the tests are for

The interesting half of this suite is the negative cases, and they are
deliberately documented as such in the test files.

**A classifier's false positives cost more than its false negatives.** A home
wrongly filed as parking disappears from the search it belongs in; parking
wrongly left in merely looks cheap. So `test_shared_living.py` carries a long
list of titles that must *not* match — «آپارتمان ۷۰ متری با پارکینگ و انباری»,
«۷۰متر پارکینگدار عربی», «افسریه والفجر با پارکینگ» — alongside the ones that
must.

**Rules were measured before they were written.** Every candidate pattern in
that module was run over all 21,377 stored adverts and every new match and
every drop inspected by hand. The tests then pin the result, so a later
"simplification" of a regex cannot quietly re-admit three hundred apartments.

**Mandatory cases carried over from the specification:**

| Deposit | Rent | Effective monthly cost |
| --: | --: | --: |
| 100,000,000 | 0 (رهن کامل) | 3,000,000 |
| 0 | 15,000,000 | 15,000,000 |
| 200,000,000 | 10,000,000 | 16,000,000 |
| 500,000,000 | 25,000,000 | 40,000,000 |

* A 4th-floor flat with `has_elevator = False` is **not** pruned when
  `must_have_elevator = True` — it is scored down by the elevator penalty. A
  walk-up is a matter of degree.
* A ground-floor unit with no lift is **not** marked down at all: it scores
  exactly as if it had one, including for the امکانات credit.
* A listing whose effective cost exceeds `1.20 × C_target` **is** pruned.
* `"آپارتمان در يوسف اباد با كمد ديواري و ۱۲۳ متر"` normalises to
  `"آپارتمان در یوسف اباد با کمد دیواری و 123 متر"`.

### Migrations

`test_migration.py` guards the thing that is easy to get wrong about a corpus
that took hours to build: a new classifier has to reach rows already stored.
It covers gaining the column, topping up rows the old rule missed, being
idempotent on a second run — and **re-running when the rule's revision
changes**, which is what stops a database stamped under an older parking rule
from skipping the widened one.

---

## 2. Frontend — `vitest`

| File | Covers |
| :-- | :-- |
| `store/useSearchStore.test.ts` | Capability gating, `setMode` semantics, what the search request actually contains, paging, error handling |
| `lib/matchColor.test.ts` | The shared match scale |
| `lib/format.test.ts` | Persian number and price formatting |

The store tests are where the mode invariants live: that swapping between the
two ranked modes preserves results, scroll, selection and map bounds and
issues **no** request; that entering map-explore clears; that leaving it
searches; that the conversational mode still sends `mode: "ranked"`.

---

## 3. Intent evaluation — `backend/evals/`

`python -m evals.intent_eval` measures Persian intent extraction against a
labelled set, in two ways because the task has two kinds of output: exact
match on the structured fields (a budget is right or it is not) and a looser
judgement on the soft-preference summary. It is a **measurement**, not a
gate — it costs API calls and is run deliberately, not in the test suite.

---

## 4. Live checks

Some things only fail in a browser: a map layer that never paints, a panel
that re-searches on mount, an RTL layout that hangs a few pixels off the far
edge. Those are verified against the running dev servers, and the invariants
they protect are written down in the source comments beside the code that
would otherwise regress — which is where they belong, because the next person
to touch that line is the one who needs them.
