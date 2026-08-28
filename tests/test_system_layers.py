from research.domain_intelligence_profiles import ExpertFamily, domain_intelligence
from research.system_layers import LayerKind, architecture_ready, required_layer_names


def test_architecture_catalog_contains_every_required_operating_layer() -> None:
    names = set(required_layer_names())
    assert LayerKind.DATA in names
    assert LayerKind.DOMAIN_CONTEXT in names
    assert LayerKind.BEHAVIORAL_MEMORY in names
    assert LayerKind.EXPERT_ENSEMBLE in names
    assert LayerKind.PROBABILITY in names
    assert LayerKind.COST in names
    assert LayerKind.LIQUIDITY in names
    assert LayerKind.RISK in names
    assert LayerKind.PORTFOLIO in names
    assert LayerKind.OPPORTUNITY in names
    assert LayerKind.HEALTH in names
    assert LayerKind.AUDIT in names
    assert LayerKind.EXECUTION_BOUNDARY in names
    assert LayerKind.VALIDATION not in names


def test_architecture_cannot_claim_ready_with_missing_operational_layer() -> None:
    implemented = set(required_layer_names()) - {LayerKind.PORTFOLIO}
    assert architecture_ready(implemented_layers=implemented, live_execution_enabled=False) is False


def test_architecture_is_ready_only_when_non_validation_layers_exist_and_live_is_off() -> None:
    implemented = set(required_layer_names()) - {LayerKind.VALIDATION}
    assert architecture_ready(implemented_layers=implemented, live_execution_enabled=False) is True
    assert architecture_ready(implemented_layers=implemented, live_execution_enabled=True) is False


def test_all_shared_expert_families_exist_for_each_supported_domain() -> None:
    for asset_class in ("FOREX", "CRYPTO", "METAL", "EQUITY"):
        profile = domain_intelligence(asset_class)
        assert set(profile.expert_features) == set(ExpertFamily)


def test_domain_priority_features_differ_by_market() -> None:
    forex = domain_intelligence("FOREX").priority_features
    crypto = domain_intelligence("CRYPTO").priority_features
    equity = domain_intelligence("EQUITY").priority_features
    assert forex != crypto
    assert crypto != equity
    assert "funding" in {feature.value for feature in crypto}
    assert "calendar" in {feature.value for feature in equity}
