import time
import threading
import urllib.request
import urllib.error
import json

from app import settings_store

_cooldowns = {}
_cooldowns_lock = threading.Lock()

_prev_net = None
_prev_net_at = 0.0
CHECK_INTERVAL = 30  # seconds between alert evaluations


def _can_fire(key, cooldown):
    now = time.time()
    with _cooldowns_lock:
        if now - _cooldowns.get(key, 0) >= cooldown:
            _cooldowns[key] = now
            return True
    return False


def _post(url, message):
    payload = json.dumps({'content': message}).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload, method='POST',
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'ActivityMonitor/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status < 300
    except urllib.error.HTTPError as e:
        # Discord returns 204 No Content on success
        return e.code < 300
    except Exception:
        return False


def test_webhook(url):
    return _post(url, '✅ **Activity Monitor** — webhook test successful!')


def _fire(hooks, key, message, cooldown):
    if not _can_fire(key, cooldown):
        return
    for h in hooks:
        _post(h['url'], message)


def _fmt(template, value, threshold, **extra):
    try:
        return template.format(value=value, threshold=threshold, **extra)
    except (KeyError, ValueError, IndexError):
        return template  # return raw template if substitution fails


def check_metrics(all_data):
    global _prev_net, _prev_net_at

    now = time.time()
    hooks = settings_store.get_webhooks()
    if not hooks:
        return

    th   = settings_store.get_thresholds()
    msgs = settings_store.get_messages()
    en   = settings_store.get_enabled()
    cd   = float(th.get('cooldown_sec', 300))

    # CPU usage
    cpu = 0.0
    if all_data.get('cpu'):
        cpu = float(all_data['cpu'].get('total_cpu') or 0)
    elif all_data.get('overview'):
        cpu = float(all_data['overview'].get('cpu_usage') or 0)
    if cpu >= th['cpu_crit'] and en.get('cpu', True):
        _fire(hooks, 'cpu_crit',
              _fmt(msgs['msg_cpu_crit'], f'{cpu:.1f}%', f'{th["cpu_crit"]:.0f}%'), cd)
    elif cpu >= th['cpu_warn'] and en.get('cpu', True):
        _fire(hooks, 'cpu_warn',
              _fmt(msgs['msg_cpu_warn'], f'{cpu:.1f}%', f'{th["cpu_warn"]:.0f}%'), cd)

    # RAM usage
    ram = 0.0
    if all_data.get('ram') and all_data['ram'].get('ram_info'):
        ram = float(all_data['ram']['ram_info'].get('used_percent') or 0)
    elif all_data.get('overview') and all_data['overview'].get('memory_usage'):
        ram = float(all_data['overview']['memory_usage'].get('used_percent') or 0)
    if ram >= th['ram_crit'] and en.get('ram', True):
        _fire(hooks, 'ram_crit',
              _fmt(msgs['msg_ram_crit'], f'{ram:.1f}%', f'{th["ram_crit"]:.0f}%'), cd)
    elif ram >= th['ram_warn'] and en.get('ram', True):
        _fire(hooks, 'ram_warn',
              _fmt(msgs['msg_ram_warn'], f'{ram:.1f}%', f'{th["ram_warn"]:.0f}%'), cd)

    # Swap usage
    if all_data.get('ram'):
        swap_list = all_data['ram'].get('swap_info') or []
        total_mb = sum(float(s.get('size_mb') or 0) for s in swap_list)
        used_mb  = sum(float(s.get('used_mb') or 0) for s in swap_list)
        if total_mb > 0:
            swap_pct = used_mb / total_mb * 100
            if swap_pct >= th['swap_crit'] and en.get('swap', True):
                _fire(hooks, 'swap_crit',
                      _fmt(msgs['msg_swap_crit'], f'{swap_pct:.1f}%', f'{th["swap_crit"]:.0f}%'), cd)
            elif swap_pct >= th['swap_warn'] and en.get('swap', True):
                _fire(hooks, 'swap_warn',
                      _fmt(msgs['msg_swap_warn'], f'{swap_pct:.1f}%', f'{th["swap_warn"]:.0f}%'), cd)

    # CPU temperature
    if all_data.get('cpu') and all_data['cpu'].get('cpu_temperature'):
        cpu_temp = float(all_data['cpu']['cpu_temperature'].get('average') or 0)
        if cpu_temp > 0:
            if cpu_temp >= th['cpu_temp_crit'] and en.get('cpu_temp', True):
                _fire(hooks, 'cpu_temp_crit',
                      _fmt(msgs['msg_cpu_temp_crit'], f'{cpu_temp:.1f}°C', f'{th["cpu_temp_crit"]:.0f}°C'), cd)
            elif cpu_temp >= th['cpu_temp_warn'] and en.get('cpu_temp', True):
                _fire(hooks, 'cpu_temp_warn',
                      _fmt(msgs['msg_cpu_temp_warn'], f'{cpu_temp:.1f}°C', f'{th["cpu_temp_warn"]:.0f}°C'), cd)

    # GPU utilization and temperature
    if all_data.get('gpu') and all_data['gpu'].get('nvidia_available'):
        for g in (all_data['gpu'].get('gpus') or []):
            idx  = g.get('index', 0)
            util = float(g.get('utilization') or 0)
            temp = float(g.get('temperature') or 0)
            if util >= th['gpu_util_crit'] and en.get('gpu_util', True):
                _fire(hooks, f'gpu_util_crit_{idx}',
                      _fmt(msgs['msg_gpu_util_crit'], f'{util:.1f}%', f'{th["gpu_util_crit"]:.0f}%', gpu_index=idx), cd)
            elif util >= th['gpu_util_warn'] and en.get('gpu_util', True):
                _fire(hooks, f'gpu_util_warn_{idx}',
                      _fmt(msgs['msg_gpu_util_warn'], f'{util:.1f}%', f'{th["gpu_util_warn"]:.0f}%', gpu_index=idx), cd)
            if temp >= th['gpu_temp_crit'] and en.get('gpu_temp', True):
                _fire(hooks, f'gpu_temp_crit_{idx}',
                      _fmt(msgs['msg_gpu_temp_crit'], f'{temp:.0f}°C', f'{th["gpu_temp_crit"]:.0f}°C', gpu_index=idx), cd)
            elif temp >= th['gpu_temp_warn'] and en.get('gpu_temp', True):
                _fire(hooks, f'gpu_temp_warn_{idx}',
                      _fmt(msgs['msg_gpu_temp_warn'], f'{temp:.0f}°C', f'{th["gpu_temp_warn"]:.0f}°C', gpu_index=idx), cd)

    # Storage
    if all_data.get('storage'):
        for dk in (all_data['storage'].get('disk_usage') or []):
            fs = dk.get('filesystem', '')
            if any(fs.startswith(p) for p in ('tmpfs', 'overlay', 'devtmpfs', 'udev', 'shm', 'cgroup', 'proc', 'sysfs')):
                continue
            pct = float(dk.get('used_percent') or 0)
            mp  = dk.get('mount_point', fs)
            if pct >= th['storage_crit'] and en.get('storage', True):
                _fire(hooks, f'storage_crit_{mp}',
                      _fmt(msgs['msg_storage_crit'], f'{pct:.1f}%', f'{th["storage_crit"]:.0f}%', mount=mp), cd)
            elif pct >= th['storage_warn'] and en.get('storage', True):
                _fire(hooks, f'storage_warn_{mp}',
                      _fmt(msgs['msg_storage_warn'], f'{pct:.1f}%', f'{th["storage_warn"]:.0f}%', mount=mp), cd)

    # Network rate (derived from cumulative byte counters)
    if all_data.get('network'):
        ifaces = all_data['network'].get('interfaces') or []
        tot_rx = sum(int(i.get('rx_bytes') or 0) for i in ifaces)
        tot_tx = sum(int(i.get('tx_bytes') or 0) for i in ifaces)
        if _prev_net and _prev_net_at:
            dt = now - _prev_net_at
            if dt > 0:
                rx_mbps = max(0, (tot_rx - _prev_net['rx']) / dt) / (1024 * 1024)
                tx_mbps = max(0, (tot_tx - _prev_net['tx']) / dt) / (1024 * 1024)
                if rx_mbps >= th['net_rx_crit_mbps'] and en.get('net_rx', True):
                    _fire(hooks, 'net_rx_crit',
                          _fmt(msgs['msg_net_rx_crit'], f'{rx_mbps:.1f} MB/s', f'{th["net_rx_crit_mbps"]:.0f} MB/s'), cd)
                elif rx_mbps >= th['net_rx_warn_mbps'] and en.get('net_rx', True):
                    _fire(hooks, 'net_rx_warn',
                          _fmt(msgs['msg_net_rx_warn'], f'{rx_mbps:.1f} MB/s', f'{th["net_rx_warn_mbps"]:.0f} MB/s'), cd)
                if tx_mbps >= th['net_tx_crit_mbps'] and en.get('net_tx', True):
                    _fire(hooks, 'net_tx_crit',
                          _fmt(msgs['msg_net_tx_crit'], f'{tx_mbps:.1f} MB/s', f'{th["net_tx_crit_mbps"]:.0f} MB/s'), cd)
                elif tx_mbps >= th['net_tx_warn_mbps'] and en.get('net_tx', True):
                    _fire(hooks, 'net_tx_warn',
                          _fmt(msgs['msg_net_tx_warn'], f'{tx_mbps:.1f} MB/s', f'{th["net_tx_warn_mbps"]:.0f} MB/s'), cd)
        _prev_net    = {'rx': tot_rx, 'tx': tot_tx}
        _prev_net_at = now

    # Load average
    load_1m = 0.0
    if all_data.get('overview') and all_data['overview'].get('load_average'):
        load_1m = float(all_data['overview']['load_average'].get('1min') or 0)
    elif all_data.get('cpu') and all_data['cpu'].get('load_average'):
        load_1m = float(all_data['cpu']['load_average'].get('1min') or 0)
    if load_1m >= th['load_crit'] and en.get('load', True):
        _fire(hooks, 'load_crit',
              _fmt(msgs['msg_load_crit'], f'{load_1m:.2f}', f'{th["load_crit"]:.1f}'), cd)
    elif load_1m >= th['load_warn'] and en.get('load', True):
        _fire(hooks, 'load_warn',
              _fmt(msgs['msg_load_warn'], f'{load_1m:.2f}', f'{th["load_warn"]:.1f}'), cd)

    # Zombie processes
    if all_data.get('processes') and all_data['processes'].get('process_counts'):
        zombies = int(all_data['processes']['process_counts'].get('Z') or 0)
        if zombies >= th['zombie_crit'] and en.get('zombie', True):
            _fire(hooks, 'zombie_crit',
                  _fmt(msgs['msg_zombie_crit'], str(zombies), str(int(th['zombie_crit']))), cd)
        elif zombies >= th['zombie_warn'] and en.get('zombie', True):
            _fire(hooks, 'zombie_warn',
                  _fmt(msgs['msg_zombie_warn'], str(zombies), str(int(th['zombie_warn']))), cd)


def start_alert_loop():
    from app import collector as _collector

    def _loop():
        while True:
            time.sleep(CHECK_INTERVAL)
            try:
                data = _collector.get_cache()
                if data:
                    check_metrics(data)
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()
