from collections import defaultdict
import copy
import difflib
import json
import re


def normalize_fa(text: str) -> str:
    """Standardize Persian/Arabic characters and whitespace."""
    if not text:
        return ""
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    text = text.replace("\u200c", " ")
    text = re.sub(r"\(.*?\)", "", text)  # remove parenthesized terms
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(محله|منطقه|خیابان|شهرک)\b", "", text)
    return " ".join(text.split()).strip()


def run_matcher_with_deduplication(
    geojson_path="tehran_neighborhoods.geojson",
    divar_json_path="neighborhoods.json",
):
    # 1. Load files
    with open(geojson_path, "r", encoding="utf-8") as f:
        geo_data = json.load(f)

    with open(divar_json_path, "r", encoding="utf-8") as f:
        divar_data = json.load(f)

    # Index GeoJSON polygons by normalized name
    geo_lookup = {}
    for feat in geo_data.get("features", []):
        raw_name = feat.get("properties", {}).get("name", "")
        norm_name = normalize_fa(raw_name)
        if norm_name:
            geo_lookup[norm_name] = feat

    kml_names_list = list(geo_lookup.keys())

    divar_children = divar_data.get("children", divar_data)

    # 2. First Pass: Find potential matches for each Divar item
    initial_unmatched = []
    # polygon_name -> list of (divar_item_data, matched_geo_feature)
    polygon_groups = defaultdict(list)

    for item in divar_children:
        data = item.get("data", item)
        divar_title = data.get("title", "")
        divar_subtitle = data.get("subtitle", "")
        norm_title = normalize_fa(divar_title)

        matched_feature = None

        # A. Exact title match
        if norm_title in geo_lookup:
            matched_feature = geo_lookup[norm_title]

        # B. Substring matching
        if not matched_feature:
            for kml_norm, feat in geo_lookup.items():
                if (len(kml_norm) > 3 and kml_norm in norm_title) or (
                    len(norm_title) > 3 and norm_title in kml_norm
                ):
                    matched_feature = feat
                    break

        # C. Fuzzy matching (80% similarity threshold)
        if not matched_feature:
            matches = difflib.get_close_matches(
                norm_title, kml_names_list, n=1, cutoff=0.80
            )
            if matches:
                matched_feature = geo_lookup[matches[0]]

        # D. Subtitle keyword check
        if not matched_feature and divar_subtitle:
            norm_subtitle = normalize_fa(divar_subtitle)
            for kml_norm, feat in geo_lookup.items():
                if len(kml_norm) > 3 and kml_norm in norm_subtitle:
                    matched_feature = feat
                    break

        if matched_feature:
            kml_name = matched_feature.get("properties", {}).get("name", "")
            polygon_groups[kml_name].append((data, matched_feature))
        else:
            initial_unmatched.append(data)

    # 3. Second Pass: Collision Resolution (Deduplication)
    final_paired_divar = []
    final_geojson_features = []
    final_unmatched = list(initial_unmatched)

    for kml_name, matches in polygon_groups.items():
        norm_kml = normalize_fa(kml_name)

        if len(matches) == 1:
            # Single match: keep it
            data, feat = matches[0]
            _add_to_final(
                data,
                feat,
                kml_name,
                final_paired_divar,
                final_geojson_features,
            )

        else:
            # Multiple Divar items claimed the same polygon
            exact_matches = []
            non_exact_matches = []

            for data, feat in matches:
                norm_title = normalize_fa(data.get("title", ""))
                if norm_title == norm_kml:
                    exact_matches.append((data, feat))
                else:
                    non_exact_matches.append(data)

            if len(exact_matches) == 1:
                # Rule: Keep the exact match, discard the others
                winning_data, winning_feat = exact_matches[0]
                _add_to_final(
                    winning_data,
                    winning_feat,
                    kml_name,
                    final_paired_divar,
                    final_geojson_features,
                )
                final_unmatched.extend(non_exact_matches)

            else:
                # Rule: If none match exactly (or ambiguous), remove ALL matches
                for data, _ in matches:
                    final_unmatched.append(data)

    # 4. Save Output Files

    # File 1: matched_neighborhoods.geojson
    matched_geojson_output = {
        "type": "FeatureCollection",
        "features": final_geojson_features,
    }
    with open("matched_neighborhoods.geojson", "w", encoding="utf-8") as f:
        json.dump(matched_geojson_output, f, ensure_ascii=False, indent=2)

    # File 2: paired_neighborhoods.json
    paired_json_output = {
        "total": len(final_paired_divar),
        "children": [{"data": item} for item in final_paired_divar],
    }
    with open("paired_neighborhoods.json", "w", encoding="utf-8") as f:
        json.dump(paired_json_output, f, ensure_ascii=False, indent=2)

    # File 3: unmatched_neighborhoods.json
    unmatched_json_output = {
        "total": len(final_unmatched),
        "children": [{"data": item} for item in final_unmatched],
    }
    with open("unmatched_neighborhoods.json", "w", encoding="utf-8") as f:
        json.dump(unmatched_json_output, f, ensure_ascii=False, indent=2)

    # 5. Print Summary
    print("=========================================")
    print(f"Total Divar Items:       {len(divar_children)}")
    print(f"Unique Polygons Mapped:  {len(final_paired_divar)}")
    print(f"Total Unmatched Items:   {len(final_unmatched)}")
    print("=========================================")
    print("All 3 files updated successfully.")


def _add_to_final(
    data, feat, kml_name, final_paired_divar, final_geojson_features
):
    divar_title = data.get("title", "")
    divar_key = data.get("key", "")
    divar_subtitle = data.get("subtitle", "")
    divar_keywords = data.get("search_keywords", "")

    # Create paired item
    final_paired_divar.append(
        {
            "key": divar_key,
            "title": divar_title,
            "subtitle": divar_subtitle,
            "search_keywords": divar_keywords,
            "matched_polygon_name": kml_name,
        }
    )

    # Create GeoJSON feature with divar key attached
    new_feat = copy.deepcopy(feat)
    new_feat["properties"] = {
        "key": divar_key,
        "title": divar_title,
        "kml_name": kml_name,
        "search_keywords": divar_keywords,
        "subtitle": divar_subtitle,
    }
    final_geojson_features.append(new_feat)


if __name__ == "__main__":
    run_matcher_with_deduplication()