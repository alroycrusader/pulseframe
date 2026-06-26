import json
import os
import threading
import uuid

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'settings.json'
)
_lock = threading.Lock()

DEFAULT_THRESHOLDS = {
    'cooldown_sec':      300.0,  # seconds before the same alert fires again
    'cpu_warn':          80.0,
    'cpu_crit':          90.0,
    'ram_warn':          85.0,
    'ram_crit':          95.0,
    'swap_warn':         50.0,
    'swap_crit':         80.0,
    'cpu_temp_warn':     70.0,
    'cpu_temp_crit':     85.0,
    'gpu_util_warn':     80.0,
    'gpu_util_crit':     90.0,
    'gpu_temp_warn':     75.0,
    'gpu_temp_crit':     85.0,
    'storage_warn':      80.0,
    'storage_crit':      90.0,
    'net_rx_warn_mbps':  100.0,
    'net_rx_crit_mbps':  500.0,
    'net_tx_warn_mbps':  100.0,
    'net_tx_crit_mbps':  500.0,
    'load_warn':         4.0,
    'load_crit':         8.0,
    'zombie_warn':       5.0,
    'zombie_crit':       20.0,
}

DEFAULT_MESSAGES = {
    'msg_cpu_warn':      '\U0001f7e1 **CPU WARNING** `{value}` (≥{threshold})',
    'msg_cpu_crit':      '\U0001f534 **CPU CRITICAL** `{value}` (≥{threshold})',
    'msg_ram_warn':      '\U0001f7e1 **RAM WARNING** `{value}` (≥{threshold})',
    'msg_ram_crit':      '\U0001f534 **RAM CRITICAL** `{value}` (≥{threshold})',
    'msg_swap_warn':     '\U0001f7e1 **SWAP WARNING** `{value}` (≥{threshold})',
    'msg_swap_crit':     '\U0001f534 **SWAP CRITICAL** `{value}` (≥{threshold})',
    'msg_cpu_temp_warn': '\U0001f7e1 **CPU TEMP WARNING** `{value}` (≥{threshold})',
    'msg_cpu_temp_crit': '\U0001f534 **CPU TEMP CRITICAL** `{value}` (≥{threshold})',
    'msg_gpu_util_warn': '\U0001f7e1 **GPU{gpu_index} UTIL WARNING** `{value}` (≥{threshold})',
    'msg_gpu_util_crit': '\U0001f534 **GPU{gpu_index} UTIL CRITICAL** `{value}` (≥{threshold})',
    'msg_gpu_temp_warn': '\U0001f7e1 **GPU{gpu_index} TEMP WARNING** `{value}` (≥{threshold})',
    'msg_gpu_temp_crit': '\U0001f534 **GPU{gpu_index} TEMP CRITICAL** `{value}` (≥{threshold})',
    'msg_storage_warn':  '\U0001f7e1 **STORAGE WARNING** `{mount}` at `{value}` (≥{threshold})',
    'msg_storage_crit':  '\U0001f534 **STORAGE CRITICAL** `{mount}` at `{value}` (≥{threshold})',
    'msg_net_rx_warn':   '\U0001f7e1 **NET RX WARNING** `{value}` (≥{threshold})',
    'msg_net_rx_crit':   '\U0001f534 **NET RX CRITICAL** `{value}` (≥{threshold})',
    'msg_net_tx_warn':   '\U0001f7e1 **NET TX WARNING** `{value}` (≥{threshold})',
    'msg_net_tx_crit':   '\U0001f534 **NET TX CRITICAL** `{value}` (≥{threshold})',
    'msg_load_warn':     '\U0001f7e1 **LOAD WARNING** `{value}` (≥{threshold})',
    'msg_load_crit':     '\U0001f534 **LOAD CRITICAL** `{value}` (≥{threshold})',
    'msg_zombie_warn':   '\U0001f7e1 **ZOMBIE PROCESSES WARNING** `{value}` (≥{threshold})',
    'msg_zombie_crit':   '\U0001f534 **ZOMBIE PROCESSES CRITICAL** `{value}` (≥{threshold})',
}


DEFAULT_ENABLED = {
    'cpu':     True,
    'ram':     True,
    'swap':    True,
    'cpu_temp':True,
    'gpu_util':True,
    'gpu_temp':True,
    'storage': True,
    'net_rx':  True,
    'net_tx':  True,
    'load':    True,
    'zombie':  True,
}


def _load():
    if not os.path.exists(SETTINGS_FILE):
        return {
            'webhooks':   [],
            'thresholds': DEFAULT_THRESHOLDS.copy(),
            'messages':   DEFAULT_MESSAGES.copy(),
            'enabled':    DEFAULT_ENABLED.copy(),
        }
    with open(SETTINGS_FILE, 'r') as f:
        data = json.load(f)
    th = data.get('thresholds', {})
    for k, v in DEFAULT_THRESHOLDS.items():
        if k not in th:
            th[k] = v
    data['thresholds'] = th
    msgs = data.get('messages', {})
    for k, v in DEFAULT_MESSAGES.items():
        if k not in msgs:
            msgs[k] = v
    data['messages'] = msgs
    en = data.get('enabled', {})
    for k, v in DEFAULT_ENABLED.items():
        if k not in en:
            en[k] = v
    data['enabled'] = en
    if 'webhooks' not in data:
        data['webhooks'] = []
    return data


def _save(data):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_webhooks():
    with _lock:
        return list(_load().get('webhooks', []))


def add_webhook(name, url):
    with _lock:
        data = _load()
        hook = {'id': str(uuid.uuid4()), 'name': name, 'url': url}
        data['webhooks'].append(hook)
        _save(data)
        return hook


def update_webhook(hook_id, name, url):
    with _lock:
        data = _load()
        for h in data['webhooks']:
            if h['id'] == hook_id:
                h['name'] = name
                h['url'] = url
                _save(data)
                return dict(h)
        return None


def delete_webhook(hook_id):
    with _lock:
        data = _load()
        data['webhooks'] = [h for h in data['webhooks'] if h['id'] != hook_id]
        _save(data)


def get_thresholds():
    with _lock:
        return dict(_load().get('thresholds', DEFAULT_THRESHOLDS.copy()))


def set_thresholds(thresholds):
    with _lock:
        data = _load()
        new_th = {}
        for k, default in DEFAULT_THRESHOLDS.items():
            v = thresholds.get(k, default)
            try:
                val = float(v)
            except (TypeError, ValueError):
                val = float(default)
            # enforce a 60-second minimum cooldown to prevent accidental spam
            if k == 'cooldown_sec':
                val = max(60.0, val)
            new_th[k] = val
        data['thresholds'] = new_th
        _save(data)
        return dict(new_th)


def get_messages():
    with _lock:
        return dict(_load().get('messages', DEFAULT_MESSAGES.copy()))


def set_messages(messages):
    with _lock:
        data = _load()
        new_msgs = {}
        for k, default in DEFAULT_MESSAGES.items():
            v = messages.get(k, '')
            new_msgs[k] = str(v).strip() or default
        data['messages'] = new_msgs
        _save(data)
        return dict(new_msgs)


def get_enabled():
    with _lock:
        return dict(_load().get('enabled', DEFAULT_ENABLED.copy()))


def set_enabled(enabled):
    with _lock:
        data = _load()
        new_en = {}
        for k in DEFAULT_ENABLED:
            new_en[k] = bool(enabled.get(k, True))
        data['enabled'] = new_en
        _save(data)
        return dict(new_en)
