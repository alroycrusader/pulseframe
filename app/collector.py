import threading
import time
from typing import Dict, Any

COLLECTION_INTERVAL = 10  # seconds

_cache: Dict[str, Any] = {}
_cache_lock = threading.RLock()

# Tracks the health of the background collection loop so the dashboard can
# surface "is the collector actually running" without any new OS-level
# capability — just bookkeeping around the loop that already exists.
_last_collected_at: float = 0.0
_last_collect_ok: bool = False


def _do_collect() -> Dict[str, Any]:
    from app.metrics.overview import get_overview_data
    from app.metrics.cpu import get_cpu_data
    from app.metrics.ram import get_ram_data
    from app.metrics.gpu import get_gpu_data
    from app.metrics.storage import get_storage_data
    from app.metrics.network import get_network_data
    from app.metrics.processes import get_processes_data
    from app.metrics.sensors import get_sensors_data
    from app.metrics.system import get_system_data
    return {
        "overview":  get_overview_data(),
        "cpu":       get_cpu_data(),
        "ram":       get_ram_data(),
        "gpu":       get_gpu_data(),
        "storage":   get_storage_data(),
        "network":   get_network_data(),
        "processes": get_processes_data(),
        "sensors":   get_sensors_data(),
        "system":    get_system_data(),
    }


def _collect_and_store():
    global _cache, _last_collected_at, _last_collect_ok
    try:
        data = _do_collect()
        with _cache_lock:
            _cache = data
            _last_collected_at = time.time()
            _last_collect_ok = True
        try:
            from app import storage
            storage.write_snapshot(data)
        except Exception as e:
            print(f"[collector] storage write failed: {e}")
    except Exception as e:
        print(f"[collector] collection failed: {e}")
        with _cache_lock:
            _last_collect_ok = False


def get_cache() -> Dict[str, Any]:
    with _cache_lock:
        return dict(_cache)


def get_health() -> Dict[str, Any]:
    """Lightweight self-health snapshot for the collector loop.

    Used to surface "is the in-memory snapshot fresh" on the dashboard —
    deliberately built from data already tracked by the loop, no new
    collection logic.
    """
    with _cache_lock:
        last_at = _last_collected_at
        ok = _last_collect_ok
    age = (time.time() - last_at) if last_at else None
    return {
        "last_collected_at": last_at or None,
        "age_sec": age,
        "ok": ok,
        "interval_sec": COLLECTION_INTERVAL,
    }


def start():
    # Warm the cache before starting the loop
    _collect_and_store()

    def _loop():
        while True:
            time.sleep(COLLECTION_INTERVAL)
            _collect_and_store()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
