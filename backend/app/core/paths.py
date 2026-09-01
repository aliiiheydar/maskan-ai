"""Where things live on disk.

Every module that reads a data file used to spell its location out for itself
-- ``Path(__file__).resolve().parent.parent / "data"`` appears nine times
across app/spatial, app/core and app/llm -- so one fact about the layout was
written down nine times and could only be changed by grepping for it. They all
ask here instead, which makes moving the corpus a one-line edit.

The layout the constants describe: code and the data it reads are separate.
``app/data/`` holds the modules (the SQLite gateway, the repository, the
offline pipelines under ``pipelines/``), and ``app/data/assets/`` holds the
JSON, GeoJSON, KML and SQLite files they load -- curated sources, pipeline
output, and runtime caches alike.
"""

from pathlib import Path

#: ``backend/`` -- the Python project root, what uvicorn is started from.
BACKEND_DIR: Path = Path(__file__).resolve().parents[2]

#: The repository root. The crawler's output sits beside ``backend/``, not
#: inside it, so anything reaching for it starts here.
PROJECT_ROOT: Path = BACKEND_DIR.parent

#: ``backend/app/`` -- the importable package.
APP_DIR: Path = BACKEND_DIR / "app"

#: Every data file the application reads at runtime or a pipeline writes.
ASSETS_DIR: Path = APP_DIR / "data" / "assets"

#: Scraped sources kept exactly as they arrived, so a rebuild never depends on
#: re-running the scrape. Only the pipelines read these.
RAW_ASSETS_DIR: Path = ASSETS_DIR / "raw"


def asset(*parts: str) -> Path:
    """Path to a data file, e.g. ``asset("tehran.geojson")``."""
    return ASSETS_DIR.joinpath(*parts)
