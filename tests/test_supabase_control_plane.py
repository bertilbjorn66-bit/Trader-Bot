from datetime import datetime, timezone

import httpx
import pytest

from trader_bot.supabase_control_plane import SupabaseControlPlane, SupabaseControlPlaneConfig


def test_config_requires_https_and_key() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        SupabaseControlPlaneConfig("http://example.invalid", "key")
    with pytest.raises(ValueError, match="service key"):
        SupabaseControlPlaneConfig("https://example.invalid", " ")


def test_health_reads_only_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"series_id": "s1", "state": "FRESH"}])

    config = SupabaseControlPlaneConfig("https://example.invalid", "server-key")
    with SupabaseControlPlane(config) as plane:
        plane._client.close()
        plane._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.invalid/rest/v1")
        result = plane.health("s1")

    assert result == {"series_id": "s1", "state": "FRESH"}
    assert requests[0].url.path == "/rest/v1/market_series_health"
    assert requests[0].url.params["select"] == "*"
    assert "timestamp" not in requests[0].url.query.decode().lower()


def test_health_upsert_sends_control_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201)

    config = SupabaseControlPlaneConfig("https://example.invalid", "server-key")
    with SupabaseControlPlane(config) as plane:
        plane._client.close()
        plane._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.invalid/rest/v1")
        plane.upsert_health(
            series_id="s1",
            state="FRESH",
            latest_observed_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            latest_data_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            row_count=10,
            quality_pass=True,
            contiguous=True,
            source_hash="abc",
            provider_status="ACTIVE",
            reason=None,
        )

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/rest/v1/market_series_health"
    assert requests[0].json()["row_count"] == 10
    assert "open" not in str(requests[0].json()).lower()


def test_start_refresh_requires_returned_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=[{"unexpected": True}])

    config = SupabaseControlPlaneConfig("https://example.invalid", "server-key")
    with SupabaseControlPlane(config) as plane:
        plane._client.close()
        plane._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.invalid/rest/v1")
        with pytest.raises(RuntimeError, match="refresh run id"):
            plane.start_refresh(
                series_id="s1",
                requested_from=datetime(2026, 8, 29, tzinfo=timezone.utc),
                requested_to=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
