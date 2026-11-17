"""End-to-end on real ENC data: set S57TOTPK_TEST_ENC to an ENC_ROOT folder."""
import os

import pytest

ENC = os.environ.get("S57TOTPK_TEST_ENC")
pytestmark = pytest.mark.skipif(not ENC, reason="set S57TOTPK_TEST_ENC to an ENC_ROOT to run")


def test_end_to_end(tmp_path):
    from s57totpk.cli import main
    out = str(tmp_path / "out")
    assert main(["run", "--enc", ENC, "--out", out, "--minzoom", "8", "--maxzoom", "9",
                 "--tile-size", "256", "--package", "tpkx,tpk"]) == 0
    rasterio = pytest.importorskip("rasterio")
    with rasterio.open(os.path.join(out, "ENC.tpkx")) as ds:
        a = ds.read(4, out_shape=(256, 256))
        assert (a > 0).any()
