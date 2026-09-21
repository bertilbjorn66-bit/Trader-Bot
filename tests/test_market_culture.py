from research.market_culture import EvidenceDimension, default_market_cultures
from trader_bot.asset_universe import AssetClass


def test_every_asset_class_has_a_distinct_native_culture() -> None:
    cultures = default_market_cultures()
    assert set(cultures) == set(AssetClass)
    for culture in cultures.values():
        assert culture.isolation_required is True
        assert culture.primary_dimensions
        assert culture.trade_evolution_dimensions
        assert culture.invalidation_dimensions


def test_crypto_culture_is_volume_funding_and_venue_aware() -> None:
    culture = default_market_cultures()[AssetClass.CRYPTO]
    assert EvidenceDimension.VOLUME in culture.primary_dimensions
    assert EvidenceDimension.FUNDING in culture.primary_dimensions
    assert EvidenceDimension.VENUE in culture.primary_dimensions
    assert not culture.allows_external_context(AssetClass.METAL)


def test_equity_culture_is_calendar_gap_and_event_aware() -> None:
    culture = default_market_cultures()[AssetClass.EQUITY]
    assert EvidenceDimension.CALENDAR in culture.primary_dimensions
    assert EvidenceDimension.GAPS in culture.primary_dimensions
    assert EvidenceDimension.EVENTS in culture.primary_dimensions


def test_cross_market_context_is_explicit_not_implicit() -> None:
    cultures = default_market_cultures()
    assert cultures[AssetClass.FOREX].allows_external_context(AssetClass.METAL)
    assert cultures[AssetClass.FOREX].allows_external_context(AssetClass.INDEX)
    assert not cultures[AssetClass.FOREX].allows_external_context(AssetClass.CRYPTO)
    assert cultures[AssetClass.COMMODITY].allows_external_context(AssetClass.METAL)
