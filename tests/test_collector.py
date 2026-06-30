from unittest.mock import patch

from app import collector


def test_get_health_reports_ok_after_successful_collect():
    with patch.object(collector, "_do_collect", return_value={"overview": {}}), \
         patch("app.storage.write_snapshot"):
        collector._collect_and_store()

    health = collector.get_health()
    assert health["ok"] is True
    assert health["interval_sec"] == collector.COLLECTION_INTERVAL
    assert health["last_collected_at"] is not None
    assert health["age_sec"] is not None
    assert health["age_sec"] >= 0


def test_get_health_reports_not_ok_after_failed_collect():
    # Seed a known-good collection first so we can confirm a later failure
    # flips `ok` without wiping the last good timestamp.
    with patch.object(collector, "_do_collect", return_value={"overview": {}}), \
         patch("app.storage.write_snapshot"):
        collector._collect_and_store()
    good_ts = collector.get_health()["last_collected_at"]

    with patch.object(collector, "_do_collect", side_effect=RuntimeError("boom")):
        collector._collect_and_store()

    health = collector.get_health()
    assert health["ok"] is False
    assert health["last_collected_at"] == good_ts


def test_get_cache_returns_a_copy():
    cache = collector.get_cache()
    cache["mutated"] = True
    assert "mutated" not in collector.get_cache()
