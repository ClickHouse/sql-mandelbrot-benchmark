# sql-mandelbrot-benchmark
**Because why benchmark sql engines with boring aggregates when you can generate fractals?**

This project uses recursive Common Table Expressions (CTE) to calculate the Mandelbrot set entirely 
in SQL — no loops, no procedural code, just pure SQL. It serves as a fun and visually appealing benchmark 
for testing recursive query performance, floating-point precision, and computational capabilities of SQL engines.

![Mandelbrot Set](images/duckbrot.png)

## What is This?

A benchmark suite that:
- Computes the famous [Mandelbrot set](https://en.wikipedia.org/wiki/Mandelbrot_set) using SQL recursive CTEs
- Tests multiple SQL engines — ClickHouse, chDB, DuckDB, ArrowDatafusion, SQLite — plus NumPy and Python implementations for reference.
- Generates beautiful fractal images as proof of correct computation
- Reveals which database / SQL engine renders infinity fastest

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/duckbrot.git
cd duckbrot

# Install dependencies
pip install -r requirements.txt

# Run the benchmark suite
python main.py
```

## Current Benchmark Results

Current results on 1400x800 pixels, 256 max iterations, MacBook Pro M3 Max:

| 🏆 | Engine/Implementation                       | Time (ms)  | Relative Performance |
|----|---------------------------------------------|------------|----------------------|
| *  | Mac Metal GPU (unfair, but the true limit)¹ | 0.77 ms    | ∞ 😵                 |
| 1  | ClickHouse (SQL)                            | 518 ms     | **0.52x** ⭐         |
| 2  | NumPy (vectorized, unrolled)                | 715 ms     | 0.72x                |
| 3  | chDB (SQL)                                  | 782 ms     | 0.79x                |
| 4  | ArrowDatafusion (SQL)                       | 995 ms     | 1.00x (baseline)     |
| 5  | DuckDB (SQL)                                | 2,011 ms   | 2.02x slower         |
| 6  | FasterPybrot                                | 3,850 ms   | 3.87x slower         |
| 7  | FastPybrot                                  | 4,370 ms   | 4.39x slower         |
| 8  | Pure Python                                 | 5,049 ms   | 5.07x slower         |
| 9  | SQLite (SQL)                                | 149,968 ms | 150.7x slower        |

**Winner overall: ClickHouse** — the only engine to beat hand-vectorized NumPy, and by a comfortable margin. End-to-end wall-clock, including launching `clickhouse local` as a subprocess and reading the result back.

**Winner SQL: ClickHouse** — ~1.9x faster than the next SQL engine (ArrowDatafusion), and ~3.9x faster than DuckDB.

How ClickHouse gets there (all on the **latest master build**, `curl https://clickhouse.com/ | sh`):
- **Parallelized recursive CTE.** Master fans the recursion's per-iteration work across all cores (~1.7x over a single thread); older builds ran it single-threaded.
- **jemalloc page-decay tuning.** The recursion allocates and frees a block every iteration. On macOS the build's effective `dirty_decay_ms` behaves like `0` (purge dirty pages immediately), so every free triggers a `madvise()` syscall — pure syscall overhead that also serializes the threads, and it roughly *doubles* the runtime. `clickbrot.py` runs with `MALLOC_CONF=dirty_decay_ms:5000`, which lets jemalloc reuse those pages within the query while still returning them to the OS ~5 s later (so it's safe for a long-running process, unlike `dirty_decay_ms:-1`). This points at a real ClickHouse issue worth fixing upstream — the macOS default purges far too eagerly for an allocation-churning workload.
- **Lean query.** Only the pixel coordinates flow through the recursion (as narrow `UInt16`); the complex-plane mapping is recomputed on the fly, and the final `ORDER BY` is replaced by a NumPy scatter.

`chDB` is the very same ClickHouse engine embedded in-process (its embedded 26.5.1 isn't built with jemalloc, so it never hits the decay issue, but its recursive CTE doesn't parallelize — hence it lands behind the parallel master binary). All SQL engines produce a pixel-for-pixel identical image.

¹ The GPU figure is the original author's MacBook Pro M4 Max measurement, kept as the theoretical "true limit" reference; all other rows are re-measured on this M3 Max.

## How It Works

The Mandelbrot set is computed by iterating the formula `z = z² + c` for each pixel in the complex plane:

```sql
WITH RECURSIVE
  -- Generate pixel grid and map to complex plane
  pixels AS (
    SELECT
      x, y,
      -2.5 + (x * 3.5 / width) AS cx,
      -1.0 + (y * 2.0 / height) AS cy
    FROM generate_series(0, width-1) AS x,
         generate_series(0, height-1) AS y
  ),
  -- Recursively iterate z = z² + c
  mandelbrot_iterations AS (
    SELECT x, y, cx, cy, 0.0 AS zx, 0.0 AS zy, 0 AS iteration
    FROM pixels

    UNION ALL

    SELECT
      x, y, cx, cy,
      zx * zx - zy * zy + cx AS zx,
      2.0 * zx * zy + cy AS zy,
      iteration + 1
    FROM mandelbrot_iterations
    WHERE iteration < max_iterations
      AND (zx * zx + zy * zy) <= 4.0
  )
SELECT x, y, MAX(iteration) AS depth
FROM mandelbrot_iterations
GROUP BY x, y;
```

The iteration count determines the color of each pixel, creating the iconic fractal pattern.

## Adding New Benchmarks

Want to test PostgreSQL, MySQL, MariaDB, SQLite or even Oracle or SQL-Server? Just:

1. Create a new file (e.g., `postgresqlbrot.py`)
2. Implement a `run_postgresqlbrot(width, height, max_iterations)` function (the DuckDB implementation is a good starting point)
3. Add one line to `main.py`:
   ```python
   BENCHMARKS = [
       ("ClickHouse (SQL)", "clickbrot", "run_clickbrot"),
       ("DuckDB (SQL)", "duckbrot", "run_duckbrot"),
       ("Pure Python", "pybrot", "run_pybrot"),
       ..., 
       ("PostgreSQL", "postgresqlbrot", "run_postgresqlbrot"),  # New!
   ]
   ```

The framework handles everything else automatically!

## Configuration

Adjust the benchmark parameters in `main.py`:

```python
WIDTH = 1400           # Image width in pixels
HEIGHT = 800           # Image height in pixels
MAX_ITERATIONS = 256   # Maximum recursion depth
```

Higher values = more detail, longer computation time.

## Known Engine Compatibility

### ✅ Works Great
- **ClickHouse** - The fastest engine in the benchmark, beating even vectorized NumPy. Full `Float64` precision, parallelized recursive CTE across all cores (run via the standalone `clickhouse local` binary, latest master build)
- **chDB** - ClickHouse embedded in-process; same engine, same full precision
- **NumPy** - Highly optimized with loop unrolling and vectorized operations
- **DuckDB** - Excellent performance, proper DOUBLE precision
- **Pure Python** - Reference implementation, just to have an idea how fast the database engines are
- **SQLite** - Works but significantly slower due to recursive CTE overhead

### Should Work (untested, please contribute 🤙)
- PostgreSQL (with proper recursive CTE support)
- others 

### Known Issues
- Some engines might struggle with support for DOUBLE precision and may use DECIMAL (not good for fractals, and lead to pixelated results)
- Watch out for type inference - explicit `::DOUBLE` casts are critical!

## What This Tests

This benchmark evaluates:
1. **Recursive CTE Performance** - How efficiently engines handle deep recursion
2. **Floating-Point Precision** - DOUBLE vs DECIMAL arithmetic accuracy
3. **Query Optimization** - How well engines optimize complex recursive queries
4. **Scalability** - Performance with increasing iterations and resolution

## Contributing

Contributions very welcome! Especially:
- New SQL engine implementations (PostgreSQL, MySQL, etc.)
- Performance optimizations
- Better visualization options
- Benchmark result submissions

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Credits

Created by Thomas Zeutschler, Ulrich Ludmann, and Jakub Jirak (the grand master of GPU fractals)

Inspired by the mathematical beauty of the Mandelbrot set and the curiosity about SQL engine performance.

## Learn More

- [Mandelbrot Set (Wikipedia)](https://en.wikipedia.org/wiki/Mandelbrot_set)
- [SQL Recursive CTEs](https://en.wikipedia.org/wiki/Hierarchical_and_recursive_queries_in_SQL)
- [ClickHouse](https://clickhouse.com/)
- [DuckDB](https://duckdb.org/)

---

**Curious which database renders infinity fastest? Clone and find out! 🌀**
