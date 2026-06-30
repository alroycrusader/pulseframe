"""HTTP-level tests for the new /api/history/* endpoints added in app/main.py:
retention (GET/POST), summary, and disk/trend. Complements test_storage.py,
which exercises the underlying storage functions directly.
"""
import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "metrics_test.db"))

    from app.main import app
    with TestClient(app) as c:
        yield c


def test_get_retention_returns_default_and_bounds(client):
    resp = client.get("/api/history/retention")
    assert resp.status_code == 200
    body = resp.json()
    assert body["retention_days"] == 30
    assert body["min_days"] == 1
    assert body["max_days"] == 365


def test_post_retention_updates_value(client):
    resp = client.post("/api/history/retention", json={"days": 10})
    assert resp.status_code == 200
    assert resp.json() == {"retention_days": 10}

    resp = client.get("/api/history/retention")
    assert resp.json()["retention_days"] == 10


def test_post_retention_clamps_out_of_range(client):
    resp = client.post("/api/history/retention", json={"days": 9999})
    assert resp.status_code == 200
    assert resp.json() == {"retention_days": 365}


def test_post_retention_rejects_non_integer(client):
    resp = client.post("/api/history/retention", json={"days": "not-a-number"})
    assert resp.status_code == 400


def test_post_retention_requires_days_field(client):
    resp = client.post("/api/history/retention", json={})
    assert resp.status_code == 400


def test_history_summary_has_expected_shape(client):
    # The TestClient lifespan starts the real background collector against
    # the patched temp DB, so a snapshot may or may not have landed yet by
    # the time this fires — assert shape, not row count.
    resp = client.get("/api/history/summary?hours=24")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_history_disk_trend_returns_list(client):
    resp = client.get("/api/history/disk/trend?hours=168")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    for entry in body:
        assert entry.keys() >= {
            "mount_point", "current_used_percent", "samples",
            "window_hours", "growth_pct_per_day",
        }


def test_history_disk_trend_filters_by_mount(client):
    resp = client.get("/api/history/disk/trend?hours=168&mount=/")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert all(entry["mount_point"] == "/" for entry in body)
