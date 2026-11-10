from rentradar import address
from rentradar.geo import GridIndex, haversine_m, point_segment_distance_m


def test_parse_strips_units_and_normalises_suffix():
    k = address.parse("6 Wait Street, Apt 3", "02120")
    assert (k.street, k.zip, k.lo, k.hi) == ("WAIT ST", "02120", 6, 6)
    k2 = address.parse("151 N 1st St, # 727", "2142")
    assert k2.street == "N 1ST ST" and k2.zip == "02142"


def test_parse_reads_zip_from_rentsmart_style_address():
    k = address.parse("256 Parker Hill Ave, 02120")
    assert k.zip == "02120" and k.street == "PARKER HILL AVE" and k.lo == 256


def test_ranges_overlap():
    building = address.parse("40-42 Sample Ave", "02134")
    unit = address.parse("41 Sample Avenue", "02134")
    other = address.parse("44 Sample Ave", "02134")
    assert building.overlaps(unit)
    assert not building.overlaps(other)


def test_from_parts_assessment_style():
    k = address.from_parts("40", "SAMPLE AVE", "2134", "42")
    assert (k.lo, k.hi, k.zip) == (40, 42, "02134")


def test_unparseable_returns_none():
    assert address.parse("Harvard Yard", "02138") is None
    assert address.parse("", "02138") is None


def test_haversine_known_distance():
    # Harvard Yard -> MIT 77 Mass Ave is roughly 2.5 km
    d = haversine_m(42.3744, -71.1169, 42.3594, -71.0928)
    assert 2300 < d < 2700


def test_grid_within_and_segment():
    pts = [(42.0 + i * 0.001, -71.0, i) for i in range(10)]
    g = GridIndex(pts, 100)
    hits = g.within(42.0, -71.0, 250)
    assert [o for _d, o in hits] == [0, 1, 2]
    seg = g.along_segment(42.0, -71.001, 42.009, -71.001, 100)
    assert len(seg) == 10  # every point is ~83 m from the line
    assert point_segment_distance_m(42.0, -71.0, 42.0, -71.001, 42.009, -71.001) < 100


def test_trailing_unit_after_suffix_is_dropped():
    assert address.parse("1218 Commonwealth Ave 1, 02134").street == "COMMONWEALTH AVE"
    assert address.parse("100 Main St B", "02134").street == "MAIN ST"
    assert address.parse("451 Park Dr", "02215").street == "PARK DR"


def test_saint_prefix_normalises_to_st():
    assert address.parse("25 Saint Lukes Rd", "02134").street == "ST LUKES RD"
    assert address.parse("25 St Lukes Rd", "02134").street == "ST LUKES RD"
