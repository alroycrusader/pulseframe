# Installation Guide

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Install](#quick-install)
- [Manual Install](#manual-install)
- [Configuration](#configuration)
- [Accessing the Dashboard](#accessing-the-dashboard)
- [No NVIDIA GPU?](#no-nvidia-gpu)
- [Managing the Container](#managing-the-container)
- [Persistent Data](#persistent-data)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Linux host (Ubuntu 20.04+) | Raspberry Pi, Debian, etc. also work |
| Docker Engine 20.10+ | [Install guide](https://docs.docker.com/engine/install/ubuntu/) |
| Docker Compose V2 | Ships with Docker Desktop and modern Engine installs — verify with `docker compose version` |
| NVIDIA GPU (optional) | Requires NVIDIA drivers and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) — see [No NVIDIA GPU?](#no-nvidia-gpu) if not applicable |

---

## Quick Install

For most users this is all you need:

```bash
git clone <repo-url> activity-monitor
cd activity-monitor
./install.sh
```

The script handles everything automatically:

1. Checks Docker and Compose are present
2. Creates the `data/` directory for persistent storage
3. Generates `.env` from `.env.example` — auto-detects your Tailscale IP if available, otherwise defaults to `127.0.0.1`
4. Builds the Docker image and starts the container
5. Polls `/health` and prints the dashboard URL when ready

---

## Manual Install

If you prefer to configure things yourself:

### 1. Clone the repository

```bash
git clone <repo-url> activity-monitor
cd activity-monitor
```

### 2. Create the data directory

```bash
mkdir -p data
```

This directory holds your settings (`settings.json`) and the metrics history database (`metrics.db`). It is mounted into the container and survives rebuilds.

### 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set your preferred values (see [Configuration](#configuration) below).

### 4. Build and start

```bash
docker compose up -d --build
```

### 5. Verify

```bash
curl http://127.0.0.1:8081/health
# → {"status":"healthy"}
```

---

## Configuration

All runtime options live in `.env` (gitignored — safe to store your IP there).

| Variable | Default | Description |
|---|---|---|
| `BIND_HOST` | `127.0.0.1` | IP address the dashboard binds to on the host. See [Accessing the Dashboard](#accessing-the-dashboard) for options. |
| `BIND_PORT` | `8081` | Host port. The container always listens on 8080 internally. |
| `CONTAINER_NAME` | `activity-monitor` | Docker container name. Change this if you run multiple instances. |

Example `.env` for a Tailscale setup:

```env
BIND_HOST=100.x.x.x
BIND_PORT=8081
CONTAINER_NAME=activity-monitor
```

---

## Accessing the Dashboard

### Option A — SSH port forwarding (most secure, no network exposure)

Leave `BIND_HOST=127.0.0.1`, then forward the port over SSH from your local machine:

```bash
ssh -L 8081:127.0.0.1:8081 user@your-server
```

Open `http://localhost:8081` in your browser.

### Option B — Tailscale (recommended for remote access)

Set `BIND_HOST` to your server's Tailscale IP (e.g. `100.x.x.x`). The dashboard is then accessible from any device on your Tailscale network at `http://100.x.x.x:8081`. No public port exposure needed.

The `install.sh` script auto-detects and sets this for you if Tailscale is running.

### Option C — LAN / all interfaces

Set `BIND_HOST=0.0.0.0` to bind on all interfaces. Anyone on the same network can reach the dashboard. Only use this on a trusted private network — there is no authentication.

---

## No NVIDIA GPU?

No action needed. `install.sh` detects whether the NVIDIA Container Runtime is registered with Docker and automatically comments out the GPU lines in `docker-compose.yml` if it is not found. The GPU tab will show "NVIDIA GPU not detected" gracefully, and everything else works normally.

If you add an NVIDIA GPU later, install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) and re-run `./install.sh` — it will uncomment the lines and rebuild automatically.

---

## Managing the Container

```bash
# View live logs
docker compose logs -f

# Stop the container (data is preserved)
docker compose down

# Start again (no rebuild)
docker compose up -d

# Stop and remove everything including the image
docker compose down --rmi all
```

---

## Persistent Data

Everything that survives container rebuilds lives in `./data/`:

| File | Contents |
|---|---|
| `data/settings.json` | Webhook URLs, alert thresholds, enabled flags, custom messages |
| `data/metrics.db` | SQLite database — rolling 30 days of metric snapshots |

Both are mounted as a Docker volume (`./data:/app/data`). Back up this directory to preserve your configuration and history.

The metrics database is queried via the history API:

```bash
# Last 6 hours of CPU, RAM, load, network, temp
curl "http://127.0.0.1:8081/api/history/metrics?hours=6"

# Last 24 hours of disk usage (optionally filter by mount point)
curl "http://127.0.0.1:8081/api/history/disk?hours=24"
curl "http://127.0.0.1:8081/api/history/disk?hours=24&mount=/"
```

Metrics are written every 10 seconds and pruned automatically after 30 days. At 10-second granularity, `metrics.db` grows at roughly **2–3 MB per day**.

---

## Updating

Pull the latest code and rebuild:

```bash
git pull
docker compose up -d --build
```

Your `data/` directory and `.env` are untouched — settings and history survive the update.

---

## Troubleshooting

### Container fails to start — `nvidia` runtime error

**Error:** `Error response from daemon: Unknown runtime specified nvidia`

This means you ran `docker compose up` directly instead of using `./install.sh`. The install script auto-detects whether the NVIDIA runtime is available and comments out those lines before starting. Run `./install.sh` instead, or manually comment out the `runtime: nvidia`, `environment:`, and `NVIDIA_*` lines in `docker-compose.yml`.

### Dashboard shows empty data on first load

The background collector runs an initial full metric sweep when the container starts. This takes 1–2 seconds. Refresh the page once if you see empty panels immediately after startup.

### Process owner names show as numbers (e.g. `1000`)

The `/etc/passwd` file is mounted read-only into the container for UID-to-username resolution. If you see numeric UIDs, verify the mount exists:

```bash
docker exec activity-monitor ls /host/etc/passwd
```

If missing, ensure your `docker-compose.yml` includes:

```yaml
- /etc/passwd:/host/etc/passwd:ro
```

Then restart: `docker compose up -d`.

### GPU tab shows "not detected"

1. Confirm `nvidia-smi` works on the host: `nvidia-smi`
2. Confirm the NVIDIA Container Toolkit is installed: `nvidia-ctk --version`
3. Ensure `runtime: nvidia` is present in `docker-compose.yml`
4. Restart Docker after toolkit installation: `sudo systemctl restart docker`

### Sensor data missing or all zeros

Some virtualized environments (VMs, WSL) do not expose hardware sensors. On bare-metal Linux, ensure the `lm-sensors` package is configured:

```bash
sudo apt install lm-sensors
sudo sensors-detect --auto
```

Sensors are read from `/sys/class/hwmon` — verify entries exist: `ls /sys/class/hwmon/`.

### Port already in use

Change `BIND_PORT` in `.env` and restart:

```bash
docker compose down
# edit .env
docker compose up -d
```

### Check what the API is returning

```bash
# Full snapshot of all current metrics
curl http://127.0.0.1:8081/api/all | python3 -m json.tool | less

# Individual sections
curl http://127.0.0.1:8081/api/cpu
curl http://127.0.0.1:8081/api/ram
curl http://127.0.0.1:8081/api/storage
curl http://127.0.0.1:8081/api/network
curl http://127.0.0.1:8081/api/processes
```
