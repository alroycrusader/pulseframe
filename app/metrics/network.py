import os

_TCP_STATES = {
    '01': 'ESTABLISHED', '02': 'SYN_SENT', '03': 'SYN_RECV',
    '04': 'FIN_WAIT1',   '05': 'FIN_WAIT2', '06': 'TIME_WAIT',
    '07': 'CLOSE',        '08': 'CLOSE_WAIT', '09': 'LAST_ACK',
    '0A': 'LISTEN',       '0B': 'CLOSING',
}

def _hex_to_ipv4_addr(hex_addr: str) -> str:
    addr, port = hex_addr.split(':')
    ip = '.'.join(str(int(addr[i:i+2], 16)) for i in (6, 4, 2, 0))
    return f"{ip}:{int(port, 16)}"

def get_network_data():
    try:
        # Get network interfaces
        interfaces = get_network_interfaces()

        # Get network statistics
        stats = get_network_stats()

        # Get top network processes
        top_processes = get_top_network_processes()

        return {
            "interfaces": interfaces,
            "stats": stats,
            "top_processes": top_processes
        }
    except Exception as e:
        return {"error": str(e)}

def get_network_interfaces():
    try:
        interfaces = []
        with open('/host/proc/1/net/dev', 'r') as f:
            lines = f.readlines()[2:]  # Skip header lines

            for line in lines:
                if ':' in line:
                    parts = line.split(':')
                    interface = parts[0].strip()
                    stats = parts[1].strip().split()

                    if len(stats) >= 10:
                        interfaces.append({
                            "interface": interface,
                            "rx_bytes": int(stats[0]),
                            "rx_packets": int(stats[1]),
                            "rx_errors": int(stats[2]),
                            "rx_dropped": int(stats[3]),
                            "tx_bytes": int(stats[8]),
                            "tx_packets": int(stats[9]),
                            "tx_errors": int(stats[10]),
                            "tx_dropped": int(stats[11])
                        })
        return interfaces
    except:
        return []

def get_network_stats():
    try:
        # Get network statistics from /proc/net/snmp
        stats = {}
        if os.path.exists('/host/proc/1/net/snmp'):
            with open('/host/proc/1/net/snmp', 'r') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            stats[parts[0]] = parts[1:]

        # Get network connections
        connections = get_network_connections()

        return {
            "snmp_stats": stats,
            "connections": connections
        }
    except:
        return {"snmp_stats": {}, "connections": []}

def get_network_connections():
    connections = []
    for proto, path in [('tcp', '/host/proc/1/net/tcp'), ('tcp6', '/host/proc/1/net/tcp6')]:
        try:
            with open(path, 'r') as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    state_hex = parts[3].upper()
                    state = _TCP_STATES.get(state_hex, state_hex)
                    try:
                        local_addr = _hex_to_ipv4_addr(parts[1])
                    except Exception:
                        local_addr = parts[1]
                    connections.append({
                        "protocol": proto,
                        "local_address": local_addr,
                        "state": state,
                    })
        except (FileNotFoundError, PermissionError):
            continue
    return connections

def get_top_network_processes():
    listening = []
    for proto, path in [('tcp', '/host/proc/1/net/tcp'), ('tcp6', '/host/proc/1/net/tcp6')]:
        try:
            with open(path, 'r') as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    if parts[3].upper() != '0A':
                        continue
                    try:
                        local_addr = _hex_to_ipv4_addr(parts[1])
                    except Exception:
                        local_addr = parts[1]
                    listening.append({
                        "protocol": proto,
                        "local_address": local_addr,
                        "state": "LISTEN",
                    })
        except (FileNotFoundError, PermissionError):
            continue
    return listening
