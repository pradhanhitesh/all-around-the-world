"""Build the ocean-currents layer: sample surface currents on a global grid and trace flow lines.

Run daily by .github/workflows/ocean-currents.yml (or by hand):
    .venv/bin/python src/backend/ocean_currents.py

1. Samples Open-Meteo's Marine API (surface current speed + direction) on a 3° grid, at ocean
   points only (data/ocean_mask.json, made once from the globe's land shapes with --make-mask).
   Open-Meteo counts every location as a call (free: ~600/min, 5,000/h, 10,000/day), so requests
   are throttled to ~460 locations a minute; a daily run takes ~9 minutes.
2. Traces evenly spaced streamlines through the velocity field (strongest currents first).
3. Writes src/frontend/public/data/currents.json for the globe.

If any request fails, nothing is written, so the site keeps the previous day's file.
Data: Open-Meteo Marine API (CC BY 4.0), surface currents from Météo-France's SMOC model.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
MASK = ROOT / "data" / "ocean_mask.json"
OUT = ROOT / "src" / "frontend" / "public" / "data" / "currents.json"
API = "https://marine-api.open-meteo.com/v1/marine"
USER_AGENT = "AllAroundTheWorld/0.2 (ocean currents layer)"

GRID = 3  # degrees
LATS = list(range(-75, 76, GRID))  # skip the polar seas (ice; little data)
LONS = list(range(-180, 180, GRID))
BATCH = 100
PAUSE = 13  # seconds between batches (~460 locations/min, under the 600/min limit)
WORLD_ATLAS = ROOT / "src" / "frontend" / "node_modules" / "world-atlas" / "countries-110m.json"

# Streamline tracing
STEP = 0.75  # degrees along the flow per step
MAX_STEPS = 70  # per direction
MIN_SPEED = 0.05  # km/h; slower than this ends a line
OCC = 1.5  # occupancy cell size (degrees): lines keep roughly this far apart
MIN_POINTS = 5


# ---------------------------------------------------------------- sampling


def fetch(points: list[tuple[int, int]]) -> dict[tuple[int, int], tuple[float, float] | None]:
    """{(lat, lon): (u_east, v_north) in km/h, or None on land} for each grid point."""
    out = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for i in range(0, len(points), BATCH):
            chunk = points[i : i + BATCH]
            for attempt in range(4):
                try:
                    res = session.get(
                        API,
                        params={
                            "latitude": ",".join(str(p[0]) for p in chunk),
                            "longitude": ",".join(str(p[1]) for p in chunk),
                            "current": "ocean_current_velocity,ocean_current_direction",
                            "cell_selection": "sea",
                        },
                        timeout=30,
                    )
                    res.raise_for_status()
                    data = res.json()
                    break
                except (requests.RequestException, ValueError) as exc:
                    if attempt == 3:
                        raise SystemExit(f"Open-Meteo request failed ({exc}); keeping the previous file.")
                    limited = getattr(getattr(exc, "response", None), "status_code", None) == 429
                    time.sleep(65 if limited else 5 * (attempt + 1))  # 429: wait out the minute
            data = data if isinstance(data, list) else [data]
            for p, loc in zip(chunk, data):
                cur = loc.get("current") or {}
                speed, direction = cur.get("ocean_current_velocity"), cur.get("ocean_current_direction")
                if speed is None or direction is None:
                    out[p] = None
                    continue
                rad = math.radians(direction)  # direction the current flows towards, clockwise from north
                out[p] = (speed * math.sin(rad), speed * math.cos(rad))
            if i + BATCH < len(points):
                time.sleep(PAUSE)
            print(f"  {min(i + BATCH, len(points))}/{len(points)}", end="\r", flush=True)
    return out


def make_mask() -> None:
    """Which grid points are ocean, from the globe's own land shapes (no API calls). Run once."""
    topo = json.loads(WORLD_ATLAS.read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        out = []
        for i in idx:
            out.extend(arcs[i] if i >= 0 else arcs[~i][::-1])
        return out

    polygons = []
    for g in topo["objects"]["countries"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"] if g["type"] == "MultiPolygon" else []
        for poly in polys:
            rings = [ring(r) for r in poly]
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            polygons.append(((min(xs), min(ys), max(xs), max(ys)), rings))

    def in_ring(x, y, r):
        inside, j = False, len(r) - 1
        for i in range(len(r)):
            (xi, yi), (xj, yj) = r[i], r[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def on_land(lat, lon):
        for (x0, y0, x1, y1), rings in polygons:
            if x0 <= lon <= x1 and y0 <= lat <= y1:
                inside = False
                for r in rings:
                    inside ^= in_ring(lon, lat, r)
                if inside:
                    return True
        return False

    ocean = [(lat, lon) for lat in LATS for lon in LONS if not on_land(lat, lon)]
    MASK.parent.mkdir(parents=True, exist_ok=True)
    MASK.write_text(json.dumps({"grid_deg": GRID, "ocean": ocean}, separators=(",", ":")))
    print(f"Saved ocean mask: {len(ocean)} of {len(LATS) * len(LONS)} grid points are ocean -> {MASK.relative_to(ROOT)}")


def sample() -> dict[tuple[int, int], tuple[float, float]]:
    if not MASK.exists():
        raise SystemExit("No ocean mask: run once with --make-mask (locally, needs src/frontend/node_modules).")
    points = [tuple(p) for p in json.loads(MASK.read_text())["ocean"]]
    print(f"Querying {len(points)} ocean points (~{len(points) // BATCH * PAUSE // 60} min, throttled)")
    values = fetch(points)
    return {p: v for p, v in values.items() if v is not None}


# ---------------------------------------------------------------- streamlines


def velocity(field, lat: float, lon: float):
    """Bilinear interpolation of (u, v) at a point; None if any surrounding sample is land/missing."""
    if not (LATS[0] <= lat <= LATS[-1]):
        return None
    lon = (lon + 180) % 360 - 180
    i0 = math.floor((lat - LATS[0]) / GRID)
    j0 = math.floor((lon - LONS[0]) / GRID)
    fy = (lat - (LATS[0] + i0 * GRID)) / GRID
    fx = (lon - (LONS[0] + j0 * GRID)) / GRID
    corners = []
    for di, dj in ((0, 0), (0, 1), (1, 0), (1, 1)):
        i = min(i0 + di, len(LATS) - 1)
        j = (j0 + dj) % len(LONS)
        v = field.get((LATS[i], LONS[j]))
        if v is None:
            return None
        corners.append(v)
    (u00, v00), (u01, v01), (u10, v10), (u11, v11) = corners
    u = (u00 * (1 - fx) + u01 * fx) * (1 - fy) + (u10 * (1 - fx) + u11 * fx) * fy
    v = (v00 * (1 - fx) + v01 * fx) * (1 - fy) + (v10 * (1 - fx) + v11 * fx) * fy
    return u, v


def occ_key(lat: float, lon: float):
    return (math.floor(lat / OCC), math.floor(((lon + 180) % 360) / OCC))


def trace(field, lat, lon, sign, taken, own):
    """Follow the flow (sign=+1) or against it (sign=-1) from a point, using midpoint (RK2) steps."""
    pts, speeds = [], []
    for _ in range(MAX_STEPS):
        vel = velocity(field, lat, lon)
        if vel is None:
            break
        speed = math.hypot(*vel)
        if speed < MIN_SPEED:
            break
        # Midpoint step, in degrees (longitude stretched by 1/cos(lat)).
        def step(la, lo, v):
            s = math.hypot(*v)
            return (
                la + sign * STEP * v[1] / s,
                lo + sign * STEP * v[0] / s / max(math.cos(math.radians(la)), 0.2),
            )
        mid = step(lat, lon, vel)
        vmid = velocity(field, *mid)
        if vmid is None or math.hypot(*vmid) < MIN_SPEED:
            break
        lat, lon = step(lat, lon, vmid)
        lon = (lon + 180) % 360 - 180
        key = occ_key(lat, lon)
        if key in taken and key not in own:
            break  # another line already runs here
        own.add(key)
        pts.append((lon, lat))
        speeds.append(speed)
    return pts, speeds


def streamlines(field):
    taken: set = set()
    lines = []
    # Seed at every ocean sample, strongest currents first so they get the cleanest lines.
    seeds = sorted(field, key=lambda p: -math.hypot(*field[p]))
    for lat, lon in seeds:
        lat, lon = lat + GRID / 2, lon + GRID / 2  # cell centre
        if velocity(field, lat, lon) is None or occ_key(lat, lon) in taken:
            continue
        own = {occ_key(lat, lon)}
        fwd, sf = trace(field, lat, lon, +1, taken, own)
        back, sb = trace(field, lat, lon, -1, taken, own)
        pts = back[::-1] + [(lon, lat)] + fwd
        if len(pts) < MIN_POINTS:
            continue
        taken |= own
        spd = sb + sf
        lines.append(
            {
                "s": round(sum(spd) / len(spd), 2),  # mean speed along the line, km/h
                "p": [[round(x, 1), round(y, 1)] for x, y in pts],  # 0.1° is plenty on a 3° grid
            }
        )
    return lines


def main() -> None:
    field = sample()
    if len(field) < 1000:
        raise SystemExit(f"Only {len(field)} ocean samples came back; keeping the previous file.")
    lines = streamlines(field)
    speeds = sorted(math.hypot(*v) for v in field.values())
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": "Open-Meteo Marine API (Météo-France SMOC surface currents), CC BY 4.0",
        "grid_deg": GRID,
        "units": "km/h",
        "speed_p90": round(speeds[int(len(speeds) * 0.9)], 2),
        "lines": lines,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {len(lines)} flow lines from {len(field)} samples -> {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    if "--make-mask" in sys.argv:
        make_mask()
    else:
        sys.exit(main())
