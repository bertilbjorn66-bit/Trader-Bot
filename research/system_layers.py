from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class LayerKind(StrEnum):
    DATA = "DATA"
    DATA_FRESHNESS = "DATA_FRESHNESS"
    INTEGRITY = "INTEGRITY"
    DOMAIN_CONTEXT = "DOMAIN_CONTEXT"
    REGIME = "REGIME"
    BEHAVIORAL_MEMORY = "BEHAVIORAL_MEMORY"
    SIMILARITY = "SIMILARITY"
    EXPERT_ENSEMBLE = "EXPERT_ENSEMBLE"
    PROBABILITY = "PROBABILITY"
    CALIBRATION = "CALIBRATION"
    COST = "COST"
    LIQUIDITY = "LIQUIDITY"
    RISK = "RISK"
    PORTFOLIO = "PORTFOLIO"
    OPPORTUNITY = "OPPORTUNITY"
    HEALTH = "HEALTH"
    TRADE_EVOLUTION = "TRADE_EVOLUTION"
    PAPER_SHADOW = "PAPER_SHADOW"
    SAFETY = "SAFETY"
    AUDIT = "AUDIT"
    VALIDATION = "VALIDATION"
    EXECUTION_BOUNDARY = "EXECUTION_BOUNDARY"


@dataclass(frozen=True, slots=True)
class LayerContract:
    name: LayerKind
    owner: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    required: bool = True
    profitability_testing_stage: bool = False


LAYER_CONTRACTS: tuple[LayerContract, ...] = (
    LayerContract(LayerKind.DATA, "data-provider", ("provider", "instrument"), ("market_observations",)),
    LayerContract(LayerKind.DATA_FRESHNESS, "data-refresh", ("market_observations", "clock"), ("freshness_state",)),
    LayerContract(LayerKind.INTEGRITY, "data-integrity", ("market_observations", "freshness_state"), ("validated_observations", "quality_state")),
    LayerContract(LayerKind.DOMAIN_CONTEXT, "domain-intelligence", ("validated_observations", "instrument_profile"), ("domain_context",)),
    LayerContract(LayerKind.REGIME, "regime-engine", ("domain_context",), ("regime_state",)),
    LayerContract(LayerKind.BEHAVIORAL_MEMORY, "behavioral-memory", ("regime_state", "matured_history"), ("historical_context",)),
    LayerContract(LayerKind.SIMILARITY, "similarity-engine", ("domain_context", "historical_context"), ("analogue_evidence",)),
    LayerContract(LayerKind.EXPERT_ENSEMBLE, "expert-router", ("domain_context", "analogue_evidence"), ("expert_votes",)),
    LayerContract(LayerKind.PROBABILITY, "probability-engine", ("expert_votes", "historical_context"), ("probability_estimate",)),
    LayerContract(LayerKind.CALIBRATION, "calibration-engine", ("probability_estimate", "matured_outcomes"), ("calibration_state",)),
    LayerContract(LayerKind.COST, "cost-engine", ("instrument_profile", "market_observations"), ("net_economics",)),
    LayerContract(LayerKind.LIQUIDITY, "liquidity-engine", ("market_observations", "instrument_profile"), ("liquidity_state",)),
    LayerContract(LayerKind.RISK, "risk-engine", ("probability_estimate", "net_economics", "liquidity_state"), ("risk_eligibility",)),
    LayerContract(LayerKind.PORTFOLIO, "portfolio-engine", ("risk_eligibility", "portfolio_state"), ("allocation_capacity",)),
    LayerContract(LayerKind.OPPORTUNITY, "opportunity-engine", ("probability_estimate", "net_economics", "risk_eligibility", "allocation_capacity"), ("ranked_opportunity",)),
    LayerContract(LayerKind.HEALTH, "model-health", ("recent_observations", "reference_observations"), ("health_state",)),
    LayerContract(LayerKind.TRADE_EVOLUTION, "trade-lifecycle", ("open_trade", "market_context"), ("evolution_state",)),
    LayerContract(LayerKind.PAPER_SHADOW, "paper-shadow", ("final_decision", "trade_evolution"), ("operational_observation",)),
    LayerContract(LayerKind.SAFETY, "safety-engine", ("decision_artifacts", "health_state", "operational_state"), ("safety_authorization",)),
    LayerContract(LayerKind.AUDIT, "audit-engine", ("all_decision_artifacts",), ("decision_record",)),
    LayerContract(LayerKind.VALIDATION, "validation-engine", ("frozen_candidate", "untouched_evidence"), ("validation_verdict",), profitability_testing_stage=True),
    LayerContract(LayerKind.EXECUTION_BOUNDARY, "execution-gateway", ("final_decision", "safety_authorization"), ("order_intent",)),
)


def required_layer_names() -> tuple[LayerKind, ...]:
    """Return the authoritative pre-validation operating stack.

    Validation is intentionally retained as a separately modeled deferred
    stage, but it is not an operating-layer requirement for this foundation.
    """

    return tuple(
        contract.name
        for contract in LAYER_CONTRACTS
        if contract.required and not contract.profitability_testing_stage
    )


def contracts_by_owner() -> Mapping[str, tuple[LayerContract, ...]]:
    grouped: dict[str, list[LayerContract]] = {}
    for contract in LAYER_CONTRACTS:
        grouped.setdefault(contract.owner, []).append(contract)
    return {owner: tuple(contracts) for owner, contracts in grouped.items()}


def architecture_ready(*, implemented_layers: set[LayerKind], live_execution_enabled: bool = False) -> bool:
    required = set(required_layer_names())
    return required.issubset(implemented_layers) and not live_execution_enabled
