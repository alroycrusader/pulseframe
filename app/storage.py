import sqlite3
import os
import time as _time

DB_PATH = os.environ.get('DB_PATH', 'data/metrics.db')
RETENTION_DAYS = 30


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


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
        -- Add gpu_pct to existing databases that pre-date this column
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
    # Add gpu_pct column to existing databases that pre-date it
    try:
        conn.execute("ALTER TABLE metric_snapshots ADD COLUMN gpu_pct REAL")
        conn.commit()
    except Exception:
        pass  # column already exists
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
        # Prune old rows
        cutoff = now - RETENTION_DAYS * 86400
        conn.execute("DELETE FROM metric_snapshots WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM disk_snapshots WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM process_snapshots WHERE timestamp < ?", (cutoff,))
        conn.commit()
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


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
