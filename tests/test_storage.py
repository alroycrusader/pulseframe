"""Tests for app/storage.py: retention configuration/migrations, pruning,
and the bucketed/aggregate history queries.

Each test gets a fresh, isolated SQLite file via the `db` fixture so tests
never touch the real data/metrics.db.
"""
import time

import pytest

from app import storage


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "metrics_test.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    storage.init_db()
    return storage


def _insert_metric(conn, ts, **cols):
    fields = ['cpu_pct', 'ram_pct', 'swap_pct', 'load_1m', 'load_5m', 'load_15m',
              'net_rx_bytes', 'net_tx_bytes', 'process_count', 'cpu_temp_avg', 'gpu_pct']
    values = {f: cols.get(f) for f in fields}
    conn.execute(
        f"""INSERT INTO metric_snapshots (timestamp, {', '.join(fields)})
            VALUES (:ts, {', '.join(':' + f for f in fields)})""",
        {'ts': ts, **values}
    )


def _insert_disk(conn, ts, mount, used_percent):
    conn.execute(
        "INSERT INTO disk_snapshots (timestamp, mount_point, used_percent) VALUES (?, ?, ?)",
        (ts, mount, used_percent)
    )


# ── Migrations / retention configuration ────────────────────────────────────

def test_init_db_seeds_default_retention(db):
    assert db.get_retention_days() == storage.DEFAULT_RETENTION_DAYS


def test_init_db_is_idempotent_and_tracks_migrations(db):
    # Calling init_db again must not error or duplicate migration effects.
    db.init_db()
    conn = db._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        assert count == len(db._MIGRATIONS)
    finally:
        conn.close()


def test_set_retention_days_persists_and_clamps(db):
    assert db.set_retention_days(7) == 7
    assert db.get_retention_days() == 7

    # Out-of-range values are clamped rather than rejected outright.
    assert db.set_retention_days(0) == db.MIN_RETENTION_DAYS
    assert db.set_retention_days(10_000) == db.MAX_RETENTION_DAYS


def test_existing_database_without_config_table_gets_safe_default(db, tmp_path, monkeypatch):
    # Simulate a pre-migration database: drop the _config table and the
    # migrations record, then re-run init_db and confirm it heals cleanly
    # back to the documented default instead of erroring.
    conn = db._connect()
    conn.execute("DROP TABLE IF EXISTS _config")
    conn.execute("DELETE FROM _migrations WHERE id = 2")
    conn.commit()
    conn.close()

    db.init_db()
    assert db.get_retention_days() == storage.DEFAULT_RETENTION_DAYS


# ── Pruning behavior ─────────────────────────────────────────────────────────

def test_prune_now_removes_rows_older_than_retention(db):
    db.set_retention_days(1)
    now = time.time()
    conn = db._connect()
    try:
        _insert_metric(conn, now - 2 * 86400, cpu_pct=50)   # too old, should be pruned
        _insert_metric(conn, now - 1000, cpu_pct=60)        # recent, should survive
        _insert_disk(conn, now - 2 * 86400, '/', 90.0)
        _insert_disk(conn, now - 1000, '/', 91.0)
        conn.commit()
    finally:
        conn.close()

    deleted = db.prune_now()
    assert deleted['metric_snapshots'] == 1
    assert deleted['disk_snapshots'] == 1

    remaining = db.query_metrics(hours=24 * 30)
    assert len(remaining) == 1
    assert remaining[0]['cpu_pct'] == 60


def test_write_snapshot_prunes_automatically(db):
    db.set_retention_days(1)
    now = time.time()
    conn = db._connect()
    try:
        _insert_metric(conn, now - 5 * 86400, cpu_pct=10)
        conn.commit()
    finally:
        conn.close()

    # A normal collector write (minimal payload) should trigger pruning too.
    db.write_snapshot({})

    remaining = db.query_metrics(hours=24 * 30)
    assert all(r['timestamp'] >= now - 86400 for r in remaining)


def test_increasing_retention_does_not_resurrect_pruned_rows(db):
    db.set_retention_days(1)
    now = time.time()
    conn = db._connect()
    try:
        _insert_metric(conn, now - 5 * 86400, cpu_pct=10)
        conn.commit()
    finally:
        conn.close()
    db.prune_now()
    assert db.query_metrics(hours=24 * 30) == []

    db.set_retention_days(30)  # widening retention shouldn't undelete rows
    assert db.query_metrics(hours=24 * 30) == []


# ── Bucketed history queries ─────────────────────────────────────────────────

def test_query_metrics_bucketing_aggregates_into_fewer_points(db):
    conn = db._connect()
    try:
        base = time.time() - 600
        for i in range(60):  # 60 samples, 10s apart = 10 minutes of data
            _insert_metric(conn, base + i * 10, cpu_pct=float(i))
        conn.commit()
    finally:
        conn.close()

    raw = db.query_metrics(hours=1)
    assert len(raw) == 60

    bucketed = db.query_metrics(hours=1, bucket_sec=60)
    # 10 minutes of data in 60s buckets -> at most 10-11 buckets, well under raw count
    assert 0 < len(bucketed) <= 11
    # bucket averages should fall within the raw value range
    assert all(0 <= r['cpu_pct'] <= 59 for r in bucketed)


def test_query_disk_filters_by_mount(db):
    conn = db._connect()
    try:
        now = time.time()
        _insert_disk(conn, now - 10, '/', 50.0)
        _insert_disk(conn, now - 10, '/data', 70.0)
        conn.commit()
    finally:
        conn.close()

    root_only = db.query_disk(hours=1, mount='/')
    assert len(root_only) == 1
    assert root_only[0]['mount_point'] == '/'


# ── Aggregate stats / capacity trends ───────────────────────────────────────

def test_query_metrics_stats_peaks_and_averages(db):
    conn = db._connect()
    try:
        base = time.time() - 300
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for i, v in enumerate(values):
            _insert_metric(conn, base + i * 10, cpu_pct=v, ram_pct=v * 2)
        conn.commit()
    finally:
        conn.close()

    stats = db.query_metrics_stats(hours=1)
    cpu_stats = stats['metrics']['cpu_pct']
    assert cpu_stats['min'] == 10.0
    assert cpu_stats['max'] == 50.0
    assert cpu_stats['avg'] == pytest.approx(30.0)
    assert cpu_stats['samples'] == 5
    assert cpu_stats['p50'] is not None


def test_query_metrics_stats_network_rate_from_counters(db):
    conn = db._connect()
    try:
        base = time.time() - 100
        # Cumulative counters increasing by 1000 bytes every 10 seconds -> ~100 B/s
        _insert_metric(conn, base, net_rx_bytes=0, net_tx_bytes=0)
        _insert_metric(conn, base + 10, net_rx_bytes=1000, net_tx_bytes=500)
        conn.commit()
    finally:
        conn.close()

    stats = db.query_metrics_stats(hours=1, bucket_sec=10)
    assert stats['metrics']['net_rx_bps']['max'] == pytest.approx(100.0)
    assert stats['metrics']['net_tx_bps']['max'] == pytest.approx(50.0)


def test_query_disk_trend_detects_growth_and_projects_full(db):
    conn = db._connect()
    try:
        base = time.time() - 86400  # 1 day ago
        # Grows from 50% to 60% over 1 day -> ~10%/day
        _insert_disk(conn, base, '/', 50.0)
        _insert_disk(conn, base + 86400, '/', 60.0)
        conn.commit()
    finally:
        conn.close()

    trend = db.query_disk_trend(hours=48)
    assert len(trend) == 1
    row = trend[0]
    assert row['mount_point'] == '/'
    assert row['growth_pct_per_day'] == pytest.approx(10.0, rel=0.05)
    assert row['days_to_full'] == pytest.approx(4.0, rel=0.1)


def test_query_disk_trend_flat_usage_has_no_projection(db):
    conn = db._connect()
    try:
        base = time.time() - 86400
        _insert_disk(conn, base, '/', 50.0)
        _insert_disk(conn, base + 86400, '/', 50.0)
        conn.commit()
    finally:
        conn.close()

    trend = db.query_disk_trend(hours=48)
    assert trend[0]['days_to_full'] is None


def test_query_metrics_stats_empty_window_returns_none_values(db):
    stats = db.query_metrics_stats(hours=1)
    for col in storage._STATS_COLUMNS:
        assert stats['metrics'][col]['samples'] == 0
        assert stats['metrics'][col]['p50'] is None
