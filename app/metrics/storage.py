import subprocess
import os

def get_storage_data():
    try:
        # Get disk usage information
        disk_usage = get_disk_usage()

        # Get filesystem information
        filesystems = get_filesystems()

        # Get partition information
        partitions = get_partitions()

        return {
            "disk_usage": disk_usage,
            "filesystems": filesystems,
            "partitions": partitions
        }
    except Exception as e:
        return {"error": str(e)}

def get_disk_usage():
    try:
        # Get disk usage using df command
        result = subprocess.run(['df', '-h'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            disk_data = []
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 6:
                        disk_data.append({
                            "filesystem": parts[0],
                            "size": parts[1],
                            "used": parts[2],
                            "available": parts[3],
                            "used_percent": int(parts[4].rstrip('%')),
                            "mount_point": parts[5]
                        })
            return disk_data
        return []
    except:
        return []

def get_filesystems():
    try:
        # Get filesystem information from /proc/filesystems
        filesystems = []
        if os.path.exists('/host/proc/filesystems'):
            with open('/host/proc/filesystems', 'r') as f:
                for line in f:
                    if not line.startswith('#') and line.strip():
                        filesystems.append(line.strip())
        return filesystems
    except:
        return []

def get_partitions():
    try:
        # Get partition information from /proc/partitions
        partitions = []
        if os.path.exists('/host/proc/partitions'):
            with open('/host/proc/partitions', 'r') as f:
                lines = f.readlines()[2:]  # Skip header lines
                for line in lines:
                    if line.strip() and not line.startswith(' '):
                        parts = line.split()
                        if len(parts) >= 4:
                            partitions.append({
                                "major": parts[0],
                                "minor": parts[1],
                                "blocks": parts[2],
                                "name": parts[3]
                            })
        return partitions
    except:
        return []