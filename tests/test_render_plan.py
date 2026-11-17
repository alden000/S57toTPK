import shapely

from s57totpk.render import RenderOptions, plan_blocks, tile_to_lonlat, lonlat_to_tile


def test_plan_detail_area():
    cov = shapely.box(-71.6, 41.2, -71.1, 41.7)
    base = plan_blocks(cov, RenderOptions(minzoom=10, maxzoom=12))
    assert {b[0] for b in base} == {10, 11, 12}
    det = plan_blocks(cov, RenderOptions(minzoom=10, maxzoom=12, detail_bbox=(-71.42, 41.48, -71.40, 41.50), detail_maxzoom=14))
    extra = [b for b in det if b[0] > 12]
    assert extra and len(extra) < len(base) * 4


def test_tile_math_roundtrip():
    x, y = lonlat_to_tile(-71.4, 41.5, 12)
    lon, lat = tile_to_lonlat(x, y, 12)
    assert abs(lon + 71.4) < 1e-9 and abs(lat - 41.5) < 1e-9
