"""Flow-line tracing for the ocean-currents layer (synthetic fields, no network)."""

import math

from src.backend import ocean_currents as oc


def uniform_field(u, v, land=lambda lat, lon: False):
    return {(lat, lon): (u, v) for lat in oc.LATS for lon in oc.LONS if not land(lat, lon)}


def test_eastward_current_gives_eastward_lines():
    lines = oc.streamlines(uniform_field(2.0, 0.0))
    assert lines, "expected some flow lines"
    for line in lines[:50]:
        lons = [p[0] for p in line["p"]]
        lats = [p[1] for p in line["p"]]
        # Points run downstream: longitude increases (mod the dateline), latitude stays put.
        steps = [((b - a + 540) % 360) - 180 for a, b in zip(lons, lons[1:])]
        assert all(s > 0 for s in steps)
        assert max(lats) - min(lats) < 0.01
        assert math.isclose(line["s"], 2.0, rel_tol=1e-6)


def test_lines_stop_at_land():
    # A north-south "continent" between 0 and 30 degrees east.
    field = uniform_field(2.0, 0.0, land=lambda lat, lon: 0 <= lon <= 30)
    for line in oc.streamlines(field):
        for lon, _ in line["p"]:
            assert not (3 <= lon <= 27), f"line crossed land at lon {lon}"


def test_direction_is_flowing_towards():
    # Open-Meteo direction 0 = flowing towards north (checked against the Florida Current).
    rad = math.radians(0)
    u, v = 3.6 * math.sin(rad), 3.6 * math.cos(rad)
    assert abs(u) < 1e-9 and v > 0
    vel = oc.velocity(uniform_field(u, v), 10.5, -40.5)
    assert vel is not None and vel[1] > 0


def test_lines_do_not_overlap_much():
    lines = oc.streamlines(uniform_field(1.0, 1.0))
    cells = {}
    for i, line in enumerate(lines):
        for lon, lat in line["p"]:
            cells.setdefault(oc.occ_key(lat, lon), set()).add(i)
    shared = sum(1 for owners in cells.values() if len(owners) > 1)
    assert shared / max(len(cells), 1) < 0.05
