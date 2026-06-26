import subprocess
import os
import pwd
import time
from datetime import datetime

def get_system_data():
    try:
        # Get system information
        system_info = get_system_info()

        # Get boot time
        boot_time = get_boot_time()

        # Get system load
        load_average = get_load_average()

        # Get system users
        users = get_system_users()

        # Get system uptime
        uptime = get_system_uptime()

        # Get kernel information
        kernel_info = get_kernel_info()

        # Get system architecture
        architecture = get_system_architecture()

        return {
            "system_info": system_info,
            "boot_time": boot_time,
            "load_average": load_average,
            "users": users,
            "uptime": uptime,
            "kernel_info": kernel_info,
            "architecture": architecture
        }
    except Exception as e:
        return {"error": str(e)}

def get_system_info():
    try:
        # Get hostname
        hostname = subprocess.check_output(['hostname'], text=True).strip()

        # Get OS information
        os_info = "Unknown"
        if os.path.exists('/host/etc/os-release'):
            with open('/host/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        os_info = line.split('=', 1)[1].strip('"')
                        break

        # Get kernel version
        kernel_version = subprocess.check_output(['uname', '-r'], text=True).strip()

        # Get machine hardware name
        machine = subprocess.check_output(['uname', '-m'], text=True).strip()

        return {
            "hostname": hostname,
            "os": os_info,
            "kernel": kernel_version,
            "machine": machine
        }
    except:
        return {
            "hostname": "Unknown",
            "os": "Unknown",
            "kernel": "Unknown",
            "machine": "Unknown"
        }

def get_boot_time():
    try:
        with open('/host/proc/stat', 'r') as f:
            for line in f:
                if line.startswith('btime'):
                    btime = int(line.split()[1])
                    boot_time = datetime.fromtimestamp(btime)
                    return boot_time.strftime("%Y-%m-%d %H:%M:%S")
        return "Unknown"
    except:
        return "Unknown"

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

def get_system_users():
    # Scan /host/proc loginuid files rather than running `who`, which relies on
    # utmp — unreliable in Docker even with a bind-mount of /var/run/utmp.
    seen = {}  # uid -> {user, tty, login_time, _mtime}
    try:
        for pid in os.listdir('/host/proc'):
            if not pid.isdigit():
                continue
            pid_path = f'/host/proc/{pid}'
            try:
                with open(f'{pid_path}/loginuid') as f:
                    uid = int(f.read().strip())
                # 4294967295 means "not set" (kernel threads, unattended daemons)
                if uid >= 4294967295:
                    continue

                try:
                    username = pwd.getpwuid(uid).pw_name
                except KeyError:
                    username = str(uid)

                tty = ''
                try:
                    with open(f'{pid_path}/stat') as f:
                        stat_data = f.read()
                    # Format: pid (comm) state ppid pgrp session tty_nr ...
                    rparen = stat_data.rfind(')')
                    fields = stat_data[rparen + 2:].split()
                    tty_nr = int(fields[4])  # index 4 = tty_nr after state/ppid/pgrp/session
                    if tty_nr:
                        major = (tty_nr >> 8) & 0xfff
                        minor = (tty_nr & 0xff) | ((tty_nr >> 12) & 0xffffff00)
                        if major == 136:
                            tty = f'pts/{minor}'
                        elif major == 4:
                            tty = f'tty{minor}'
                except Exception:
                    pass

                mtime = os.path.getmtime(pid_path)

                if uid not in seen:
                    seen[uid] = {
                        'user': username,
                        'tty': tty,
                        'login_time': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
                        '_mtime': mtime,
                    }
                else:
                    # Track the oldest process to approximate login time
                    if mtime < seen[uid]['_mtime']:
                        seen[uid]['_mtime'] = mtime
                        seen[uid]['login_time'] = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                    if tty and not seen[uid]['tty']:
                        seen[uid]['tty'] = tty
            except Exception:
                continue

        return [
            {'user': u['user'], 'tty': u['tty'] or '?', 'login_time': u['login_time']}
            for u in seen.values()
        ]
    except Exception:
        return []

def get_system_uptime():
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

def get_kernel_info():
    try:
        # Get kernel version
        kernel_version = subprocess.check_output(['uname', '-r'], text=True).strip()

        # Get kernel build date
        build_date = "Unknown"
        try:
            with open('/host/proc/version', 'r') as f:
                version_info = f.read().strip()
                if 'build' in version_info:
                    build_date = version_info.split('build')[1].split()[0]
        except:
            pass

        # Get kernel command line
        cmdline = "Unknown"
        try:
            with open('/host/proc/cmdline', 'r') as f:
                cmdline = f.read().strip()
        except:
            pass

        return {
            "version": kernel_version,
            "build_date": build_date,
            "command_line": cmdline
        }
    except:
        return {
            "version": "Unknown",
            "build_date": "Unknown",
            "command_line": "Unknown"
        }

def get_system_architecture():
    try:
        # Get system architecture
        architecture = subprocess.check_output(['uname', '-m'], text=True).strip()
        return architecture
    except:
        return "Unknown"