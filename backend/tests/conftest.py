"""Test-suite isolation from local dev secrets.

The app lifespan seeds 1000 synthetic listings and embeds each one through
app.state.llm_client at startup. If backend/.env holds a real OpenRouter key
(needed for live/manual dev use), importing app.main during test collection
would otherwise make ~1000 real network calls before a single test runs.
Forcing the placeholder key here keeps the test suite on the local mock
embedding path -- fast, deterministic, fully offline -- regardless of what
the developer has configured for live use. Must run before app.main (and
therefore app.core.config.settings) is imported by any test module, which
module-level code in a conftest.py guarantees.
"""

import os

# Both providers, since chat completions and embeddings now read different
# keys (see app.core.config): leaving either one real would put part of the
# suite back on the network.
os.environ["OPENROUTER_API_KEY"] = "your_openrouter_api_key_here"
