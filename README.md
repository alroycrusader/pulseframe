# Activity Monitor

A self-hosted, Docker-deployable Linux server monitoring dashboard with real-time metrics, alert webhooks, and persistent history — designed to run permanently on a server without measurably impacting its workload.

**License:** Free for personal use · [Commercial license required](#license) for businesses

---

## What it does

Activity Monitor gives you a live view of everything happening on your Linux server through a dark-themed web dashboard. It collects metrics every 10 seconds via a background collector, serves all data from an in-memory cache (so API requests are near-instant), and persists 30 days of history to a local SQLite database.

### Dashboard tabs

| Tab | What you see |
|---|---|
| **Overview** | CPU %, RAM %, disk, load average, uptime, process count |
| **CPU** | Per-core usage, frequency, temperature, top CPU processes |
| **RAM** | Used / free / cached / buffered, swap usage, top memory processes |
| **GPU** | NVIDIA GPU utilisation, VRAM, temperature, per-GPU process list |
| **Storage** | Per-filesystem usage, partition table, I/O stats |
| **Network** | Per-interface RX/TX counters, active connections, listening ports |
| **Processes** | Full process list with CPU %, RAM %, I/O rates, owner, command |
| **Sensors** | Hardware temperatures, fan speeds, power supply state |
| **System Info** | Hostname, OS, kernel version, uptime |

### Alerting

Configure webhook URLs (Discord, Slack, or any HTTP endpoint) and set thresholds for CPU, RAM, swap, disk, GPU, network throughput, load average, and zombie processes. Alerts fire with configurable cooldown periods so you do not get flooded.

### History API

Query the last N hours of metrics programmatically:

```
GET /api/history/metrics?hours=6
GET /api/history/disk?hours=24&mount=/
```

---

## Requirements

- Linux host (Ubuntu 20.04+ recommended; Debian, Raspberry Pi OS also work)
- Docker Engine 20.10+ with Docker Compose V2
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) *(optional — GPU tab is gracefully disabled without it)*

---

## Installation

See **[INSTALL.md](INSTALL.md)** for the full guide including access options, configuration reference, update procedure, and troubleshooting.

**Quick start:**

```bash
git clone <repo-url> activity-monitor
cd activity-monitor
./install.sh
```

`install.sh` handles everything:
- Detects whether the NVIDIA Container Runtime is available and adjusts `docker-compose.yml` automatically
- Auto-detects your Tailscale IP and sets it as the bind address, or falls back to `127.0.0.1`
- Creates `data/` for persistent storage
- Builds and starts the container
- Polls `/health` and prints your dashboard URL when ready

---

## Architecture

```
Browser  ──▶  FastAPI (uvicorn)  ──▶  in-memory cache  ──▶  response (< 1 ms)
                                             ▲
                              Background collector (every 10 s)
                                             │
                              ┌──────────────┴──────────────┐
                              │  /proc  /sys  /etc  hwmon   │
                              └──────────────┬──────────────┘
                                             │
                                       SQLite (WAL)
                                    30-day rolling history
```

All metric collection happens in a single daemon thread. API endpoints read from the cache and never block on I/O or sleep calls. The alert loop also reads the same cache rather than performing its own collection.

---

## Configuration

All options are set in `.env` (created by `install.sh`, gitignored):

| Variable | Default | Description |
|---|---|---|
| `BIND_HOST` | `127.0.0.1` | Host IP to bind the dashboard on |
| `BIND_PORT` | `8081` | Host port |
| `CONTAINER_NAME` | `activity-monitor` | Docker container name |

---

## API reference

All endpoints return JSON. Data is served from the in-memory cache and reflects the most recent collection cycle (up to 10 seconds old).

| Endpoint | Description |
|---|---|
| `GET /health` | Health check — returns `{"status":"healthy"}` |
| `GET /api/all` | Full snapshot of all metrics |
| `GET /api/overview` | System summary |
| `GET /api/cpu` | CPU metrics and top processes |
| `GET /api/ram` | Memory and swap |
| `GET /api/gpu` | NVIDIA GPU data |
| `GET /api/storage` | Disk usage and partitions |
| `GET /api/network` | Network interfaces and connections |
| `GET /api/processes` | Full process list |
| `GET /api/sensors` | Temperatures and fans |
| `GET /api/system` | System info |
| `GET /api/history/metrics?hours=N` | Historical metric snapshots (default 6 h) |
| `GET /api/history/disk?hours=N&mount=X` | Historical disk usage, optional mount filter |

---

## Persistent data

Everything that survives container rebuilds lives in `./data/`:

| File | Contents |
|---|---|
| `data/settings.json` | Webhooks, alert thresholds, messages, enabled flags |
| `data/metrics.db` | SQLite metrics history (30-day rolling, ~2–3 MB/day) |

Back up this directory to preserve your configuration and history across server migrations.

---

## License

**Personal and non-commercial use is free.**

This project is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0). You may use, copy, modify, and self-host this software at no cost for:

- Personal home servers and hobby projects
- Research, education, and experimentation
- Charitable organisations, educational institutions, and government bodies

**Commercial use requires a paid license.**

If you are a company or using this software as part of a commercial operation, you must obtain a commercial license before use. Contact **alroycrusader@gmail.com** to discuss pricing.

See [LICENSE](LICENSE) for the full terms.
