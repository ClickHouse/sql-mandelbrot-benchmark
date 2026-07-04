"""
ArcBrot - Arc Mandelbrot Set Computation in Plain SQL

This is an implementation of the sql-mandelbrot-benchmark using Arc
(https://github.com/Basekick-Labs/arc), a columnar analytical database.

Arc's query engine is DuckDB, so the SQL is the DuckDB reference query verbatim.
What this benchmark measures on top of the raw engine is Arc's real server path:
the Fiber HTTP round-trip, Arc's SQL gate, DuckDB execution, and the columnar
Arrow IPC result streamed back over the wire — i.e. how a client actually talks
to Arc, not an in-process embedding.

Setup — start a local Arc with auth and telemetry disabled:

    make build          # in the arc repo; produces ./arc (built with -tags=duckdb_arrow)
    ARC_AUTH_ENABLED=false \
    ARC_TELEMETRY_ENABLED=false \
    ARC_STORAGE_LOCAL_PATH=/tmp/arc-mandelbrot/data \
    ARC_AUTH_DB_PATH=/tmp/arc-mandelbrot/arc.db \
    ./arc

The endpoint used is POST /api/v1/query/arrow, which returns an Apache Arrow IPC
stream (Content-Type: application/vnd.apache.arrow.stream). Override the base URL
with the ARC_URL environment variable (default http://localhost:8000).

Author: Ignacio Van Droogenbroeck
License: MIT
GitHub: https://github.com/Basekick-Labs/sql-mandelbrot-benchmark
"""

import io
import json
import os
import urllib.request

import numpy as np
import pyarrow as pa

from utils import save_mandelbrot_image

ARC_URL = os.environ.get("ARC_URL", "http://localhost:8000")


def run_arcbrot(width, height, max_iterations):
    """
    Compute Mandelbrot set using Arc's HTTP query API with recursive CTEs.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        max_iterations: Maximum iterations per pixel

    Returns:
        2D numpy array of iteration counts
    """
    # Build the SQL query (identical to the DuckDB reference — Arc runs DuckDB).
    # We skip the final ORDER BY and instead scatter the result into the image by
    # (x, y) in NumPy, matching the ClickHouse implementation.
    mandelbrot_query = f"""
    WITH RECURSIVE
      pixels AS (
        SELECT
          x::INTEGER AS x,
          y::INTEGER AS y,
          -2.5 + (x::DOUBLE * 3.5 / {width - 1}.0) AS cx,
          -1.0 + (y::DOUBLE * 2.0 / {height - 1}.0) AS cy
        FROM
          generate_series(0, {width - 1}) AS t1(x),
          generate_series(0, {height - 1}) AS t2(y)
      ),
      mandelbrot_iterations AS (
        SELECT x, y, cx, cy, 0.0::DOUBLE AS zx, 0.0::DOUBLE AS zy, 0 AS iteration
        FROM pixels

        UNION ALL

        SELECT
          m.x,
          m.y,
          m.cx,
          m.cy,
          (m.zx * m.zx - m.zy * m.zy + m.cx)::DOUBLE AS zx,
          (2.0 * m.zx * m.zy + m.cy)::DOUBLE AS zy,
          m.iteration + 1 AS iteration
        FROM mandelbrot_iterations m
        WHERE
          m.iteration < {max_iterations}
          AND (m.zx * m.zx + m.zy * m.zy) <= 4.0
      )
    SELECT
      x,
      y,
      MAX(iteration) AS depth
    FROM mandelbrot_iterations
    GROUP BY x, y
    """

    # Execute query against Arc's Arrow endpoint (POST JSON body, get Arrow IPC back)
    request = urllib.request.Request(
        f"{ARC_URL}/api/v1/query/arrow",
        data=json.dumps({"sql": mandelbrot_query}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        body = response.read()

    # Read the Arrow stream and scatter the depths into the image grid
    table = pa.ipc.open_stream(io.BytesIO(body)).read_all()
    xs = table["x"].to_numpy()
    ys = table["y"].to_numpy()
    depth = table["depth"].to_numpy()

    mandelbrot = np.empty((height, width), dtype=np.uint32)
    mandelbrot[ys, xs] = depth

    return mandelbrot


if __name__ == "__main__":
    # Standalone execution
    WIDTH = 1400
    HEIGHT = 800
    MAX_ITERATIONS = 256

    print(f"Computing Mandelbrot set ({WIDTH}x{HEIGHT}, max {MAX_ITERATIONS} iterations)...")
    result = run_arcbrot(WIDTH, HEIGHT, MAX_ITERATIONS)
    save_mandelbrot_image(result, MAX_ITERATIONS, 'arcbrot.png')
