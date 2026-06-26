import subprocess
import os

def get_gpu_data():
    try:
        if not is_nvidia_available():
            return {
                "nvidia_available": False,
                "gpu_count": 0,
                "gpus": [],
                "other_gpus": detect_other_gpus(),
                "error": "NVIDIA GPU not detected or nvidia-smi not available"
            }

        gpus = get_nvidia_gpu_info()
        return {
            "nvidia_available": True,
            "gpu_count": len(gpus),
            "gpus": gpus,
            "gpu_processes": get_gpu_processes(),
        }
    except Exception as e:
        return {"error": str(e)}

def is_nvidia_available():
    try:
        result = subprocess.run(['which', 'nvidia-smi'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def _safe_float(s):
    try:
        return float(s)
    except:
        return 0.0

def _safe_int(s):
    try:
        return int(s)
    except:
        return 0

def get_cuda_version():
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'CUDA Version' in line:
                import re
                m = re.search(r'CUDA Version:\s*([\d.]+)', line)
                if m:
                    return m.group(1)
    except:
        pass
    return 'N/A'

def get_nvidia_gpu_info():
    try:
        result = subprocess.run([
            'nvidia-smi',
            '--query-gpu=index,name,utilization.gpu,memory.total,memory.used,memory.free,'
                        'temperature.gpu,power.draw,power.limit,fan.speed,driver_version',
            '--format=csv,noheader,nounits'
        ], capture_output=True, text=True, timeout=10)

        gpus = []
        if result.returncode != 0:
            return gpus

        cuda_version = get_cuda_version()

        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            v = [x.strip() for x in line.split(',')]
            if len(v) < 11:
                continue
            mem_total = _safe_int(v[3])
            mem_used  = _safe_int(v[4])
            mem_pct   = round(mem_used / mem_total * 100, 1) if mem_total > 0 else 0
            gpus.append({
                "index":             _safe_int(v[0]),
                "name":              v[1],
                "utilization":       _safe_float(v[2]),
                "memory_total_mb":   mem_total,
                "memory_used_mb":    mem_used,
                "memory_free_mb":    _safe_int(v[5]),
                "memory_used_pct":   mem_pct,
                "temperature":       _safe_int(v[6]),
                "power_draw_watts":  _safe_float(v[7]),
                "power_limit_watts": _safe_float(v[8]),
                "fan_speed":         _safe_int(v[9]),
                "driver_version":    v[10],
                "cuda_version":      cuda_version,
            })
        return gpus
    except:
        return []

def get_gpu_processes():
    # Try pmon first — gives SM% and MEM% per process
    try:
        result = subprocess.run(
            ['nvidia-smi', 'pmon', '-c', '1', '-s', 'um'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            procs = []
            for line in result.stdout.strip().split('\n'):
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 5 or parts[1] == '-':
                    continue
                # pmon columns: gpu pid type sm% mem% enc% dec% jpg% ofa% fb(MB) ccpm(MB) command
                procs.append({
                    'gpu_index': _safe_int(parts[0]),
                    'pid':       parts[1],
                    'type':      parts[2] if len(parts) > 2 else '',
                    'sm_pct':    _safe_float(parts[3]) if parts[3] != '-' else 0.0,
                    'mem_pct':   _safe_float(parts[4]) if parts[4] != '-' else 0.0,
                    'fb_mb':     _safe_int(parts[9])  if len(parts) > 9  and parts[9]  != '-' else 0,
                    'command':   parts[11] if len(parts) > 11 else '',
                })
            if procs:
                return procs
    except Exception:
        pass

    # Fallback: --query-compute-apps (no SM%, only VRAM used)
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-compute-apps=pid,process_name,used_gpu_memory',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            procs = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = [x.strip() for x in line.split(',')]
                if len(parts) < 3:
                    continue
                procs.append({
                    'gpu_index': 0,
                    'pid':       parts[0],
                    'type':      'C',
                    'sm_pct':    0.0,
                    'mem_pct':   0.0,
                    'fb_mb':     _safe_int(parts[2]),
                    'command':   parts[1],
                })
            return procs
    except Exception:
        pass

    return []


def detect_other_gpus():
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.strip().split('\n'):
            if any(k in line for k in ('VGA', 'Display', '3D controller')):
                gpus.append({"device": line.strip()})
        return gpus
    except:
        return []
