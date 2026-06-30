from fastapi.testclient import TestClient

from app.main import app


def test_health_services_endpoint_reports_known_services():
    with TestClient(app) as client:
        resp = client.get("/api/health/services")
        assert resp.status_code == 200
        body = resp.json()
        names = {s["name"] for s in body["services"]}
        assert names == {"Metrics Collector", "History Storage", "Alerting"}
        for s in body["services"]:
            assert s["status"] in ("ok", "warn", "down")
            assert isinstance(s["detail"], str) and s["detail"]


def test_thresholds_endpoint_is_read_only_and_has_known_keys():
    # The dashboard reads this endpoint to render threshold bands — assert
    # the shape it depends on without writing anything (set_thresholds is
    # owned by the parallel alerting work and is out of scope here).
    with TestClient(app) as client:
        resp = client.get("/api/settings/thresholds")
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "cpu_warn", "cpu_crit",
            "ram_warn", "ram_crit",
            "storage_warn", "storage_crit",
            "gpu_util_warn", "gpu_util_crit",
            "net_rx_warn_mbps", "net_rx_crit_mbps",
            "net_tx_warn_mbps", "net_tx_crit_mbps",
        ):
            assert key in data


def test_all_endpoint_still_returns_every_tab_slice():
    with TestClient(app) as client:
        resp = client.get("/api/all")
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "overview", "cpu", "ram", "gpu", "storage",
            "network", "processes", "sensors", "system",
        ):
            assert key in body


def test_health_check_endpoint_unchanged():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}
