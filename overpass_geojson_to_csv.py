import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

HEADERS = [
    "#",
    "OSM ID",
    "Latitude",
    "Longitude",
    "Google Maps",
    "Google Street View",
    "Checked",
]


def pick_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        raise SystemExit(
            "Please supply a file: python overpass_geojson_to_csv_fixed.py export.geojson"
        )

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    filename = filedialog.askopenfilename(
        title="Select an Overpass Turbo GeoJSON export",
        filetypes=[("GeoJSON", "*.geojson *.json"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(filename) if filename else None


def notify(message, error=False):
    print(message, file=sys.stderr if error else sys.stdout)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        (messagebox.showerror if error else messagebox.showinfo)(
            "Overpass GeoJSON to Google Sheets", message
        )
        root.destroy()
    except Exception:
        pass


def parse_lon_lat(coordinates):
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (ValueError, TypeError, OverflowError):
        return None
    if not (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        return None
    return longitude, latitude


def line_midpoint(coordinates):
    points = [parse_lon_lat(p) for p in coordinates] if isinstance(coordinates, list) else []
    points = [p for p in points if p is not None]
    if not points:
        return None
    if len(points) == 1:
        return points[0]

    segments = []
    total = 0.0
    for p1, p2 in zip(points, points[1:]):
        latitude_scale = math.cos(math.radians((p1[1] + p2[1]) / 2))
        distance = math.hypot((p2[0] - p1[0]) * latitude_scale, p2[1] - p1[1])
        segments.append(distance)
        total += distance
    if not total:
        return points[0]

    half = total / 2
    traveled = 0.0
    for i, distance in enumerate(segments):
        if traveled + distance >= half:
            fraction = (half - traveled) / distance if distance else 0
            p1, p2 = points[i], points[i + 1]
            return (p1[0] + fraction * (p2[0] - p1[0]),
                    p1[1] + fraction * (p2[1] - p1[1]))
        traveled += distance
    return points[-1]


def polygon_centroid(rings):
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        return None
    points = [parse_lon_lat(p) for p in rings[0]]
    points = [p for p in points if p is not None]
    if not points:
        return None
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if not points:
        return None
    
    origin_lon, origin_lat = points[0]
    relative = [(lon - origin_lon, lat - origin_lat) for lon, lat in points]
    twice_area = 0.0
    centroid_lon = 0.0
    centroid_lat = 0.0
    for p1, p2 in zip(relative, relative[1:] + relative[:1]):
        cross = p1[0] * p2[1] - p2[0] * p1[1]
        twice_area += cross
        centroid_lon += (p1[0] + p2[0]) * cross
        centroid_lat += (p1[1] + p2[1]) * cross
    if abs(twice_area) > 1e-15:
        return (origin_lon + centroid_lon / (3 * twice_area),
                origin_lat + centroid_lat / (3 * twice_area))
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def geometry_point(geometry):
    if not isinstance(geometry, dict):
        return None
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")

    if geom_type == "Point":
        return parse_lon_lat(coords)
    if geom_type == "MultiPoint":
        pts = [parse_lon_lat(p) for p in coords] if isinstance(coords, list) else []
        pts = [p for p in pts if p is not None]
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    if geom_type == "LineString":
        return line_midpoint(coords)
    if geom_type == "MultiLineString" and isinstance(coords, list):
        def line_length(line):
            pts = [parse_lon_lat(p) for p in line] if isinstance(line, list) else []
            pts = [p for p in pts if p is not None]
            return sum(math.hypot((b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2)),
                                  b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        if coords:
            return line_midpoint(max(coords, key=line_length))
    if geom_type == "Polygon":
        return polygon_centroid(coords)
    if geom_type == "MultiPolygon" and isinstance(coords, list):
        def bbox_area(poly):
            pts = [parse_lon_lat(p) for p in poly[0]] if isinstance(poly, list) and poly and isinstance(poly[0], list) else []
            pts = [p for p in pts if p is not None]
            if not pts:
                return 0
            return (max(p[0] for p in pts) - min(p[0] for p in pts)) * (max(p[1] for p in pts) - min(p[1] for p in pts))
        if coords:
            return polygon_centroid(max(coords, key=bbox_area))
    if geom_type == "GeometryCollection":
        for sub_geometry in geometry.get("geometries") or []:
            point = geometry_point(sub_geometry)
            if point:
                return point
    return None


def point_rows(geojson):
    if not isinstance(geojson, dict):
        raise ValueError("This isn't a valid GeoJSON FeatureCollection.")
    features = geojson.get("features")
    if geojson.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("This isn't a valid GeoJSON FeatureCollection.")

    seen_ids = set()
    skipped = Counter()
    rows = []

    for feature in features:
        if not isinstance(feature, dict):
            skipped["Invalid feature"] += 1
            continue

        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        osm_ref = str(properties.get("@id") or feature.get("id") or "")
        parts = osm_ref.split("/", 1)
        if len(parts) != 2 or parts[0] not in {"node", "way", "relation"} or not parts[1].isdecimal():
            skipped["Missing/invalid OSM ID"] += 1
            continue
        if osm_ref in seen_ids:
            skipped["Duplicate OSM ID"] += 1
            continue

        point = geometry_point(feature.get("geometry"))
        if point is None:
            skipped["Missing/invalid geometry"] += 1
            continue
        longitude, latitude = point
        if not (math.isfinite(longitude) and math.isfinite(latitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            skipped["Invalid representative coordinates"] += 1
            continue

        lat_text, lon_text = format(latitude, ".15g"), format(longitude, ".15g")
        google_maps = (
            f"https://www.google.com/maps/search/?api=1&query={lat_text}%2C{lon_text}"
        )
        street_view = (
            "https://www.google.com/maps/@?api=1&map_action=pano"
            f"&viewpoint={lat_text}%2C{lon_text}"
        )

        seen_ids.add(osm_ref)
        rows.append([
            len(rows) + 1, osm_ref, lat_text, lon_text,
            google_maps, street_view, "FALSE"
        ])

    return rows, skipped


def convert(source):
    with source.open("r", encoding="utf-8-sig") as handle:
        geojson = json.load(handle)

    rows, skipped = point_rows(geojson)
    if not rows:
        details = ", ".join(f"{reason}: {count}" for reason, count in skipped.items())
        raise ValueError(f"No usable OSM features found in this export. {details}")

    destination = source.with_name(source.stem + "_google_sheets.csv")
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)

    return destination, len(rows), skipped


def main():
    used_picker = len(sys.argv) == 1
    if used_picker:
        source = pick_file()
        if source is None:
            return
    else:
        source = Path(sys.argv[1].strip('"')).expanduser()

    try:
        if not source.is_file():
            raise FileNotFoundError(f"File not found: {source}")
        output, count, skipped = convert(source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        notify(f"Could not convert file:\n{exc}", error=True)
        sys.exit(1)

    skipped_total = sum(skipped.values())
    skipped_details = "\n".join(f"  {reason}: {amount}" for reason, amount in skipped.items())
    message = (
        f"Created: {output}\n"
        f"Locations exported: {count}\n"
        f"Skipped invalid or duplicate features: {skipped_total}\n"
        + (skipped_details + "\n" if skipped_total else "")
        + "\nGoogle Sheets: File > Import > Upload the CSV, then select "
        "column G below the header and choose Insert > Checkbox."
    )
    if used_picker:
        notify(message)
    else:
        print(message)


if __name__ == "__main__":
    main()
