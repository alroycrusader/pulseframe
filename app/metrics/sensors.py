import subprocess
import os
import glob

def get_sensors_data():
    try:
        # Get temperature sensors
        temperatures = get_temperature_sensors()

        # Get fan speeds
        fans = get_fan_speeds()

        # Get power supplies
        power_supplies = get_power_supplies()

        # Get other sensor data
        other_sensors = get_other_sensors()

        return {
            "temperatures": temperatures,
            "fans": fans,
            "power_supplies": power_supplies,
            "other_sensors": other_sensors
        }
    except Exception as e:
        return {"error": str(e)}

def get_temperature_sensors():
    try:
        temperatures = []

        # Try lm-sensors first
        try:
            result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_sensor = None
                for line in lines:
                    if ':' in line and not line.startswith(' '):
                        # This is a sensor name
                        current_sensor = line.strip()
                    elif current_sensor and line.strip() and not line.startswith(' '):
                        # This is a temperature reading
                        if '°C' in line:
                            temp = line.split()[0].rstrip('°C')
                            temperatures.append({
                                "sensor": current_sensor,
                                "temperature": temp
                            })
        except:
            pass

        # Fallback to reading from /sys/class/hwmon
        if not temperatures:
            hwmon_path = '/host/sys/class/hwmon'
            if os.path.exists(hwmon_path):
                for hwmon in os.listdir(hwmon_path):
                    temp_file = os.path.join(hwmon_path, hwmon, 'temp1_input')
                    if os.path.exists(temp_file):
                        try:
                            with open(temp_file, 'r') as f:
                                temp = int(f.read().strip()) / 1000.0
                                temperatures.append({
                                    "sensor": hwmon,
                                    "temperature": temp
                                })
                        except:
                            pass

        return temperatures
    except:
        return []

def get_fan_speeds():
    try:
        fans = []

        # Try reading from /sys/class/hwmon
        hwmon_path = '/host/sys/class/hwmon'
        if os.path.exists(hwmon_path):
            for hwmon in os.listdir(hwmon_path):
                fan_file = os.path.join(hwmon_path, hwmon, 'fan1_input')
                if os.path.exists(fan_file):
                    try:
                        with open(fan_file, 'r') as f:
                            fan_speed = int(f.read().strip())
                            fans.append({
                                "fan": hwmon,
                                "speed": fan_speed
                            })
                    except:
                        pass

        return fans
    except:
        return []

def get_power_supplies():
    try:
        power_supplies = []

        # Try reading from /sys/class/power_supply
        power_path = '/host/sys/class/power_supply'
        if os.path.exists(power_path):
            for power_supply in os.listdir(power_path):
                power_file = os.path.join(power_path, power_supply, 'capacity')
                if os.path.exists(power_file):
                    try:
                        with open(power_file, 'r') as f:
                            capacity = int(f.read().strip())
                            power_supplies.append({
                                "supply": power_supply,
                                "capacity": capacity
                            })
                    except:
                        pass

        return power_supplies
    except:
        return []

def get_other_sensors():
    try:
        other_sensors = []

        # Try reading from various sensor paths
        sensor_paths = [
            '/host/sys/class/hwmon',
            '/host/sys/class/thermal',
            '/host/proc/pressure',
            '/host/proc/temperature'
        ]

        for path in sensor_paths:
            if os.path.exists(path):
                if 'hwmon' in path:
                    for hwmon in os.listdir(path):
                        # Look for various sensor files
                        for sensor_file in ['in1_input', 'curr1_input']:
                            file_path = os.path.join(path, hwmon, sensor_file)
                            if os.path.exists(file_path):
                                try:
                                    with open(file_path, 'r') as f:
                                        value = f.read().strip()
                                        other_sensors.append({
                                            "path": file_path,
                                            "value": value
                                        })
                                except:
                                    pass
                elif 'thermal' in path:
                    for thermal_zone in os.listdir(path):
                        temp_file = os.path.join(path, thermal_zone, 'temp')
                        if os.path.exists(temp_file):
                            try:
                                with open(temp_file, 'r') as f:
                                    temp = int(f.read().strip()) / 1000.0
                                    other_sensors.append({
                                        "path": temp_file,
                                        "value": temp
                                    })
                            except:
                                pass

        return other_sensors
    except:
        return []