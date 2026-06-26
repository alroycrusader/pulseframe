import threading
import time
from typing import Dict, Any

COLLECTION_INTERVAL = 10  # seconds

_cache: Dict[str, Any] = {}
_cache_lock = threading.RLock()


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
    global _cache
    try:
        data = _do_collect()
        with _cache_lock:
            _cache = data
        try:
            from app import storage
            storage.write_snapshot(data)
        except Exception as e:
            print(f"[collector] storage write failed: {e}")
    except Exception as e:
        print(f"[collector] collection failed: {e}")


def get_cache() -> Dict[str, Any]:
    with _cache_lock:
        return dict(_cache)


def start():
    # Warm the cache before starting the loop
    _collect_and_store()

    def _loop():
        while True:
            time.sleep(COLLECTION_INTERVAL)
            _collect_and_store()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
