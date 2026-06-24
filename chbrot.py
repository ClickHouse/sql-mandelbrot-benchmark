"""
chbrot - chDB Mandelbrot Set Computation in Plain SQL

This is an implementation of the sql-mandelbrot-benchmark using chDB.
It computes the classic Mandelbrot set in plain SQL — no loops, no procedural code, just pure SQL.

Author: Alexey Milovidov
License: MIT
GitHub: https://github.com/Zeutschler/sql-mandelbrot-benchmark
"""

import chdb
import numpy as np
import pyarrow
from utils import save_mandelbrot_image


def run_chbrot(width, height, max_iterations):
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
    """

    # Execute query
    result = chdb.query(mandelbrot_query, output_format="ArrowTable")

    # Scatter the depths into the image grid by (x, y)
    xs = result['x'].to_numpy()
    ys = result['y'].to_numpy()
    depth = result['depth'].to_numpy()

    mandelbrot = np.empty((height, width), dtype=np.uint32)
    mandelbrot[ys, xs] = depth

    return mandelbrot


if __name__ == "__main__":
    # Standalone execution
    WIDTH = 1400
    HEIGHT = 800
    MAX_ITERATIONS = 256

    print(f"Computing Mandelbrot set ({WIDTH}x{HEIGHT}, max {MAX_ITERATIONS} iterations)...")
    result = run_chbrot(WIDTH, HEIGHT, MAX_ITERATIONS)
    save_mandelbrot_image(result, MAX_ITERATIONS, 'chbrot.png')
