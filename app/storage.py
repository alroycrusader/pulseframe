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
            cpu_temp_avg  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ms_ts ON metric_snapshots(timestamp);

        CREATE TABLE IF NOT EXISTS disk_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL NOT NULL,
            mount_point  TEXT NOT NULL,
            used_percent REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ds_ts ON disk_snapshots(timestamp);
    """)
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

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO metric_snapshots
               (timestamp,cpu_pct,ram_pct,swap_pct,load_1m,load_5m,load_15m,
                net_rx_bytes,net_tx_bytes,process_count,cpu_temp_avg)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (now, cpu_pct, ram_pct, swap_pct, load_1m, load_5m, load_15m,
             net_rx, net_tx, proc_count, cpu_temp_avg)
        )
        if disk_rows:
            conn.executemany(
                "INSERT INTO disk_snapshots (timestamp,mount_point,used_percent) VALUES (?,?,?)",
                disk_rows
            )
        # Prune old rows
        cutoff = now - RETENTION_DAYS * 86400
        conn.execute("DELETE FROM metric_snapshots WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM disk_snapshots WHERE timestamp < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


def query_metrics(hours: float) -> list:
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM metric_snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_disk(hours: float, mount: str = None) -> list:
    cutoff = _time.time() - hours * 3600
    conn = _connect()
    try:
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


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
