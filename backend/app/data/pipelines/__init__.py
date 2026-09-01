"""Offline builders: everything that turns a raw source into an asset.

Nothing in here is imported by the API. These modules run once, by hand or
from backend/scripts, and their output lands in ``app/data/assets/`` for the
runtime side of this package (``database``, ``repository``) to read. Keeping
them apart is what makes that readable: the request path and the build path
were previously the same directory, so a module's cost -- an Overpass round
trip, a full re-parse of the crawl -- said nothing about whether a search
paid it.
"""
