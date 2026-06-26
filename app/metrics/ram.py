import subprocess
import os

def get_ram_data():
    try:
        ram_info = get_ram_info()
        swap_info = get_swap_info()
        mem_total_kb = (ram_info.get('total_mb') or 0) * 1024
        top_processes = get_top_memory_processes(mem_total_kb)
        return {
            "ram_info": ram_info,
            "swap_info": swap_info,
            "top_processes": top_processes
        }
    except Exception as e:
        return {"error": str(e)}

def get_ram_info():
    try:
        with open('/host/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    meminfo[key.strip()] = value.strip()

            # Convert to MB for better readability
            mem_total = int(meminfo['MemTotal'].split()[0]) // 1024
            mem_free = int(meminfo['MemFree'].split()[0]) // 1024
            mem_available = int(meminfo['MemAvailable'].split()[0]) // 1024
            buffers = int(meminfo.get('Buffers', '0').split()[0]) // 1024
            cached = int(meminfo.get('Cached', '0').split()[0]) // 1024

            used = mem_total - mem_available
            used_percent = (used / mem_total) * 100 if mem_total > 0 else 0

            return {
                "total_mb": mem_total,
                "used_mb": used,
                "free_mb": mem_free,
                "available_mb": mem_available,
                "buffers_mb": buffers,
                "cached_mb": cached,
                "used_percent": used_percent
            }
    except:
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "available_mb": 0,
            "buffers_mb": 0,
            "cached_mb": 0,
            "used_percent": 0
        }

def get_swap_info():
    try:
        with open('/host/proc/swaps', 'r') as f:
            lines = f.readlines()[1:]  # Skip header

        if lines:
            swap_data = []
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 5:
                        swap_data.append({
                            "file": parts[0],
                            "type": parts[1],
                            "size_mb": int(parts[2]) // 1024,
                            "used_mb": int(parts[3]) // 1024,
                            "priority": parts[4]
                        })
            return swap_data
        return []
    except:
        return []

def get_top_memory_processes(mem_total_kb=0):
    try:
        processes = []
        proc_base = '/host/proc'
        for pid_str in os.listdir(proc_base):
            if not pid_str.isdigit():
                continue
            pid_dir = f'{proc_base}/{pid_str}'
            try:
                status = {}
                with open(f'{pid_dir}/status', 'r') as f:
                    for line in f:
                        if ':' in line:
                            k, v = line.split(':', 1)
                            status[k.strip()] = v.strip()

                rss_parts = status.get('VmRSS', '0 kB').split()
                vm_rss_kb = int(rss_parts[0]) if rss_parts else 0
                name = status.get('Name', 'unknown')

                try:
                    with open(f'{pid_dir}/cmdline', 'rb') as f:
                        cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
                    if not cmdline:
                        cmdline = f'[{name}]'
                except Exception:
                    cmdline = f'[{name}]'

                mem_pct = (vm_rss_kb / mem_total_kb * 100) if mem_total_kb > 0 else 0
                processes.append({
                    'pid': int(pid_str),
                    'name': name,
                    'vm_rss_mb': vm_rss_kb // 1024,
                    'memory_percent': round(mem_pct, 1),
                    'command': cmdline[:120],
                })
            except (PermissionError, FileNotFoundError, ProcessLookupError, ValueError):
                continue

        processes.sort(key=lambda p: p['vm_rss_mb'], reverse=True)
        return processes[:10]
    except Exception as e:
        return []