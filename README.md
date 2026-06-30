# PulseFrame

A self-hosted, Docker-deployable Linux server monitoring dashboard with real-time metrics, alert webhooks, and persistent history — designed to run permanently on a server without measurably impacting its workload.

**License:** Source-available · Free for personal and internal business use · [Paid license required](#license) for redistribution, resale, SaaS, or embedding

By [vimsoft.org](https://vimsoft.org)

---

## What it does

PulseFrame gives you a live view of everything happening on your Linux server through a dark-themed web dashboard. It collects metrics every 10 seconds via a background collector, serves all data from an in-memory cache (so API requests are near-instant), and persists 30 days of history to a local SQLite database.

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
git clone <repo-url> pulseframe
cd pulseframe
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
| `CONTAINER_NAME` | `pulseframe` | Docker container name |

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

PulseFrame is **source-available** — it is not "free software" or "open source" in the FSF/OSI sense, because redistribution, resale, SaaS, and embedding are restricted (see below).

**You may use PulseFrame for free for:**

- personal use, home servers, and hobby projects
- research and education
- non-commercial organisations (charities, educational institutions, public research bodies, government institutions)
- **internal business use** — running PulseFrame within your own company or organisation to monitor and operate infrastructure that you own, lease, or control

Internal business use does **not** include making PulseFrame, or a service built on it, available to your customers, clients, tenants, or any other third party.

**A paid commercial license is required to:**

- redistribute PulseFrame
- resell PulseFrame
- sublicense PulseFrame
- offer PulseFrame as a hosted, managed, or SaaS service
- embed PulseFrame into a commercial product or service
- provide PulseFrame to third parties as part of a paid product, service, appliance, bundle, or platform

Commercial licenses are granted only under a separate written agreement with Vimsoft, and grant only the rights expressly stated in that agreement. See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) for details, or contact **customer.service@vimsoft.org**.

See [LICENSE](LICENSE) for the full terms.

> This licensing model is custom to this project and has not yet received review by a qualified software/IP lawyer. Treat it as a statement of intent, not legal advice.

---

[vimsoft.org](https://vimsoft.org)
