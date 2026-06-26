import os
import time

PROC_PATH = '/host/proc'

_prev_cpu = {}  # {pid: (ticks, timestamp)}
_prev_io  = {}  # {pid: (read_bytes, write_bytes, timestamp)}
_ticks_per_sec = None
_uid_name_cache = {}


def _uid_to_name(uid_str):
    if uid_str in _uid_name_cache:
        return _uid_name_cache[uid_str]
    name = uid_str
    for passwd_path in ('/host/etc/passwd', '/etc/passwd'):
        try:
            with open(passwd_path, 'r') as f:
                for line in f:
                    parts = line.strip().split(':')
                    if len(parts) >= 3 and parts[2] == uid_str:
                        name = parts[0]
                        break
            break
        except Exception:
            continue
    _uid_name_cache[uid_str] = name
    return name


def _get_ticks():
    global _ticks_per_sec
    if _ticks_per_sec is None:
        try:
            _ticks_per_sec = os.sysconf('SC_CLK_TCK')
        except Exception:
            _ticks_per_sec = 100
    return _ticks_per_sec


def _get_mem_total_kb():
    try:
        with open(f'{PROC_PATH}/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _read_process(pid):
    pid_path = f'{PROC_PATH}/{pid}'
    try:
        status = {}
        with open(f'{pid_path}/status', 'r') as f:
            for line in f:
                k, _, v = line.partition(':')
                status[k.strip()] = v.strip()

        try:
            with open(f'{pid_path}/cmdline', 'rb') as f:
                cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
            if not cmdline:
                cmdline = status.get('Name', '')
        except Exception:
            cmdline = status.get('Name', '')

        def kb(s):
            parts = s.split()
            return int(parts[0]) if parts else 0

        vm_size_kb = kb(status.get('VmSize', '0'))
        vm_rss_kb = kb(status.get('VmRSS', '0'))

        utime = stime = 0
        try:
            with open(f'{pid_path}/stat', 'r') as f:
                data = f.read()
            comm_end = data.rfind(')')
            if comm_end >= 0:
                fields = data[comm_end + 2:].split()
                utime = int(fields[11])
                stime = int(fields[12])
        except Exception:
            pass

        cpu_ticks = utime + stime
        tps = _get_ticks()
        total_secs = cpu_ticks / tps
        cpu_time_str = f'{int(total_secs // 60)}:{int(total_secs % 60):02d}'

        now = time.time()
        cpu_pct = 0.0
        if pid in _prev_cpu:
            prev_ticks, prev_time = _prev_cpu[pid]
            dt = now - prev_time
            if dt > 0:
                cpu_pct = max(0.0, (cpu_ticks - prev_ticks) / tps / dt * 100)
        _prev_cpu[pid] = (cpu_ticks, now)

        state_val = status.get('State', 'U')
        state = state_val[0] if state_val else 'U'

        uid = _uid_to_name(status.get('Uid', '0').split()[0])

        io_read_bytes = 0
        io_write_bytes = 0
        try:
            with open(f'{pid_path}/io', 'r') as f:
                for line in f:
                    if line.startswith('read_bytes:'):
                        io_read_bytes = int(line.split()[1])
                    elif line.startswith('write_bytes:'):
                        io_write_bytes = int(line.split()[1])
        except (PermissionError, FileNotFoundError, OSError):
            pass

        io_read_bps = 0.0
        io_write_bps = 0.0
        if pid in _prev_io:
            prev_read, prev_write, prev_time = _prev_io[pid]
            dt = now - prev_time
            if dt > 0:
                io_read_bps  = max(0.0, (io_read_bytes  - prev_read)  / dt)
                io_write_bps = max(0.0, (io_write_bytes - prev_write) / dt)
        _prev_io[pid] = (io_read_bytes, io_write_bytes, now)

        return {
            "pid": pid,
            "user": uid,
            "cpu_percent": round(cpu_pct, 1),
            "memory_percent": 0.0,
            "virtual_memory": str(vm_size_kb),
            "resident_memory": str(vm_rss_kb),
            "_rss_kb": vm_rss_kb,
            "status": state,
            "cpu_time": cpu_time_str,
            "command": cmdline[:120],
            "disk_read_bps":   round(io_read_bps,   1),
            "disk_write_bps":  round(io_write_bps,  1),
            "disk_read_bytes": io_read_bytes,
            "disk_write_bytes": io_write_bytes,
        }
    except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
        return None


def _collect_all():
    mem_total = _get_mem_total_kb()
    try:
        pids = [e for e in os.listdir(PROC_PATH) if e.isdigit()]
    except Exception:
        return []

    processes = []
    for pid in pids:
        proc = _read_process(pid)
        if proc is None:
            continue
        if mem_total > 0:
            proc['memory_percent'] = round(proc['_rss_kb'] / mem_total * 100, 1)
        del proc['_rss_kb']
        processes.append(proc)

    current_pids = {p['pid'] for p in processes}
    for stale in [p for p in list(_prev_cpu) if p not in current_pids]:
        _prev_cpu.pop(stale, None)
    for stale in [p for p in list(_prev_io) if p not in current_pids]:
        _prev_io.pop(stale, None)

    return processes


def get_processes_data():
    try:
        all_procs = _collect_all()
        top_disk = sorted(all_procs, key=lambda p: p['disk_read_bytes'] + p['disk_write_bytes'], reverse=True)[:50]
        counts = {}
        for p in all_procs:
            counts[p['status']] = counts.get(p['status'], 0) + 1
        return {
            "all_processes": all_procs,
            "top_disk":      top_disk,
            "process_counts": counts,
        }
    except Exception as e:
        return {"error": str(e)}
