import json
import xml.etree.ElementTree as ET


def parse_kml_neighborhoods(kml_path):
    tree = ET.parse(kml_path)
    root = tree.getroot()

    # KML namespaces
    namespaces = {"kml": "http://www.opengis.net/kml/2.2"}

    features = []

    # Find all Placemarks in the file
    for placemark in root.findall(".//kml:Placemark", namespaces):
        # 1. Get the neighborhood name
        name_elem = placemark.find("kml:name", namespaces)
        name = name_elem.text.strip() if name_elem is not None else "Unknown"

        # 2. Look for Polygon coordinates
        coords_elem = placemark.find(".//kml:coordinates", namespaces)
        if coords_elem is None or not coords_elem.text:
            continue

        raw_coords = coords_elem.text.strip().split()
        ring = []
        for coord_str in raw_coords:
            parts = coord_str.split(",")
            if len(parts) >= 2:
                lon = float(parts[0])
                lat = float(parts[1])
                ring.append([lon, lat])

        if ring:
            # Build GeoJSON feature
            feature = {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],  # outer boundary
                },
            }
            features.append(feature)

    return {"type": "FeatureCollection", "features": features}


# Usage:
geojson_data = parse_kml_neighborhoods("tehran_districts-Final.kml")

# Save as standard GeoJSON
with open("tehran_neighborhoods.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson_data, f, ensure_ascii=False, indent=2)

print(f"Extracted {len(geojson_data['features'])} neighborhood polygons.")