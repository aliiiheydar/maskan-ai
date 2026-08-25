"""Builds app/data/tehran_transit_nodes.json from the raw scraped sources in
app/data/raw/ (real Tehran Metro station data + real BRT corridor route data).

Run with:
    python scripts/build_transit_data.py

Output node schema (list[dict], see app/spatial/transit.py):
    {
        "id": str,                 # stable slug, unique across metro+brt
        "name": str,                # Persian display name
        "name_en": str | None,      # English name (metro only; None for BRT)
        "lat": float,
        "lon": float,
        "type": "metro" | "brt",
        "lines": list[str],         # e.g. ["1"] or ["1", "3"] for interchanges
        "has_elevator": bool,
        "relations": list[str],     # adjacent station ids on the network graph
    }

Metro: 150 real stations across Lines 1-7 (incl. interchange stations that
belong to multiple lines), sourced from a metro station dataset that includes
a real adjacency graph (`relations`) and accessibility data (`elevator`).

BRT: 10 real corridors sourced from route-ordered stop lists. The raw data
lists each corridor's stops independently, so the same physical stop can
appear multiple times (once per corridor it serves). Physical stops are
merged by geographic proximity (<150m) into single nodes carrying multiple
`lines`, and `relations` are derived from each corridor's stop order (real
route adjacency, not a distance heuristic).
"""

import json
import math
import re
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "app" / "data" / "raw"
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "tehran_transit_nodes.json"

BRT_MERGE_RADIUS_KM = 0.15


def _slugify(name: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{prefix}-{slug}" if slug else prefix


def _unique_id(base: str, taken: set[str]) -> str:
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_metro_nodes() -> tuple[list[dict], dict[str, str]]:
    raw: dict[str, dict] = json.loads((RAW_DIR / "metro_stations_raw.json").read_text(encoding="utf-8"))

    taken_ids: set[str] = set()
    name_to_id: dict[str, str] = {}
    nodes: list[dict] = []

    for key, station in raw.items():
        node_id = _unique_id(_slugify(key, "metro"), taken_ids)
        name_to_id[key] = node_id
        nodes.append(
            {
                "id": node_id,
                "name": station["translations"]["fa"],
                "name_en": station["name"],
                "lat": station["latitude"],
                "lon": station["longitude"],
                "type": "metro",
                "lines": [str(line) for line in station["lines"]],
                "has_elevator": bool(station.get("elevator")),
                "relations": list(station["relations"]),  # names for now, resolved to ids below
            }
        )

    for node in nodes:
        node["relations"] = sorted({name_to_id[r] for r in node["relations"] if r in name_to_id})

    # The source adjacency isn't perfectly symmetric (a handful of stations
    # list a neighbor that doesn't list them back) -- mirror edges so the
    # graph is a well-formed undirected station network.
    by_id = {n["id"]: n for n in nodes}
    for node in nodes:
        for neighbor_id in node["relations"]:
            neighbor = by_id[neighbor_id]
            if node["id"] not in neighbor["relations"]:
                neighbor["relations"].append(node["id"])
    for node in nodes:
        node["relations"].sort()

    return nodes, name_to_id


def build_brt_nodes() -> list[dict]:
    raw: list[dict] = json.loads((RAW_DIR / "brt_lines_raw.json").read_text(encoding="utf-8"))

    nodes: list[dict] = []
    # Station names are Persian-only (no ASCII transliteration available), so
    # ids follow the corridor-local sequence they were first observed on:
    # "brt-{corridor}-{seq:02d}", matching the readable id scheme used for
    # metro nodes instead of a meaningless numeric fallback.
    per_corridor_seq: dict[str, int] = {}
    # sequence[(corridor, stop_index)] -> merged node index, so we can derive
    # route-order adjacency (relations) per corridor after merging duplicates.
    sequence: list[list[int]] = []

    for entry in raw:
        corridor = entry["line"].replace("خط", "").strip()
        line_node_indices: list[int] = []

        for stop in entry["stations"]:
            lat, lon = stop["coordinates"]["lat"], stop["coordinates"]["lng"]

            merged_idx = None
            for idx, node in enumerate(nodes):
                if _haversine_km(lat, lon, node["lat"], node["lon"]) <= BRT_MERGE_RADIUS_KM:
                    merged_idx = idx
                    break

            if merged_idx is None:
                per_corridor_seq[corridor] = per_corridor_seq.get(corridor, 0) + 1
                node_id = f"brt-{corridor}-{per_corridor_seq[corridor]:02d}"
                nodes.append(
                    {
                        "id": node_id,
                        "name": stop["name"],
                        "name_en": None,
                        "lat": lat,
                        "lon": lon,
                        "type": "brt",
                        "lines": [corridor],
                        "has_elevator": False,
                        "relations": [],
                    }
                )
                merged_idx = len(nodes) - 1
            else:
                if corridor not in nodes[merged_idx]["lines"]:
                    nodes[merged_idx]["lines"].append(corridor)

            line_node_indices.append(merged_idx)

        sequence.append(line_node_indices)

    for line_node_indices in sequence:
        for a, b in zip(line_node_indices, line_node_indices[1:]):
            if a == b:
                continue
            id_a, id_b = nodes[a]["id"], nodes[b]["id"]
            if id_b not in nodes[a]["relations"]:
                nodes[a]["relations"].append(id_b)
            if id_a not in nodes[b]["relations"]:
                nodes[b]["relations"].append(id_a)

    for node in nodes:
        node["relations"].sort()
        node["lines"].sort()

    return nodes


def main() -> None:
    metro_nodes, _ = build_metro_nodes()
    brt_nodes = build_brt_nodes()
    all_nodes = metro_nodes + brt_nodes

    ids = [n["id"] for n in all_nodes]
    assert len(ids) == len(set(ids)), "duplicate node ids produced"

    OUT_PATH.write_text(json.dumps(all_nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(all_nodes)} nodes ({len(metro_nodes)} metro, {len(brt_nodes)} brt) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
