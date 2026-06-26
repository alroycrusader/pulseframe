# LEGACY: This Flask-based server is no longer used.
# The active server is app/main.py (FastAPI).
# Kept for reference only.
from flask import Flask, jsonify
from flask_cors import CORS
import time
import threading
from metrics.overview import get_overview_data
from metrics.cpu import get_cpu_data
from metrics.ram import get_ram_data
from metrics.gpu import get_gpu_data
from metrics.storage import get_storage_data
from metrics.network import get_network_data
from metrics.processes import get_processes_data
from metrics.sensors import get_sensors_data
from metrics.system import get_system_data

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Cache data to avoid excessive system calls
cache_data = {}
cache_timestamp = 0
cache_duration = 5  # seconds

def get_cached_data():
    global cache_data, cache_timestamp

    current_time = time.time()
    if current_time - cache_timestamp > cache_duration:
        # Refresh cache
        cache_data = {
            "overview": get_overview_data(),
            "cpu": get_cpu_data(),
            "ram": get_ram_data(),
            "gpu": get_gpu_data(),
            "storage": get_storage_data(),
            "network": get_network_data(),
            "processes": get_processes_data(),
            "sensors": get_sensors_data(),
            "system": get_system_data()
        }
        cache_timestamp = current_time

    return cache_data

@app.route('/')
def index():
    return jsonify({"message": "Activity Monitor API is running"})

@app.route('/api/overview')
def overview():
    data = get_cached_data()
    return jsonify(data["overview"])

@app.route('/api/cpu')
def cpu():
    data = get_cached_data()
    return jsonify(data["cpu"])

@app.route('/api/ram')
def ram():
    data = get_cached_data()
    return jsonify(data["ram"])

@app.route('/api/gpu')
def gpu():
    data = get_cached_data()
    return jsonify(data["gpu"])

@app.route('/api/storage')
def storage():
    data = get_cached_data()
    return jsonify(data["storage"])

@app.route('/api/network')
def network():
    data = get_cached_data()
    return jsonify(data["network"])

@app.route('/api/processes')
def processes():
    data = get_cached_data()
    return jsonify(data["processes"])

@app.route('/api/sensors')
def sensors():
    data = get_cached_data()
    return jsonify(data["sensors"])

@app.route('/api/system')
def system():
    data = get_cached_data()
    return jsonify(data["system"])

@app.route('/api/all')
def all_metrics():
    data = get_cached_data()
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)