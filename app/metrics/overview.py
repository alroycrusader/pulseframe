import os
import socket
import platform
import time as _time
from datetime import datetime

_system_info_cache = None

def get_overview_data():
    try:
        # Get system information
        system_info = get_system_info()

        # Get overall CPU usage
        cpu_usage = get_cpu_usage()

        # Get overall memory usage
        memory_usage = get_memory_usage()

        # Get disk usage
        disk_usage = get_disk_usage()

        # Get uptime
        uptime = get_uptime()

        # Get load average
        load_average = get_load_average()

        # Get number of running processes
        process_count = get_process_count()

        # Get system time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "system_info": system_info,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "disk_usage": disk_usage,
            "uptime": uptime,
            "load_average": load_average,
            "process_count": process_count,
            "current_time": current_time
        }
    except Exception as e:
        return {"error": str(e)}

def get_system_info():
    global _system_info_cache
    if _system_info_cache is not None:
        return _system_info_cache

    try:
        # Get hostname
        try:
            with open('/host/proc/sys/kernel/hostname', 'r') as f:
                hostname = f.read().strip()
        except OSError:
            hostname = socket.gethostname()

        # Get OS information
        os_info = "Unknown"
        if os.path.exists('/host/etc/os-release'):
            with open('/host/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        os_info = line.split('=', 1)[1].strip().strip('"')
                        break

        # Get kernel version
        try:
            with open('/host/proc/sys/kernel/osrelease', 'r') as f:
                kernel_version = f.read().strip()
        except OSError:
            kernel_version = platform.release()

        _system_info_cache = {
            "hostname": hostname,
            "os": os_info,
            "kernel": kernel_version
        }
        return _system_info_cache
    except:
        return {
            "hostname": "Unknown",
            "os": "Unknown",
            "kernel": "Unknown"
        }

def _read_cpu_stat():
    with open('/host/proc/stat', 'r') as f:
        parts = f.readline().split()
    total = sum(int(x) for x in parts[1:8] if x.isdigit())
    idle  = int(parts[4]) + (int(parts[5]) if len(parts) > 5 else 0)
    return total, idle

def get_cpu_usage():
    try:
        t1, i1 = _read_cpu_stat()
        _time.sleep(0.15)
        t2, i2 = _read_cpu_stat()
        dt = t2 - t1
        di = i2 - i1
        return max(0.0, min(100.0, 100.0 * (dt - di) / dt)) if dt > 0 else 0.0
    except:
        return 0.0

def get_memory_usage():
    try:
        with open('/host/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    meminfo[key.strip()] = value.strip()

            mem_total = int(meminfo['MemTotal'].split()[0])
            mem_free = int(meminfo['MemFree'].split()[0])
            mem_available = int(meminfo['MemAvailable'].split()[0])

            used = mem_total - mem_available
            used_percent = (used / mem_total) * 100 if mem_total > 0 else 0

            return {
                "total_mb": mem_total // 1024,
                "used_mb": used // 1024,
                "available_mb": mem_available // 1024,
                "used_percent": used_percent
            }
    except:
        return {
            "total_mb": 0,
            "used_mb": 0,
            "available_mb": 0,
            "used_percent": 0
        }

def get_disk_usage():
    try:
        for path in ('/host', '/'):
            try:
                st = os.statvfs(path)
                break
            except OSError:
                continue
        else:
            return {"filesystem": "/", "size": "0", "used": "0", "available": "0", "used_percent": 0}

        total = st.f_blocks * st.f_frsize
        free  = st.f_bfree  * st.f_frsize
        used  = total - free
        used_pct = int(used / total * 100) if total > 0 else 0

        def _fmt(b):
            gb = b / (1024 ** 3)
            if gb >= 1:
                return f"{gb:.1f}G"
            return f"{b / (1024 ** 2):.0f}M"

        return {
            "filesystem": "host",
            "size": _fmt(total),
            "used": _fmt(used),
            "available": _fmt(free),
            "used_percent": used_pct,
        }
    except Exception:
        return {"filesystem": "/", "size": "0", "used": "0", "available": "0", "used_percent": 0}

def get_uptime():
    try:
        with open('/host/proc/uptime', 'r') as f:
            uptime_seconds = float(f.read().split()[0])
            uptime_days = int(uptime_seconds // 86400)
            uptime_hours = int((uptime_seconds % 86400) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            return {
                "total_seconds": uptime_seconds,
                "days": uptime_days,
                "hours": uptime_hours,
                "minutes": uptime_minutes
            }
    except:
        return {
            "total_seconds": 0,
            "days": 0,
            "hours": 0,
            "minutes": 0
        }

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

def get_process_count():
    try:
        return sum(1 for e in os.listdir('/host/proc') if e.isdigit())
    except Exception:
        return 0
