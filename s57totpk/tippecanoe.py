"""Optional: make the vector tiles with tippecanoe in Docker instead of the
built-in tiler. The image is built from a pinned tippecanoe release.

Tiles are written inside the container to /tmp and copied out at the end:
writing through a Windows bind mount is many times slower.
"""
from __future__ import annotations

import os
import shutil
import subprocess

TIPPECANOE_VERSION = "2.79.0"
IMAGE = f"s57totpk-tippecanoe:{TIPPECANOE_VERSION}"
DOCKERFILE = f"""FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsqlite3-dev zlib1g-dev git ca-certificates \\
 && git clone --depth 1 --branch {TIPPECANOE_VERSION} https://github.com/felt/tippecanoe.git /src \\
 && make -C /src -j4 && make -C /src install
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libsqlite3-0 zlib1g && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/tippecanoe /usr/local/bin/tile-join /usr/local/bin/
"""
ARGS = ["-l", "enc", "-Z", "8", "-z", "16", "-r1", "--no-feature-limit", "--no-tile-size-limit",
        "--detect-shared-borders", "--simplification=2", "--force"]


def _run(cmd, log_path, log):
    log("  $ " + " ".join(cmd))
    with open(log_path, "ab") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}), see {log_path}")


def ensure_image(work_dir: str, log=print):
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("docker not found on PATH")
    r = subprocess.run([docker, "image", "inspect", IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode == 0:
        return docker
    d = os.path.join(work_dir, "tippecanoe-docker")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "Dockerfile"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(DOCKERFILE)
    log(f"Building Docker image {IMAGE} (one time)")
    _run([docker, "build", "-t", IMAGE, d], os.path.join(work_dir, "tippecanoe.log"), log)
    return docker


def make_tiles(out_dir: str, minzoom: int = 8, maxzoom: int = 16, log=print) -> str:
    docker = ensure_image(out_dir, log)
    args = list(ARGS)
    args[args.index("-Z") + 1] = str(minzoom)
    args[args.index("-z") + 1] = str(maxzoom)
    src = os.path.abspath(out_dir)
    script = ("tippecanoe -o /tmp/enc.mbtiles " + " ".join(args) +
              " /data/enc.geojsons && cp /tmp/enc.mbtiles /data/enc-tippecanoe.mbtiles.partial")
    log("Vector tiles with tippecanoe " + TIPPECANOE_VERSION)
    _run([docker, "run", "--rm", "-v", f"{src}:/data", IMAGE, "sh", "-c", script],
         os.path.join(out_dir, "tippecanoe.log"), log)
    dst = os.path.join(out_dir, "enc-tippecanoe.mbtiles")
    os.replace(dst + ".partial", dst)
    return dst
