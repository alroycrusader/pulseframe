import os
import re
import time

_cpu_model_cache = None
_physical_cores_cache = None
_logical_cores_cache = None

_cpu_top_prev = {}  # {pid_str: (ticks, timestamp)}

def get_cpu_data():
    try:
        total_cpu, core_usage = _measure_cpu_usage()
        return {
            "cpu_model": get_cpu_model(),
            "physical_cores": get_physical_cores(),
            "logical_cores": get_logical_cores(),
            "per_core_usage": core_usage,
            "total_cpu": total_cpu,
            "cpu_frequency": get_cpu_frequency(),
            "cpu_temperature": get_cpu_temperature(),
            "load_average": get_load_average(),
            "top_processes": get_top_cpu_processes()
        }
    except Exception as e:
        return {"error": str(e)}

def get_cpu_model():
    global _cpu_model_cache
    if _cpu_model_cache is not None:
        return _cpu_model_cache
    try:
        with open('/host/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    _cpu_model_cache = line.split(':')[1].strip()
                    return _cpu_model_cache
    except Exception:
        pass
    _cpu_model_cache = "Unknown CPU"
    return _cpu_model_cache

def get_physical_cores():
    global _physical_cores_cache
    if _physical_cores_cache is not None:
        return _physical_cores_cache
    try:
        cores = set()
        with open('/host/proc/cpuinfo', 'r') as f:
            current_physical_id = None
            current_core_id = None
            for line in f:
                if line.startswith('physical id'):
                    current_physical_id = line.split(':')[1].strip()
                elif line.startswith('core id'):
                    current_core_id = line.split(':')[1].strip()
                elif line.strip() == '':
                    if current_physical_id is not None and current_core_id is not None:
                        cores.add((current_physical_id, current_core_id))
                    current_physical_id = None
                    current_core_id = None
        _physical_cores_cache = len(cores) if cores else get_logical_cores()
        return _physical_cores_cache
    except Exception:
        pass
    _physical_cores_cache = 0
    return _physical_cores_cache

def get_logical_cores():
    global _logical_cores_cache
    if _logical_cores_cache is not None:
        return _logical_cores_cache
    try:
        count = 0
        with open('/host/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('processor'):
                    count += 1
        _logical_cores_cache = count
        return _logical_cores_cache
    except Exception:
        pass
    _logical_cores_cache = 0
    return _logical_cores_cache

def _read_proc_stat():
    """Return {cpu_label: (total_jiffies, idle_jiffies)} for all CPU lines."""
    result = {}
    with open('/host/proc/stat', 'r') as f:
        for line in f:
            if not line.startswith('cpu'):
                break
            parts = line.split()
            if len(parts) < 5:
                continue
            total = sum(int(x) for x in parts[1:8] if x.isdigit())
            idle  = int(parts[4]) + (int(parts[5]) if len(parts) > 5 else 0)
            result[parts[0]] = (total, idle)
    return result

def _measure_cpu_usage():
    try:
        snap1 = _read_proc_stat()
        time.sleep(0.15)
        snap2 = _read_proc_stat()

        # Total
        total_cpu = 0.0
        if 'cpu' in snap1 and 'cpu' in snap2:
            dt = snap2['cpu'][0] - snap1['cpu'][0]
            di = snap2['cpu'][1] - snap1['cpu'][1]
            total_cpu = max(0.0, min(100.0, 100.0 * (dt - di) / dt)) if dt > 0 else 0.0

        # Per-core
        core_data = []
        core_idx = 0
        for key in sorted(snap1.keys()):
            if key == 'cpu':
                continue
            if key not in snap2:
                continue
            dt = snap2[key][0] - snap1[key][0]
            di = snap2[key][1] - snap1[key][1]
            usage = 100.0 * (dt - di) / dt if dt > 0 else 0.0
            core_data.append({"core": core_idx, "usage": max(0.0, min(100.0, usage))})
            core_idx += 1

        return total_cpu, core_data
    except Exception:
        return 0.0, []

def get_cpu_frequency():
    try:
        # Try to get CPU frequency from /sys
        frequencies = []
        try:
            with open('/host/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('cpu MHz'):
                        freq = float(line.split(':')[1].strip())
                        frequencies.append(freq)
        except:
            pass

        if frequencies:
            return {
                "current": frequencies[0],
                "min": min(frequencies),
                "max": max(frequencies)
            }
        return {"current": 0, "min": 0, "max": 0}
    except:
        return {"current": 0, "min": 0, "max": 0}

def get_cpu_temperature():
    try:
        # Try to get CPU temperature from thermal zones
        temp_sensors = []
        thermal_path = '/host/sys/class/thermal'
        if os.path.exists(thermal_path):
            for zone in os.listdir(thermal_path):
                if zone.startswith('thermal_zone'):
                    temp_file = os.path.join(thermal_path, zone, 'temp')
                    if os.path.exists(temp_file):
                        try:
                            with open(temp_file, 'r') as f:
                                temp = int(f.read().strip()) / 1000.0
                                temp_sensors.append(temp)
                        except:
                            pass

        # Also check hwmon sensors
        hwmon_path = '/host/sys/class/hwmon'
        if os.path.exists(hwmon_path):
            for hwmon in os.listdir(hwmon_path):
                temp_file = os.path.join(hwmon_path, hwmon, 'temp1_input')
                if os.path.exists(temp_file):
                    try:
                        with open(temp_file, 'r') as f:
                            temp = int(f.read().strip()) / 1000.0
                            temp_sensors.append(temp)
                    except:
                        pass

        if temp_sensors:
            return {
                "average": sum(temp_sensors) / len(temp_sensors),
                "max": max(temp_sensors),
                "min": min(temp_sensors)
            }
        return {"average": 0, "max": 0, "min": 0}
    except:
        return {"average": 0, "max": 0, "min": 0}

def get_load_average():
    try:
        with open('/host/proc/loadavg', 'r') as f:
            loadavg = f.read().strip().split()
            return {
                "1min": float(loadavg[0]),
                "5min": float(loadavg[1]),
                "15min": float(loadavg[2])
            }
    except:
        return {"1min": 0, "5min": 0, "15min": 0}

def _uid_to_name_cpu(uid_str):
    for passwd_path in ('/host/etc/passwd', '/etc/passwd'):
        try:
            with open(passwd_path, 'r') as f:
                for line in f:
                    parts = line.strip().split(':')
                    if len(parts) >= 3 and parts[2] == uid_str:
                        return parts[0]
            break
        except Exception:
            continue
    return uid_str

def get_top_cpu_processes():
    global _cpu_top_prev
    proc_path = '/host/proc'
    tps = 100
    try:
        tps = os.sysconf('SC_CLK_TCK')
    except Exception:
        pass

    now = time.time()
    procs = []
    try:
        pids = [e for e in os.listdir(proc_path) if e.isdigit()]
    except Exception:
        return []

    for pid in pids:
        pid_dir = f'{proc_path}/{pid}'
        try:
            # Read stat for CPU ticks
            with open(f'{pid_dir}/stat', 'r') as f:
                data = f.read()
            comm_end = data.rfind(')')
            if comm_end < 0:
                continue
            fields = data[comm_end + 2:].split()
            utime = int(fields[11])
            stime = int(fields[12])
            ticks = utime + stime

            cpu_pct = 0.0
            if pid in _cpu_top_prev:
                prev_ticks, prev_time = _cpu_top_prev[pid]
                dt = now - prev_time
                if dt > 0:
                    cpu_pct = max(0.0, (ticks - prev_ticks) / tps / dt * 100)
            _cpu_top_prev[pid] = (ticks, now)

            # Read status for uid and memory
            status = {}
            with open(f'{pid_dir}/status', 'r') as f:
                for line in f:
                    k, _, v = line.partition(':')
                    status[k.strip()] = v.strip()

            uid_str = status.get('Uid', '0').split()[0]
            user = _uid_to_name_cpu(uid_str)

            rss_parts = status.get('VmRSS', '0 kB').split()
            vm_rss_kb = int(rss_parts[0]) if rss_parts else 0

            try:
                with open(f'{pid_dir}/cmdline', 'rb') as f:
                    cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
                if not cmdline:
                    cmdline = status.get('Name', '')
            except Exception:
                cmdline = status.get('Name', '')

            procs.append({
                "pid": pid,
                "user": user,
                "cpu_percent": round(cpu_pct, 1),
                "memory_percent": 0.0,
                "virtual_memory": status.get('VmSize', '0 kB').split()[0] if status.get('VmSize') else '0',
                "resident_memory": str(vm_rss_kb),
                "command": cmdline[:120],
            })
        except (PermissionError, FileNotFoundError, ProcessLookupError, ValueError, OSError):
            continue

    # Prune stale pids
    current = set(pids)
    for stale in [p for p in list(_cpu_top_prev) if p not in current]:
        _cpu_top_prev.pop(stale, None)

    procs.sort(key=lambda p: p['cpu_percent'], reverse=True)
    return procs[:10]
