"""Storage and the data behind it.

    database.py             SQLite gateway -- schema, build, upsert, queries
    repository.py           the in-process corpus the API ranks against
    synthetic_generator.py  a stand-in corpus when no database has been built
    price_plausibility.py   the price floors that keep placeholder ads out
    pipelines/              offline builders; never imported by the API
    assets/                 every data file the above read or write
    seed/                   the corpus as it ships, compressed (see paths.SEED_DIR)

The split between the last two and the rest is the one worth keeping: a module
at this level runs while a user waits, and anything under ``pipelines/`` runs
once, by hand, to produce a file in ``assets/``. Paths into ``assets/`` come
from ``app.core.paths`` rather than being spelled out per module.
"""
