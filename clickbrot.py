"""
ClickBrot - ClickHouse Mandelbrot Set Computation in Plain SQL

This is an implementation of the sql-mandelbrot-benchmark using ClickHouse.
It computes the classic Mandelbrot set in plain SQL — no loops, no procedural code, just pure SQL.

How to install ClickHouse:
```
curl https://clickhouse.com/ | sh
```

Author: Alexey Milovidov
License: MIT
GitHub: https://github.com/Zeutschler/sql-mandelbrot-benchmark
"""

import os
import subprocess
import numpy as np
import io
from utils import save_mandelbrot_image

# The recursive CTE allocates and frees a fresh block on every one of the 256 iterations.
# On macOS the build's effective jemalloc `dirty_decay_ms` behaves like 0 (purge dirty pages
# immediately), so every free triggers a madvise() syscall — and that syscall churn, not the
# arithmetic, dominates the runtime (it also serializes the threads). Giving the decay a small
# finite window lets jemalloc reuse those pages within the query instead of returning them to
# the OS each cycle, which makes the query ~1.9x faster. 5 s is well above the query's runtime,
# so pages are still returned to the OS shortly after the work finishes — unlike `-1` (never
# decay), which would leak the working set for a long-running process.
CLICKHOUSE_ENV = {**os.environ, "MALLOC_CONF": "dirty_decay_ms:5000"}


def run_clickbrot(width, height, max_iterations):
    """
    Compute Mandelbrot set using ClickHouse SQL with recursive CTEs.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        max_iterations: Maximum iterations per pixel

    Returns:
        2D numpy array of iteration counts
    """
    # Build the SQL query.
    # Only the pixel coordinates are carried through the recursion (as narrow UInt16);
    # the complex-plane coordinates are recomputed on the fly. This keeps the data that
    # flows through the recursive step as small as possible. We also skip the final
    # ORDER BY and instead scatter the result into the image by (x, y) in NumPy.
    mandelbrot_query = f"""
    WITH RECURSIVE
      -- Generate pixel grid
      pixels AS (
        SELECT
          toUInt16(arrayJoin(range({width}))) AS x,
          toUInt16(arrayJoin(range({height}))) AS y
      ),
      -- Recursively iterate z = z² + c, mapping the pixel to the complex plane on the fly
      mandelbrot_iterations AS (
        SELECT x, y, 0.0::Float64 AS zx, 0.0::Float64 AS zy, 0::UInt32 AS iteration
        FROM pixels

        UNION ALL

        SELECT
          x, y,
          zx * zx - zy * zy + (-2.5 + x * 3.5 / {width - 1}),
          2.0 * zx * zy + (-1.0 + y * 2.0 / {height - 1}),
          iteration + 1
        FROM mandelbrot_iterations
        WHERE iteration < {max_iterations}
          AND (zx * zx + zy * zy) <= 4.0
      )
    SELECT x, y, MAX(iteration) AS depth
    FROM mandelbrot_iterations
    GROUP BY x, y
    FORMAT Arrow
    """

    # Execute query using clickhouse local
    result = subprocess.run(
        ['clickhouse', 'local', '--query', mandelbrot_query],
        capture_output=True,
        check=True,
        env=CLICKHOUSE_ENV,
    )

    # Read the Arrow output and scatter the depths into the image grid
    import pyarrow as pa
    table = pa.ipc.open_file(io.BytesIO(result.stdout)).read_all()
    xs = table['x'].to_numpy()
    ys = table['y'].to_numpy()
    depth = table['depth'].to_numpy()

    mandelbrot = np.empty((height, width), dtype=np.uint32)
    mandelbrot[ys, xs] = depth

    return mandelbrot


if __name__ == "__main__":
    # Standalone execution
    WIDTH = 1400
    HEIGHT = 800
    MAX_ITERATIONS = 256

    print(f"Computing Mandelbrot set ({WIDTH}x{HEIGHT}, max {MAX_ITERATIONS} iterations)...")
    result = run_clickbrot(WIDTH, HEIGHT, MAX_ITERATIONS)
    save_mandelbrot_image(result, MAX_ITERATIONS, 'clickbrot.png')
