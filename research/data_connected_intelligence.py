from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from research.intelligence_audit import lagged_correlations, regime_transition_stats
from research.intelligence_controls import drift_report


@dataclass(frozen=True)
class PairRelationSummary:
    horizon: int
    pair_a: str
    pair_b: str
    observations: int
    contemporaneous: float
    strongest_lag: int
    strongest_lag_correlation: float


@dataclass(frozen=True)
class CalibrationSummary:
    horizon: int
    observations: int
    mean_agreement: float
    positive_rate: float


@dataclass(frozen=True)
class CostStressSummary:
    horizon: int
    gross_expectancy_pips: float
    net_at_05_pips: float
    net_at_10_pips: float
    net_at_20_pips: float


def _aligned_series(records: Sequence[dict[str, Any]], horizon: int, pair_a: str, pair_b: str) -> tuple[list[float], list[float]]:
    a = {str(r['timestamp']): float(r['outcome_pips']) for r in records if int(r['horizon']) == horizon and r['pair'] == pair_a}
    b = {str(r['timestamp']): float(r['outcome_pips']) for r in records if int(r['horizon']) == horizon and r['pair'] == pair_b}
    common = sorted(set(a) & set(b))
    return [a[t] for t in common], [b[t] for t in common]


def _calibration(records: Sequence[dict[str, Any]], horizon: int) -> CalibrationSummary:
    rows = [r for r in records if int(r['horizon']) == horizon]
    if not rows:
        raise ValueError('no records for calibration')
    agreement = [float(r['agreement']) for r in rows]
    positive = [float(r['outcome_pips']) > 0 for r in rows]
    return CalibrationSummary(horizon, len(rows), mean(agreement), mean(positive))


def _cost_stress(records: Sequence[dict[str, Any]], horizon: int) -> CostStressSummary:
    values = [float(r['outcome_pips']) for r in records if int(r['horizon']) == horizon]
    if not values:
        raise ValueError('no records for cost stress')
    gross = mean(values)
    return CostStressSummary(horizon, gross, gross - 0.5, gross - 1.0, gross - 2.0)


def build_data_connected_intelligence(input_path: Path, output_path: Path) -> dict[str, Any]:
    raw = input_path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode('utf-8'))
    records: list[dict[str, Any]] = data['target_records']
    pairs = sorted({str(r['pair']) for r in records})
    horizons = sorted({int(r['horizon']) for r in records})

    relations: list[PairRelationSummary] = []
    for horizon in horizons:
        for pair_a, pair_b in itertools.combinations(pairs, 2):
            a, b = _aligned_series(records, horizon, pair_a, pair_b)
            if len(a) < 20:
                continue
            lagged = lagged_correlations(a, b, max_lag=5)
            strongest = max(lagged, key=lambda item: abs(item.correlation))
            zero_lag = next(item for item in lagged if item.lag == 0)
            relations.append(
                PairRelationSummary(
                    horizon,
                    pair_a,
                    pair_b,
                    len(a),
                    zero_lag.correlation,
                    strongest.lag,
                    strongest.correlation,
                )
            )

    transitions: dict[str, Any] = {}
    for pair in pairs:
        rows = sorted((r for r in records if r['pair'] == pair), key=lambda r: str(r['timestamp']))
        seen: set[tuple[str, int]] = set()
        states: list[str] = []
        outcomes: list[float] = []
        for row in rows:
            key = (str(row['timestamp']), int(row['horizon']))
            if key in seen:
                continue
            seen.add(key)
            states.append(str(row['regime']))
            outcomes.append(float(row['outcome_pips']))
        stats = regime_transition_stats(states, outcomes) if len(states) >= 2 else []
        transitions[pair] = [stat.__dict__ for stat in stats]

    calibrations = [_calibration(records, horizon).__dict__ for horizon in horizons]
    costs = [_cost_stress(records, horizon).__dict__ for horizon in horizons]

    discovery = [float(r['outcome_pips']) for r in records if r['split'] == 'discovery']
    confirmation = [float(r['outcome_pips']) for r in records if r['split'] == 'confirmation']
    drift = drift_report(discovery, confirmation)

    result = {
        'status': 'DATA_CONNECTED_INTELLIGENCE_ATLAS_COMPLETED',
        'source': 'VERIFIED-FINAL-HOLDOUT-RESEARCH',
        'input_sha256': source_digest,
        'record_count': len(records),
        'pairs': pairs,
        'horizons': horizons,
        'cross_pair_relations': [relation.__dict__ for relation in relations],
        'regime_transitions': transitions,
        'agreement_calibration': calibrations,
        'cost_stress': costs,
        'discovery_vs_confirmation_drift': drift.__dict__,
        'promotion': {
            'live_authorization': False,
            'strategy_promotion': False,
            'interpretation': 'descriptive intelligence only; no strategy is promoted by this artifact',
        },
    }
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return result
