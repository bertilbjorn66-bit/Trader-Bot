from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from trader_bot.asset_universe import AssetClass, InstrumentProfile
from trader_bot.market_flow import FlowAssessment, FlowState, MarketEvidence, assess_flow
from trader_bot.portfolio_flow import AllocationDecision, PortfolioSnapshot, allocate
from .asset_research_contract import ResearchContract, ResearchMode, contract_for
from .domain_profiles import ContextFeature, domain_profile


class ResearchVerdict(StrEnum):
    READY = "READY"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DomainObservation:
    """Decision-time facts emitted by an asset-specific intelligence adapter."""

    available_features: frozenset[ContextFeature]
    evidence: MarketEvidence


@dataclass(frozen=True, slots=True)
class ResearchDecision:
    symbol: str
    asset_class: AssetClass
    verdict: ResearchVerdict
    reasons: tuple[str, ...]
    flow: FlowAssessment
    allocation: AllocationDecision | None


class AssetIntelligenceAdapter(Protocol):
    """Pure research adapter: no order transmission and no portfolio mutation."""

    asset_class: AssetClass

    def observe(self, profile: InstrumentProfile) -> DomainObservation: ...


class FixedEvidenceAdapter:
    """Testing/development adapter for one domain; never authorizes execution."""

    def __init__(self, asset_class: AssetClass, evidence: MarketEvidence) -> None:
        self.asset_class = asset_class
        self.evidence = evidence

    def observe(self, profile: InstrumentProfile) -> DomainObservation:
        contract: ResearchContract = contract_for(profile)
        if contract.mode not in {
            ResearchMode.HISTORICAL,
            ResearchMode.WALK_FORWARD,
            ResearchMode.CONFIRMATION,
        }:
            raise ValueError("unsupported research mode")
        return DomainObservation(
            available_features=frozenset(domain_profile(profile).required),
            evidence=self.evidence,
        )


class MultiAssetResearchEngine:
    """Uniform orchestration with asset-specific intelligence at the observation boundary."""

    def __init__(self, adapters: Mapping[AssetClass, AssetIntelligenceAdapter]) -> None:
        self._adapters = dict(adapters)

    def evaluate(
        self,
        profile: InstrumentProfile,
        snapshot: PortfolioSnapshot | None = None,
    ) -> ResearchDecision:
        contract: ResearchContract = contract_for(profile)
        contract.validate_profile(profile)
        required = domain_profile(profile).required
        adapter = self._adapters.get(profile.asset_class)
        if adapter is None:
            reason = "asset_class_intelligence_adapter_missing"
            flow = FlowAssessment(FlowState.BLOCKED, (reason,), 0.0)
            return ResearchDecision(profile.symbol, profile.asset_class, ResearchVerdict.BLOCKED, (reason,), flow, None)
        if adapter.asset_class is not profile.asset_class:
            raise ValueError("intelligence adapter asset class does not match instrument")

        observation = adapter.observe(profile)
        missing = tuple(sorted(feature.value for feature in required - observation.available_features))
        if missing:
            reasons = tuple(f"missing_context:{feature}" for feature in missing)
            flow = FlowAssessment(FlowState.BLOCKED, reasons, 0.0)
            return ResearchDecision(profile.symbol, profile.asset_class, ResearchVerdict.BLOCKED, reasons, flow, None)

        flow = assess_flow(profile, observation.evidence)
        if flow.state is not FlowState.READY:
            verdict = ResearchVerdict.BLOCKED if flow.state is FlowState.BLOCKED else ResearchVerdict.WAIT
            return ResearchDecision(profile.symbol, profile.asset_class, verdict, flow.reasons, flow, None)

        portfolio = snapshot if snapshot is not None else PortfolioSnapshot()
        allocation = allocate(profile.symbol, profile.asset_class, flow, portfolio)
        verdict = ResearchVerdict.READY if allocation.allowed else ResearchVerdict.WAIT
        reasons = () if allocation.allowed else (allocation.reason,)
        return ResearchDecision(profile.symbol, profile.asset_class, verdict, reasons, flow, allocation)
