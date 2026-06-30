from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

import app.settings_store as settings_store
import app.alerts as alerts
from app import collector, storage


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    collector.start()
    alerts.start_alert_loop()
    yield

app = FastAPI(title="PulseFrame", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def read_root():
    # Return the main HTML page
    with open("app/static/index.html", "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.get("/api/overview")
async def read_overview():
    try:
        return collector.get_cache().get("overview", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cpu")
async def read_cpu():
    try:
        return collector.get_cache().get("cpu", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ram")
async def read_ram():
    try:
        return collector.get_cache().get("ram", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/gpu")
async def read_gpu():
    try:
        return collector.get_cache().get("gpu", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/storage")
async def read_storage():
    try:
        return collector.get_cache().get("storage", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/network")
async def read_network():
    try:
        return collector.get_cache().get("network", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/processes")
async def read_processes():
    try:
        return collector.get_cache().get("processes", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sensors")
async def read_sensors():
    try:
        return collector.get_cache().get("sensors", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system")
async def read_system():
    try:
        return collector.get_cache().get("system", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/all")
async def read_all():
    try:
        return collector.get_cache()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from app import storage as _storage


@app.get("/api/history/metrics")
async def history_metrics(hours: float = 6.0, bucket_sec: int = None):
    try:
        return _storage.query_metrics(hours, bucket_sec)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/disk")
async def history_disk(hours: float = 6.0, mount: str = None, bucket_sec: int = None):
    try:
        return _storage.query_disk(hours, mount, bucket_sec)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/processes")
async def history_processes(hours: float = 6.0):
    try:
        return _storage.query_processes(hours)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/processes/at")
async def history_processes_at(timestamp: float, window_sec: float = 30):
    try:
        procs = _storage.query_processes_at(timestamp, window_sec)
        tracking_start = _storage.query_process_tracking_start()
        return {"processes": procs, "tracking_start": tracking_start}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/summary")
async def history_summary(hours: float = 24.0, bucket_sec: int = None):
    """Peaks/averages/percentiles for CPU, RAM, swap, load, temps, GPU,
    network throughput, and process count over the given window."""
    try:
        return _storage.query_metrics_stats(hours, bucket_sec)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/disk/trend")
async def history_disk_trend(hours: float = 168.0, mount: str = None):
    """Per-mount capacity trend (growth rate, projected days-to-full)."""
    try:
        return _storage.query_disk_trend(hours, mount)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/retention")
async def get_retention_ep():
    return {
        "retention_days": _storage.get_retention_days(),
        "min_days": _storage.MIN_RETENTION_DAYS,
        "max_days": _storage.MAX_RETENTION_DAYS,
    }


@app.post("/api/history/retention")
async def set_retention_ep(data: dict = Body(...)):
    try:
        days = int(data.get("days"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="days must be an integer")
    try:
        applied = _storage.set_retention_days(days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"retention_days": applied}


# ── Settings: Webhooks ──────────────────────────────────────────────────────

@app.get("/api/settings/webhooks")
async def list_webhooks():
    return settings_store.get_webhooks()


@app.post("/api/settings/webhooks")
async def create_webhook(data: dict = Body(...)):
    name = str(data.get("name", "")).strip()
    url = str(data.get("url", "")).strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="name and url required")
    return settings_store.add_webhook(name, url)


@app.put("/api/settings/webhooks/{hook_id}")
async def update_webhook_ep(hook_id: str, data: dict = Body(...)):
    name = str(data.get("name", "")).strip()
    url = str(data.get("url", "")).strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="name and url required")
    result = settings_store.update_webhook(hook_id, name, url)
    if not result:
        raise HTTPException(status_code=404, detail="not found")
    return result


@app.delete("/api/settings/webhooks/{hook_id}")
async def delete_webhook_ep(hook_id: str):
    settings_store.delete_webhook(hook_id)
    return {"ok": True}


@app.post("/api/settings/webhooks/test-url")
async def test_webhook_url_ep(data: dict = Body(...)):
    url = str(data.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    ok = alerts.test_webhook(url)
    return {"ok": ok}


@app.post("/api/settings/webhooks/{hook_id}/test")
async def test_webhook_ep(hook_id: str):
    hooks = settings_store.get_webhooks()
    hook = next((h for h in hooks if h["id"] == hook_id), None)
    if not hook:
        raise HTTPException(status_code=404, detail="not found")
    ok = alerts.test_webhook(hook["url"])
    return {"ok": ok}


# ── Settings: Thresholds ────────────────────────────────────────────────────

@app.get("/api/settings/thresholds")
async def get_thresholds_ep():
    return settings_store.get_thresholds()


@app.post("/api/settings/thresholds")
async def set_thresholds_ep(data: dict = Body(...)):
    return settings_store.set_thresholds(data)


# ── Settings: Messages ──────────────────────────────────────────────────────

@app.get("/api/settings/messages")
async def get_messages_ep():
    return settings_store.get_messages()


@app.post("/api/settings/messages")
async def set_messages_ep(data: dict = Body(...)):
    return settings_store.set_messages(data)


# ── Settings: Enabled ───────────────────────────────────────────────────────

@app.get("/api/settings/enabled")
async def get_enabled_ep():
    return settings_store.get_enabled()


@app.post("/api/settings/enabled")
async def set_enabled_ep(data: dict = Body(...)):
    return settings_store.set_enabled(data)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)