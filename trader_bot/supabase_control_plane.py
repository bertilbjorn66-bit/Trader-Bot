from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(frozen=True, slots=True)
class SupabaseControlPlaneConfig:
    url: str
    service_key: str

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ValueError("Supabase URL must use HTTPS")
        if not self.service_key.strip():
            raise ValueError("Supabase service key is required")


class SupabaseControlPlane:
    """Server-side control-plane client; raw market data never passes through it."""

    def __init__(self, config: SupabaseControlPlaneConfig, *, timeout: float = 10.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        base = config.url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{base}/rest/v1",
            timeout=timeout,
            headers={
                "apikey": config.service_key,
                "Authorization": f"Bearer {config.service_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SupabaseControlPlane":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def health(self, series_id: str) -> dict[str, Any] | None:
        response = self._client.get(
            "/market_series_health",
            params={"select": "*", "series_id": f"eq.{quote(series_id, safe='')}"},
        )
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def upsert_health(
        self,
        *,
        series_id: str,
        state: str,
        latest_observed_at: datetime | None,
        latest_data_at: datetime | None,
        row_count: int,
        quality_pass: bool,
        contiguous: bool,
        source_hash: str | None,
        provider_status: str | None,
        reason: str | None,
    ) -> None:
        payload = {
            "series_id": series_id,
            "state": state,
            "latest_observed_at": latest_observed_at.isoformat() if latest_observed_at else None,
            "latest_data_at": latest_data_at.isoformat() if latest_data_at else None,
            "row_count": row_count,
            "quality_pass": quality_pass,
            "contiguous": contiguous,
            "source_hash": source_hash,
            "provider_status": provider_status,
            "reason": reason,
        }
        response = self._client.post(
            "/market_series_health",
            params={"on_conflict": "series_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
        )
        response.raise_for_status()

    def start_refresh(
        self,
        *,
        series_id: str,
        requested_from: datetime,
        requested_to: datetime,
    ) -> str:
        response = self._client.post(
            "/market_refresh_runs",
            headers={"Prefer": "return=representation"},
            json={
                "series_id": series_id,
                "requested_from": requested_from.isoformat(),
                "requested_to": requested_to.isoformat(),
                "status": "RUNNING",
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError("Supabase did not return a refresh run id")
        refresh_id = rows[0].get("id")
        if not isinstance(refresh_id, str) or not refresh_id:
            raise RuntimeError("Supabase did not return a valid refresh run id")
        return refresh_id

    def finish_refresh(
        self,
        *,
        run_id: str,
        status: str,
        received_rows: int,
        stored_rows: int,
        failure_reason: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now().astimezone().isoformat(),
            "received_rows": received_rows,
            "stored_rows": stored_rows,
            "failure_reason": failure_reason,
        }
        response = self._client.patch(
            "/market_refresh_runs",
            params={"id": f"eq.{quote(run_id, safe='')}"},
            headers={"Prefer": "return=minimal"},
            json=payload,
        )
        response.raise_for_status()
