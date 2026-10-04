#!/usr/bin/env python3
"""Rebuild data/sites.json and data/creeks.geojson from OpenStreetMap (Overpass).

Run:  python3 data/tools/build_sites.py            # fetch live from Overpass
      python3 data/tools/build_sites.py --cache d/  # reuse/save raw Overpass JSON in d/

What it does:
1. Pulls every OSM waterway named "Wolf Creek" / "Deer Creek" / "Little Deer Creek"
   in a bounding box around Grass Valley / Nevada City.
2. Joins ways that share nodes into connected components and keeps the component
   that passes through the town (there are several Wolf and Deer Creeks in CA;
   this is the check that we have the right one).
3. Simplifies the line (Douglas-Peucker, ~8 m) for the map.
4. Snaps each hand-picked public access point onto the creek line and records
   how far the snap moved it, so nobody gets a marker in the middle of a road.

Standard library only; OSM data is (c) OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import urllib.parse
import urllib.request

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "creekwatch-hackathon/0.1 (+https://github.com/jphein/creek-watch)"
HERE = pathlib.Path(__file__).resolve().parent.parent  # data/

CREEKS = {
    "wolf": {
        "name": "Wolf Creek",
        "town": "Grass Valley",
        "osm_name": "Wolf Creek",
        "bbox": (39.03, -121.14, 39.23, -121.02),
        "town_center": (39.2191, -121.0610),
        "description": "Rises near Loma Rica, runs through downtown Grass Valley and the "
        "North Star / Wolf Creek Trail corridor, then south ~30 km to the Bear River near Wolf.",
    },
    "deer": {
        "name": "Deer Creek",
        "town": "Nevada City",
        "osm_name": "Deer Creek",
        "bbox": (39.22, -121.29, 39.30, -120.89),
        "town_center": (39.2616, -121.0161),
        "description": "Flows from Scotts Flat Reservoir through downtown Nevada City, "
        "along the Deer Creek Tribute Trail, past Rough and Ready to Lake Wildwood, "
        "then on to the Yuba River near Smartsville.",
    },
}

# Hand-picked public access points (upstream -> downstream). `near` is the OSM feature
# (trail bridge, park, road bridge) the point is named after; we snap it to the creek.
# `line` lets a site sit on a tributary line instead of the main stem.
SITES = {
    "wolf": [
        dict(id="wolf-loma-rica-trail", name="Loma Rica Trail bridge", near=(39.22447, -121.02632),
             access="Public trail (Loma Rica Trail); upper Wolf Creek near the headwaters.",
             osm="way/449267810"),
        dict(id="wolf-downtown", name="Downtown Grass Valley (Elisabeth Daniels Park)",
             near=(39.21684, -121.06299),
             access="City pocket park off Bank St by the Park & Ride. Wolf Creek is in a culvert "
             "under downtown (OSM way 1085194147) and reappears here at its outlet.",
             osm="way/826973207"),
        dict(id="wolf-glen-jones-park", name="Wolf Creek Trail at Glen Jones Park / North Star Museum",
             near=(39.20794, -121.06958),
             access="Public trail and picnic area at the North Star Mining Museum (Allison Ranch Rd).",
             osm="way/1546648003"),
        dict(id="wolf-daspah-seyo-trail", name="Daspah Seyo Trail", near=(39.20408, -121.06692),
             access="Public trail continuing downstream of the museum along Wolf Creek.",
             osm="way/1546649673"),
        dict(id="wolf-allison-ranch-rd", name="Allison Ranch Road bridge (La Barr Meadows)",
             near=(39.16584, -121.0611),
             access="View from the public road bridge only; land on both banks is private. "
             "USGS sampled water quality here (site 390955121034101).",
             osm="way/1127241694"),
        dict(id="wolf-wolf-rd", name="Wolf Road bridge (near Wolf)", near=(39.05213, -121.10845),
             access="View from the public road bridge only. Former USGS site 11423150 "
             "'Wolf C nr Wolf CA', ~3 km above the Bear River.",
             osm="way/305641149"),
    ],
    "deer": [
        dict(id="deer-pioneer-park", name="Pioneer Park (Little Deer Creek)", near=(39.25934, -121.00967),
             line="Little Deer Creek",
             access="City park. NOTE: this is Little Deer Creek, a tributary that joins Deer "
             "Creek ~0.6 km downstream at Calanan Park.",
             osm="relation/12824928"),
        dict(id="deer-calanan-park", name="Downtown Nevada City (Calanan Park / Miner's Trail)",
             near=(39.26256, -121.01751),
             access="City park and footpath at Broad St / Hwy 49, just below the Little Deer Creek confluence.",
             osm="way/479769136"),
        dict(id="deer-angkula-seo-bridge", name="Deer Creek Tribute Trail, Angkula Seo Bridge",
             near=(39.26034, -121.0334),
             access="Public trail suspension bridge on the Tribute Trail (Providence Mine Rd trailhead).",
             osm="way/899660375"),
        dict(id="deer-tribute-trail-lower", name="Deer Creek Tribute Trail, lower bridge (Champion Mine Rd)",
             near=(39.25472, -121.04656),
             access="Public trail bridge near Stocking Flat (Champion Mine Rd trailhead).",
             osm="way/936506323"),
        dict(id="deer-bitney-springs-rd", name="Bitney Springs Road bridge", near=(39.24666, -121.11169),
             access="View from the public road bridge only, between Nevada City and Rough and Ready.",
             osm="way/127311846"),
        dict(id="deer-pleasant-valley-rd", name="Pleasant Valley Road bridge (below Lake Wildwood)",
             near=(39.23648, -121.21764),
             access="View from the public road bridge only, Penn Valley; below the Lake Wildwood dam.",
             osm="way/864445285"),
    ],
}


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def overpass(query: str, cache: pathlib.Path | None, key: str):
    if cache:
        f = cache / f"{key}.json"
        if f.exists():
            return json.loads(f.read_text())
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{key}.json").write_text(json.dumps(d))
    return d


def components(ways):
    """Union ways that share any node; return list of lists of ways."""
    parent = {w["id"]: w["id"] for w in ways}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_node = {}
    for w in ways:
        for n in w["nodes"]:
            by_node.setdefault(n, []).append(w["id"])
    for ids in by_node.values():
        for o in ids[1:]:
            parent[find(o)] = find(ids[0])
    groups = {}
    for w in ways:
        groups.setdefault(find(w["id"]), []).append(w)
    return list(groups.values())


def chain(ways):
    """Stitch ways into as few LineStrings as possible (by shared end nodes)."""
    segs = [(w["nodes"], [(p["lon"], p["lat"]) for p in w["geometry"]]) for w in ways]
    lines = []
    while segs:
        nodes, coords = segs.pop(0)
        nodes, coords = list(nodes), list(coords)
        grew = True
        while grew:
            grew = False
            for i, (n2, c2) in enumerate(segs):
                if n2[0] == nodes[-1]:
                    nodes += n2[1:]; coords += c2[1:]
                elif n2[-1] == nodes[0]:
                    nodes = n2[:-1] + nodes; coords = c2[:-1] + coords
                elif n2[-1] == nodes[-1]:
                    nodes += n2[::-1][1:]; coords += c2[::-1][1:]
                elif n2[0] == nodes[0]:
                    nodes = n2[::-1][:-1] + nodes; coords = c2[::-1][:-1] + coords
                else:
                    continue
                segs.pop(i)
                grew = True
                break
        lines.append(coords)
    return lines


def simplify(coords, tol_m=8.0):
    """Douglas-Peucker in a local equirectangular projection."""
    if len(coords) < 3:
        return coords
    lat0 = math.radians(coords[0][1])
    xy = [(lon * 111320 * math.cos(lat0), lat * 110540) for lon, lat in coords]

    def perp(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == dy == 0:
            return math.hypot(x - x1, y - y1)
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))

    keep = [False] * len(coords)
    keep[0] = keep[-1] = True
    stack = [(0, len(coords) - 1)]
    while stack:
        s, e = stack.pop()
        best, idx = 0.0, None
        for i in range(s + 1, e):
            d = perp(xy[i], xy[s], xy[e])
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol_m:
            keep[idx] = True
            stack += [(s, idx), (idx, e)]
    return [[round(c[0], 6), round(c[1], 6)] for c, k in zip(coords, keep) if k]


def snap(pt, lines):
    """Nearest point on any of the lines to pt=(lat,lon). Returns ((lat,lon), metres)."""
    lat0 = math.radians(pt[0])
    fx, fy = 111320 * math.cos(lat0), 110540
    px, py = pt[1] * fx, pt[0] * fy
    best = (None, float("inf"))
    for line in lines:
        for (lo1, la1), (lo2, la2) in zip(line, line[1:]):
            x1, y1, x2, y2 = lo1 * fx, la1 * fy, lo2 * fx, la2 * fy
            dx, dy = x2 - x1, y2 - y1
            t = 0 if dx == dy == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
            sx, sy = x1 + t * dx, y1 + t * dy
            d = math.hypot(px - sx, py - sy)
            if d < best[1]:
                best = ((sy / fy, sx / fx), d)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=pathlib.Path, default=None)
    args = ap.parse_args()

    out_creeks, features = [], []
    for cid, c in CREEKS.items():
        s, w, n, e = c["bbox"]
        names = [c["osm_name"]] + sorted({x["line"] for x in SITES[cid] if x.get("line")})
        q = "[out:json][timeout:90];(" + "".join(
            f'way["waterway"]["name"="{nm}"]({s},{w},{n},{e});' for nm in names) + ");out geom;"
        d = overpass(q, args.cache, f"osm_{cid}")
        lines_by_name = {}
        for nm in names:
            ways = [x for x in d["elements"] if x["tags"].get("name") == nm]
            comps = components(ways)
            ref = c["town_center"] if nm == c["osm_name"] else None
            if ref:
                comp = min(comps, key=lambda ws: min(km(ref, (p["lat"], p["lon"])) for x in ws for p in x["geometry"]))
                dist = min(km(ref, (p["lat"], p["lon"])) for x in comp for p in x["geometry"])
                assert dist < 0.5, f"{nm}: nearest component is {dist:.2f} km from {c['town']}: wrong creek?"
            else:
                comp = max(comps, key=len)
            raw = chain(comp)
            # Snap only to open channel: a marker over a culvert points at a street.
            lines_by_name[nm] = chain([x for x in comp if x["tags"].get("tunnel") != "culvert"])
            for coords in raw:
                features.append({
                    "type": "Feature",
                    "properties": {"creek_id": cid, "name": nm, "main_stem": nm == c["osm_name"],
                                   "source": "OpenStreetMap contributors (ODbL)",
                                   "osm_way_ids": sorted(x["id"] for x in comp)},
                    "geometry": {"type": "LineString", "coordinates": simplify(coords)},
                })
        sites = []
        for st in SITES[cid]:
            line_name = st.get("line", c["osm_name"])
            (la, lo), moved = snap(st["near"], lines_by_name[line_name])
            sites.append({
                "id": st["id"], "name": st["name"], "lat": round(la, 6), "lon": round(lo, 6),
                "on_main_stem": line_name == c["osm_name"], "waterway": line_name,
                "access": st["access"], "osm_ref": f"https://www.openstreetmap.org/{st['osm']}",
                "snap_moved_m": round(moved),
            })
            assert moved < 150, f"{st['id']} snapped {moved:.0f} m: check the point"
        out_creeks.append({"id": cid, "name": c["name"], "town": c["town"],
                           "description": c["description"], "sites": sites})

    (HERE / "sites.json").write_text(json.dumps(out_creeks, indent=2) + "\n")
    (HERE / "creeks.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}) + "\n")
    for c in out_creeks:
        for s in c["sites"]:
            print(f'{s["id"]:28s} {s["lat"]:.5f},{s["lon"]:.5f} snap {s["snap_moved_m"]:>3} m  {s["waterway"]}')
    print(f"{len(features)} line features")


if __name__ == "__main__":
    main()
