from __future__ import annotations

import pytest

from research.data_intake_contract import DataSnapshot, ProvenanceStatus
from research.real_data_sources import DataResolution, default_real_data_sources
from trader_bot.asset_universe import AssetClass


def test_real_source_map_covers_current_research_domains() -> None:
    sources = default_real_data_sources()
    assert any(source.supports(AssetClass.FOREX, DataResolution.MINUTE) for source in sources)
    assert any(source.supports(AssetClass.CRYPTO, DataResolution.MINUTE) for source in sources)
    assert any(source.supports(AssetClass.METAL, DataResolution.MINUTE) for source in sources)
    assert any(source.supports(AssetClass.EQUITY, DataResolution.DAILY) for source in sources)
    assert any(source.supports(AssetClass.INDEX, DataResolution.DAILY) for source in sources)


def test_synthetic_snapshot_cannot_enter_empirical_research() -> None:
    snapshot = DataSnapshot(
        snapshot_id="snapshot-1",
        source_id="TEST",
        asset_class=AssetClass.CRYPTO,
        symbol="BTC/USD",
        resolution="MINUTE",
        start_timestamp=1,
        end_timestamp=2,
        row_count=2,
        content_sha256="0" * 64,
        provenance=ProvenanceStatus.SYNTHETIC,
        fields=frozenset({"timestamp", "open", "high", "low", "close", "volume"}),
    )
    with pytest.raises(ValueError, match="VERIFIED_REAL"):
        snapshot.validate()


def test_snapshot_requires_valid_hash_and_chronology() -> None:
    snapshot = DataSnapshot(
        snapshot_id="snapshot-2",
        source_id="TEST",
        asset_class=AssetClass.FOREX,
        symbol="EUR/USD",
        resolution="MINUTE",
        start_timestamp=2,
        end_timestamp=1,
        row_count=1,
        content_sha256="not-a-hash",
        provenance=ProvenanceStatus.VERIFIED_REAL,
        fields=frozenset({"timestamp"}),
    )
    with pytest.raises(ValueError, match="chronological"):
        snapshot.validate()
