import sqlite3
import os
import time as _time

DB_PATH = os.environ.get('DB_PATH', 'data/metrics.db')

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365


def _parse_default_retention_days() -> int:
    """Parse HISTORY_RETENTION_DAYS, falling back to 30 on anything invalid
    (missing, non-numeric, or out of range) instead of crashing at import.
    """
    try:
        days = int(float(os.environ.get('HISTORY_RETENTION_DAYS', '30')))
    except (TypeError, ValueError):
        return 30
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, days))


# Default retention window, used only to seed the `_config` table the first
# time a database is initialized. After that, the persisted value in
# `_config` is authoritative — see get_retention_days()/set_retention_days().
DEFAULT_RETENTION_DAYS = _parse_default_retention_days()


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ── Schema migrations ───────────────────────────────────────────────────────
# Each migration is a small, idempotent function applied at most once per
# database (tracked via the `_migrations` table). This gives existing SQLite
# files a safe upgrade path instead of requiring a fresh database.
_MIGRATIONS = []


def _migration(fn):
    _MIGRATIONS.append(fn)
    return fn


@_migration
def _m001_add_gpu_pct_column(conn):
    """Older databases pre-date the gpu_pct column on metric_snapshots."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(metric_snapshots)").fetchall()]
    if 'gpu_pct' not in cols:
        conn.execute("ALTER TABLE metric_snapshots ADD COLUMN gpu_pct REAL")


@_migration
def _m002_create_config_table(conn):
    """Add a key/value config table and seed retention_days.

    Existing installs were hard-coded to 30 days; seed with the
    HISTORY_RETENTION_DAYS env var (defaulting to 30) so behavior is
    unchanged unless an operator opts in to a different value.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO _config (key, value) VALUES ('retention_days', ?)",
        (str(DEFAULT_RETENTION_DAYS),)
    )


def init_db():
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metric_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     REAL NOT NULL,
            cpu_pct       REAL,
            ram_pct       REAL,
            swap_pct      REAL,
            load_1m       REAL,
            load_5m       REAL,
            load_15m      REAL,
            net_rx_bytes  INTEGER,
            net_tx_bytes  INTEGER,
            process_count INTEGER,
            cpu_temp_avg  REAL,
            gpu_pct       REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ms_ts ON metric_snapshots(timestamp);
        CREATE TABLE IF NOT EXISTS _migrations (id INTEGER PRIMARY KEY);

        CREATE TABLE IF NOT EXISTS disk_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL NOT NULL,
            mount_point  TEXT NOT NULL,
            used_percent REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ds_ts ON disk_snapshots(timestamp);

        CREATE TABLE IF NOT EXISTS process_snapshots (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            name      TEXT,
            cpu_pct   REAL,
            mem_pct   REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ps_ts ON process_snapshots(timestamp);
    """)
    conn.commit()

    applied = {r[0] for r in conn.execute("SELECT id FROM _migrations").fetchall()}
    for migration_id, fn in enumerate(_MIGRATIONS, start=1):
        if migration_id in applied:
            continue
        fn(conn)
        conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
        conn.commit()

    conn.close()


def write_snapshot(data: dict):
    now = _time.time()

    # Extract metric values safely
    cpu_pct = None
    cpu_data = data.get('cpu') or {}
    overview = data.get('overview') or {}
    if cpu_data.get('total_cpu') is not None:
        try:
            cpu_pct = float(cpu_data['total_cpu'])
        except (TypeError, ValueError):
            pass
    if cpu_pct is None and overview.get('cpu_usage') is not None:
        try:
            cpu_pct = float(overview['cpu_usage'])
        except (TypeError, ValueError):
            pass

    ram_pct = None
    ram_data = data.get('ram') or {}
    ram_info = ram_data.get('ram_info') or {}
    if ram_info.get('used_percent') is not None:
        try:
            ram_pct = float(ram_info['used_percent'])
        except (TypeError, ValueError):
            pass

    swap_pct = None
    swap_list = ram_data.get('swap_info') or []
    if swap_list:
        try:
            total_mb = sum(float(s.get('size_mb') or 0) for s in swap_list)
            used_mb  = sum(float(s.get('used_mb')  or 0) for s in swap_list)
            swap_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0.0
        except Exception:
            pass

    load_avg = (cpu_data.get('load_average') or overview.get('load_average')) or {}
    load_1m  = _safe_float(load_avg.get('1min'))
    load_5m  = _safe_float(load_avg.get('5min'))
    load_15m = _safe_float(load_avg.get('15min'))

    net_data = data.get('network') or {}
    ifaces = net_data.get('interfaces') or []
    net_rx = sum(int(i.get('rx_bytes') or 0) for i in ifaces) if ifaces else None
    net_tx = sum(int(i.get('tx_bytes') or 0) for i in ifaces) if ifaces else None

    proc_count = None
    if overview.get('process_count') is not None:
        proc_count = int(overview['process_count'])
    elif data.get('processes') and data['processes'].get('all_processes'):
        proc_count = len(data['processes']['all_processes'])

    cpu_temp_avg = None
    if cpu_data.get('cpu_temperature'):
        cpu_temp_avg = _safe_float(cpu_data['cpu_temperature'].get('average'))

    gpu_pct = None
    gpu_data = data.get('gpu') or {}
    if gpu_data.get('nvidia_available') and gpu_data.get('gpus'):
        utils = [_safe_float(g.get('utilization')) for g in gpu_data['gpus'] if g.get('utilization') is not None]
        if utils:
            gpu_pct = sum(utils) / len(utils)

    # Disk snapshots — skip virtual filesystems
    SKIP_FS = ('tmpfs', 'overlay', 'devtmpfs', 'udev', 'shm', 'cgroup', 'proc', 'sysfs', 'none')
    storage_data = data.get('storage') or {}
    disk_rows = []
    for dk in (storage_data.get('disk_usage') or []):
        fs = dk.get('filesystem', '')
        if any(fs.startswith(p) for p in SKIP_FS):
            continue
        mp  = dk.get('mount_point', fs)
        pct = _safe_float(dk.get('used_percent'))
        disk_rows.append((now, mp, pct))

    # Top-10 processes by CPU for this snapshot
    proc_rows = []
    processes = (data.get('processes') or {}).get('all_processes') or []
    top_procs = sorted(processes, key=lambda p: float(p.get('cpu_percent') or 0), reverse=True)[:10]
    for p in top_procs:
        cmd = (p.get('command') or '').strip()
        name = (cmd.split()[0] if cmd else 'unknown').split('/')[-1][:64]
        cpu = _safe_float(p.get('cpu_percent'))
        mem = _safe_float(p.get('memory_percent'))
        if name and cpu is not None:
            proc_rows.append((now, name, cpu, mem))

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO metric_snapshots
               (timestamp,cpu_pct,ram_pct,swap_pct,load_1m,load_5m,load_15m,
                net_rx_bytes,net_tx_bytes,process_count,cpu_temp_avg,gpu_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now, cpu_pct, ram_pct, swap_pct, load_1m, load_5m, load_15m,
             net_rx, net_tx, proc_count, cpu_temp_avg, gpu_pct)
        )
        if disk_rows:
            conn.executemany(
                "INSERT INTO disk_snapshots (timestamp,mount_point,used_percent) VALUES (?,?,?)",
                disk_rows
            )
        if proc_rows:
            conn.executemany(
                "INSERT INTO process_snapshots (timestamp,name,cpu_pct,mem_pct) VALUES (?,?,?,?)",
                proc_rows
            )
        # Prune old rows according to the configured retention window
        _prune_conn(conn)
        conn.commit()
    finally:
        conn.close()


# ── Retention configuration ─────────────────────────────────────────────────

def _get_retention_days_conn(conn) -> int:
    row = conn.execute("SELECT value FROM _config WHERE key = 'retention_days'").fetchone()
    if row is None:
        return DEFAULT_RETENTION_DAYS
    try:
        return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, int(float(row['value']))))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def get_retention_days() -> int:
    conn = _connect()
    try:
        return _get_retention_days_conn(conn)
    finally:
        conn.close()


def set_retention_days(days: int) -> int:
    """Persist a new retention window (days) and immediately prune rows that
    now fall outside of it, rather than waiting for the next collector tick.
    """
    days = max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, int(days)))
    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO _config (key, value) VALUES ('retention_days', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (str(days),))
        _prune_conn(conn)
        conn.commit()
        return days
    finally:
        conn.close()


def _prune_conn(conn) -> dict:
    """Delete snapshot rows older than the configured retention window using
    an already-open connection. Caller is responsible for committing.
    """
    days = _get_retention_days_conn(conn)
    cutoff = _time.time() - days * 86400
    deleted = {}
    for table in ('metric_snapshots', 'disk_snapshots', 'process_snapshots'):
        cur = conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        deleted[table] = cur.rowcount
    return deleted


def prune_now() -> dict:
    """Manually prune rows older than the current retention window. Returns
    the number of rows deleted per table. Useful for ops/testing; the
    collector also prunes automatically on every write_snapshot() call.
    """
    conn = _connect()
    try:
        deleted = _prune_conn(conn)
        conn.commit()
        return deleted
    finally:
        conn.close()


def query_metrics(hours: float, bucket_sec: int = None) -> list:
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        if bucket_sec:
            b = int(bucket_sec)
            rows = conn.execute("""
                SELECT
                  CAST(timestamp / :b AS INTEGER) * :b AS timestamp,
                  AVG(cpu_pct)        AS cpu_pct,
                  AVG(ram_pct)        AS ram_pct,
                  AVG(swap_pct)       AS swap_pct,
                  AVG(load_1m)        AS load_1m,
                  AVG(load_5m)        AS load_5m,
                  AVG(load_15m)       AS load_15m,
                  AVG(net_rx_bytes)   AS net_rx_bytes,
                  AVG(net_tx_bytes)   AS net_tx_bytes,
                  AVG(process_count)  AS process_count,
                  AVG(cpu_temp_avg)   AS cpu_temp_avg,
                  AVG(gpu_pct)        AS gpu_pct
                FROM metric_snapshots
                WHERE timestamp >= :cutoff
                GROUP BY CAST(timestamp / :b AS INTEGER)
                ORDER BY timestamp ASC
            """, {'b': b, 'cutoff': cutoff}).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM metric_snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_disk(hours: float, mount: str = None, bucket_sec: int = None) -> list:
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        if bucket_sec:
            b = int(bucket_sec)
            if mount:
                rows = conn.execute("""
                    SELECT
                      CAST(timestamp / :b AS INTEGER) * :b AS timestamp,
                      mount_point,
                      AVG(used_percent) AS used_percent
                    FROM disk_snapshots
                    WHERE timestamp >= :cutoff AND mount_point = :mount
                    GROUP BY CAST(timestamp / :b AS INTEGER), mount_point
                    ORDER BY timestamp ASC
                """, {'b': b, 'cutoff': cutoff, 'mount': mount}).fetchall()
            else:
                rows = conn.execute("""
                    SELECT
                      CAST(timestamp / :b AS INTEGER) * :b AS timestamp,
                      mount_point,
                      AVG(used_percent) AS used_percent
                    FROM disk_snapshots
                    WHERE timestamp >= :cutoff
                    GROUP BY CAST(timestamp / :b AS INTEGER), mount_point
                    ORDER BY timestamp ASC
                """, {'b': b, 'cutoff': cutoff}).fetchall()
        else:
            if mount:
                rows = conn.execute(
                    "SELECT * FROM disk_snapshots WHERE timestamp >= ? AND mount_point = ? ORDER BY timestamp ASC",
                    (cutoff, mount)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM disk_snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
                    (cutoff,)
                ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_process_tracking_start() -> float | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT MIN(timestamp) FROM process_snapshots").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def query_processes_at(timestamp: float, window_sec: float = 30) -> list:
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT
              name,
              MAX(cpu_pct) AS cpu_pct,
              MAX(mem_pct) AS mem_pct
            FROM process_snapshots
            WHERE timestamp BETWEEN ? AND ?
            GROUP BY name
            ORDER BY cpu_pct DESC
            LIMIT 20
        """, (timestamp - window_sec, timestamp + window_sec)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_processes(hours: float) -> list:
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT
              name,
              MAX(cpu_pct)  AS peak_cpu_pct,
              AVG(cpu_pct)  AS avg_cpu_pct,
              MAX(mem_pct)  AS peak_mem_pct,
              COUNT(*)      AS samples
            FROM process_snapshots
            WHERE timestamp >= ?
            GROUP BY name
            ORDER BY peak_cpu_pct DESC
            LIMIT 20
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Aggregate analytics: peaks / averages / percentiles / capacity trends ──
#
# These intentionally avoid pulling raw rows into Python for long (e.g.
# 30-day) windows. min/max/avg use SQL aggregates over an indexed timestamp
# range scan (single pass, O(n)). Percentiles are approximated from the same
# bucketed averages used for the chart endpoints above, which bounds the
# amount of data that ever needs sorting in Python regardless of how long
# the retention window is.

_STATS_COLUMNS = (
    'cpu_pct', 'ram_pct', 'swap_pct', 'load_1m', 'load_5m', 'load_15m',
    'cpu_temp_avg', 'gpu_pct', 'process_count',
)


def _auto_bucket_sec(hours: float, max_points: int = 2000) -> int:
    """Pick a bucket size (seconds) that keeps the number of buckets bounded,
    so percentile/trend computations stay cheap even for 30-day windows.
    """
    if hours <= 0:
        return 10
    total_sec = hours * 3600.0
    return max(10, int(total_sec / max_points))


def _percentile(sorted_values: list, pct: float):
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (pct / 100.0) * (len(sorted_values) - 1)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def _series_stats(values: list) -> dict:
    if not values:
        return {'min': None, 'max': None, 'avg': None, 'p50': None, 'p95': None, 'p99': None, 'samples': 0}
    sv = sorted(values)
    return {
        'min': sv[0],
        'max': sv[-1],
        'avg': sum(values) / len(values),
        'p50': _percentile(sv, 50),
        'p95': _percentile(sv, 95),
        'p99': _percentile(sv, 99),
        'samples': len(values),
    }


def _linreg_slope(xs: list, ys: list):
    """Least-squares slope (dy/dx) over the given points, or None if it
    cannot be determined (fewer than 2 points, or no variance in x).
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def query_metrics_stats(hours: float, bucket_sec: int = None) -> dict:
    """Peaks/averages/percentiles for each numeric metric over the window.

    min/max/avg/samples are computed directly from raw rows via SQL
    aggregates (exact). Percentiles are approximated from bucketed averages
    (bounded sample count) to stay cheap for long windows.
    """
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        agg_select = ', '.join(
            f"MIN({c}) AS {c}_min, MAX({c}) AS {c}_max, AVG({c}) AS {c}_avg, COUNT({c}) AS {c}_n"
            for c in _STATS_COLUMNS
        )
        agg_row = conn.execute(
            f"SELECT {agg_select} FROM metric_snapshots WHERE timestamp >= ?",
            (cutoff,)
        ).fetchone()

        b = int(bucket_sec) if bucket_sec else _auto_bucket_sec(hours)
        bucket_select = ', '.join(f"AVG({c}) AS {c}" for c in _STATS_COLUMNS)
        bucket_rows = conn.execute(f"""
            SELECT
              CAST(timestamp / :b AS INTEGER) * :b AS bucket_ts,
              {bucket_select},
              AVG(net_rx_bytes) AS net_rx_bytes,
              AVG(net_tx_bytes) AS net_tx_bytes
            FROM metric_snapshots
            WHERE timestamp >= :cutoff
            GROUP BY CAST(timestamp / :b AS INTEGER)
            ORDER BY bucket_ts ASC
        """, {'b': b, 'cutoff': cutoff}).fetchall()

        metrics = {}
        for c in _STATS_COLUMNS:
            bucket_values = sorted(r[c] for r in bucket_rows if r[c] is not None)
            metrics[c] = {
                'min': agg_row[f'{c}_min'],
                'max': agg_row[f'{c}_max'],
                'avg': agg_row[f'{c}_avg'],
                'samples': agg_row[f'{c}_n'],
                'p50': _percentile(bucket_values, 50),
                'p95': _percentile(bucket_values, 95),
                'p99': _percentile(bucket_values, 99),
            }

        # Network counters are cumulative, so peaks/averages only make sense
        # as throughput rates computed from deltas between buckets.
        rx_rates, tx_rates = [], []
        prev = None
        for r in bucket_rows:
            if prev is not None and r['net_rx_bytes'] is not None and prev['net_rx_bytes'] is not None:
                dt = r['bucket_ts'] - prev['bucket_ts']
                if dt > 0:
                    rx_rates.append(max(0.0, (r['net_rx_bytes'] - prev['net_rx_bytes']) / dt))
                    tx_rates.append(max(0.0, (r['net_tx_bytes'] - prev['net_tx_bytes']) / dt))
            prev = r
        metrics['net_rx_bps'] = _series_stats(rx_rates)
        metrics['net_tx_bps'] = _series_stats(tx_rates)

        return {'hours': hours, 'bucket_sec': b, 'metrics': metrics}
    finally:
        conn.close()


def query_disk_trend(hours: float = 168.0, mount: str = None) -> list:
    """Per-mount capacity trend: current usage, growth rate (%/day) via a
    linear-regression fit over the window, and a naive projection for when
    the mount would reach 100% if the current trend continues.
    """
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        if mount:
            mounts = [mount]
        else:
            rows = conn.execute(
                "SELECT DISTINCT mount_point FROM disk_snapshots WHERE timestamp >= ?",
                (cutoff,)
            ).fetchall()
            mounts = [r['mount_point'] for r in rows]

        results = []
        for m in mounts:
            rows = conn.execute("""
                SELECT timestamp, used_percent FROM disk_snapshots
                WHERE timestamp >= ? AND mount_point = ? AND used_percent IS NOT NULL
                ORDER BY timestamp ASC
            """, (cutoff, m)).fetchall()
            if not rows:
                continue
            xs = [r['timestamp'] for r in rows]
            ys = [r['used_percent'] for r in rows]
            slope_per_sec = _linreg_slope(xs, ys)
            growth_pct_per_day = slope_per_sec * 86400 if slope_per_sec is not None else None
            current = ys[-1]
            days_to_full = None
            if growth_pct_per_day and growth_pct_per_day > 0.0001:
                days_to_full = max(0.0, (100.0 - current) / growth_pct_per_day)
            results.append({
                'mount_point': m,
                'current_used_percent': current,
                'samples': len(rows),
                'window_hours': hours,
                'growth_pct_per_day': growth_pct_per_day,
                'days_to_full': days_to_full,
            })
        return results
    finally:
        conn.close()


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
