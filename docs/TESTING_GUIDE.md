# Testing Strategy & Verification Harness

## 1. Test Architecture

Every pull request or implementation phase must pass three layers of automated tests:
1. **Unit Tests (`tests/unit/`)**: Pure functions for Persian normalization, Tabdil calculations, distance math, and scoring logic.
2. **Integration Tests (`tests/integration/`)**: OpenRouter client mocking, intent extraction parsing, and repository filtering.
3. **End-to-End API Tests (`tests/e2e/`)**: FastAPI endpoints via `httpx.AsyncClient`.

---

## 2. Mandatory Test Cases

### 2.1 Tabdil Calculation Matrix (`test_pricing.py`)
| Input Deposit | Input Rent | Expected Effective Monthly Cost |
| :--- | :--- | :--- |
| `100,000,000` | `0` (رهن کامل) | `3,000,000` |
| `0` | `15,000,000` (اجاره کامل)| `15,000,000` |
| `200,000,000` | `10,000,000` | `16,000,000` |
| `500,000,000` | `25,000,000` | `40,000,000` |

### 2.2 Hard Constraint Enforcement Matrix (`test_scoring.py`)
* Test that a 4th-floor apartment with `has_elevator=False` returns `Utility = 0` when `must_have_elevator=True`.
* Test that a ground-floor unit (`floor=0`) with `has_elevator=False` is NOT pruned when `must_have_elevator=True`.
* Test that a listing with $C_{\text{eff}} > 1.25 \times C_{\text{target}}$ is pruned.

### 2.3 Persian String Normalization Matrix (`test_normalizer.py`)
* Input: `"آپارتمان در يوسف اباد با كمد ديواري و ۱۲۳ متر"`
* Expected: `"آپارتمان در یوسف آباد با کمد دیواری و 123 متر"` (Arabic characters and Persian digits normalized).

---

## 3. Running Test Suites

```bash
# Run all unit and integration tests
pytest -v

# Run with test coverage report
pytest --cov=app --cov-report=term-missing

# Run only spatial distance tests
pytest tests/unit/test_spatial.py -v
