"""app.data.database.migrate -- gaining a flag without re-crawling.

A corpus takes hours to build, so a new classifier has to be applied to the
rows already stored. Both migrations feed the one ``is_shared_living`` column:
the column itself, and the later discovery that parking spaces are let under
the same Divar category as apartments.
"""

import json
import sqlite3

import pytest

from app.data.database import migrate

PARKING = {"title": "اجاره پارکینگ مسقف", "description": "درب ریموت‌دار"}
FLATMATE = {"title": "هم‌خانه خانم نیازمندیم", "description": ""}
APARTMENT = {"title": "آپارتمان ۸۵ متری دو خوابه", "description": "دارای پارکینگ و انباری"}


def _db(*payloads, with_column: bool) -> sqlite3.Connection:
    """A stored corpus, either at the current schema or before the flag existed."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    column = ", is_shared_living INTEGER NOT NULL DEFAULT 0" if with_column else ""
    connection.execute(
        "CREATE TABLE listings (id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
        f"effective_monthly_cost INTEGER NOT NULL DEFAULT 0{column})"
    )
    connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for index, payload in enumerate(payloads):
        connection.execute("INSERT INTO listings (id, payload) VALUES (?, ?)", (str(index), json.dumps(payload)))
    return connection


def _flagged(connection) -> set[str]:
    return {row["id"] for row in connection.execute("SELECT id FROM listings WHERE is_shared_living = 1")}


def test_a_database_predating_the_column_gains_it_filled(): 
    connection = _db(PARKING, FLATMATE, APARTMENT, with_column=False)
    assert migrate(connection) == 2
    assert _flagged(connection) == {"0", "1"}


def test_a_database_that_only_missed_the_parking_rule_is_topped_up():
    """The realistic case: the column is there and the flatmate adverts are
    already flagged, but the parking ones were filed as ordinary flats."""
    connection = _db(PARKING, FLATMATE, APARTMENT, with_column=True)
    connection.execute("UPDATE listings SET is_shared_living = 1 WHERE id = '1'")
    assert migrate(connection) == 1
    assert _flagged(connection) == {"0", "1"}


def test_migrating_twice_changes_nothing():
    """It records itself in `meta`: re-flagging on every open would be
    harmless but would read every payload each time the corpus is written to."""
    connection = _db(PARKING, APARTMENT, with_column=True)
    assert migrate(connection) == 1
    assert migrate(connection) == 0
    assert _flagged(connection) == {"0"}


def test_an_already_flagged_row_is_not_re_examined():
    connection = _db(APARTMENT, with_column=True)
    connection.execute("UPDATE listings SET is_shared_living = 1")
    assert migrate(connection) == 0
    assert _flagged(connection) == {"0"}


def test_a_fresh_database_has_nothing_to_migrate():
    """No table yet: the schema script creates it with the column in place and
    enrichment flags every row on the way in."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    assert migrate(connection) == 0
