from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

BOOTSTRAP_REPS = 2000
MIN_DISCOVERY_N = 100
MIN_CONFIRMATION_N = 100
MIN_NO_TRADE_N = 30
STRONG_STABILITY = 2 / 3

SPECS = {
    'pair_horizon_regime_direction': ('pair', 'horizon', 'regime', 'direction'),
    'pair_horizon_regime_session_direction': ('pair', 'horizon', 'regime', 'session', 'direction'),
    'pair_horizon_regime_session': ('pair', 'horizon', 'regime', 'session'),
}

@dataclass(frozen=True)
class Group:
    spec: str
    key: tuple[object, ...]
    split: str
    outcomes: tuple[float, ...]
    years: tuple[int, ...]


def pf(values: Sequence[float]) -> float | None:
    gross_win = sum(v for v in values if v > 0)
    gross_loss = -sum(v for v in values if v < 0)
    if gross_loss == 0:
        return None
    return gross_win / gross_loss


def bootstrap_ci(values: Sequence[float], seed: int, reps: int = BOOTSTRAP_REPS) -> tuple[float, float] | tuple[None, None]:
    if len(values) < MIN_CONFIRMATION_N:
        return (None, None)
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(reps):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo = means[max(0, int(0.025 * reps) - 1)]
    hi = means[min(reps - 1, int(0.975 * reps))]
    return lo, hi


def metrics(values: Sequence[float], years: Sequence[int], *, bootstrap: bool, seed: int = 0) -> dict[str, Any]:
    n = len(values)
    expectancy = sum(values) / n if n else None
    profit_factor = pf(values)
    positive_years = 0
    observed_years = 0
    by_year: dict[int, list[float]] = defaultdict(list)
    for y, v in zip(years, values):
        by_year[y].append(v)
    for vals in by_year.values():
        observed_years += 1
        if sum(vals) / len(vals) > 0:
            positive_years += 1
    stability = positive_years / observed_years if observed_years else 0.0
    ci = bootstrap_ci(values, seed) if bootstrap else (None, None)
    status = 'UNKNOWN'
    if n >= MIN_CONFIRMATION_N:
        if expectancy is not None and profit_factor is not None and ci[0] is not None and ci[0] > 0 and stability >= STRONG_STABILITY:
            status = 'STRONG_CONTEXT'
        elif expectancy is not None and (expectancy > 0 or (profit_factor is not None and profit_factor > 1)):
            status = 'WATCH_CONTEXT'
        elif expectancy is not None and (expectancy <= 0 or (profit_factor is not None and profit_factor <= 1)):
            status = 'NO_TRADE'
    elif n >= MIN_NO_TRADE_N and expectancy is not None and (expectancy <= 0 or (profit_factor is not None and profit_factor <= 1)):
        status = 'NO_TRADE'
    return {
        'n': n,
        'expectancy_pips': expectancy,
        'profit_factor': profit_factor,
        'win_rate': sum(v > 0 for v in values) / n if n else None,
        'positive_years': positive_years,
        'observed_years': observed_years,
        'stability_ratio': stability,
        'bootstrap_expectancy_ci_pips': list(ci),
        'status': status,
    }


def load(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
    records: list[dict[str, Any]] = data['target_records']
    return data, records


def build_groups(records: Iterable[dict[str, Any]]) -> list[Group]:
    buckets: dict[tuple[str, tuple[object, ...], str], list[tuple[float, int]]] = defaultdict(list)
    for rec in records:
        for spec, keys in SPECS.items():
            key = tuple(rec[k] for k in keys)
            buckets[(spec, key, rec['split'])].append((float(rec['outcome_pips']), int(rec['year'])))
    return [
        Group(spec, key, split, tuple(v for v, _ in vals), tuple(y for _, y in vals))
        for (spec, key, split), vals in buckets.items()
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    _, records = load(Path(args.input))
    source_digest = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
    groups = build_groups(records)

    discovery_candidates: list[dict[str, Any]] = []
    for discovery_group in groups:
        if discovery_group.split != 'discovery' or len(discovery_group.outcomes) < MIN_DISCOVERY_N:
            continue
        m = metrics(discovery_group.outcomes, discovery_group.years, bootstrap=False)
        if (m['expectancy_pips'] is not None and m['expectancy_pips'] > 0 and
                m['profit_factor'] is not None and m['profit_factor'] > 1):
            discovery_candidates.append({'spec': discovery_group.spec, 'key': list(discovery_group.key), 'discovery': m})

    discovery_candidates.sort(
        key=lambda x: (
            float(x['discovery']['expectancy_pips']),
            float(x['discovery']['profit_factor']),
            int(x['discovery']['n']),
        ), reverse=True,
    )
    selected: list[dict[str, Any]] = []
    per_spec: dict[str, int] = defaultdict(int)
    for c in discovery_candidates:
        spec = str(c['spec'])
        if per_spec[spec] >= 20:
            continue
        selected.append(c)
        per_spec[spec] += 1

    index = {(group.spec, group.key, group.split): group for group in groups}
    confirmation_results: list[dict[str, Any]] = []
    for c in selected:
        spec = str(c['spec'])
        key = tuple(c['key'])
        confirmation_group = index.get((spec, key, 'confirmation'))
        if confirmation_group is None or len(confirmation_group.outcomes) < MIN_CONFIRMATION_N:
            continue
        seed_material = f'{spec}|{key}|confirmation'.encode('utf-8')
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], 'big')
        m = metrics(confirmation_group.outcomes, confirmation_group.years, bootstrap=True, seed=seed)
        confirmation_results.append({
            'spec': spec,
            'key': list(key),
            'split': 'confirmation',
            'discovery_metrics': c['discovery'],
            'confirmation_metrics': m,
        })

    strong = [r for r in confirmation_results if r['confirmation_metrics']['status'] == 'STRONG_CONTEXT']
    watch = [r for r in confirmation_results if r['confirmation_metrics']['status'] == 'WATCH_CONTEXT']
    no_trade = [r for r in confirmation_results if r['confirmation_metrics']['status'] == 'NO_TRADE']

    result: dict[str, Any] = {
        'status': 'HIERARCHICAL_CONTEXT_VALIDATION_COMPLETED',
        'source': 'VERIFIED-FINAL-HOLDOUT-RESEARCH',
        'record_count': len(records),
        'input_sha256': source_digest,
        'methodology': {
            'purpose': 'test broader context abstractions without tuning on confirmation data',
            'hierarchies': {k: list(v) for k, v in SPECS.items()},
            'discovery_min_samples': MIN_DISCOVERY_N,
            'confirmation_min_samples': MIN_CONFIRMATION_N,
            'fixed_top_k_per_hierarchy': 20,
            'bootstrap_reps': BOOTSTRAP_REPS,
            'strong_rule': 'confirmation n>=100, expectancy>0, PF>1, lower bootstrap bound>0, positive expectancy in >=67% of observed years',
            'no_trade_rule': 'confirmation n>=30, non-positive expectancy or PF<=1',
            'selection_split': 'discovery_only',
            'live_authorization': 'never granted by this analysis',
            'input_mutation': 'none',
        },
        'summary': {
            'discovery_candidates': len(discovery_candidates),
            'selected_candidates': len(selected),
            'confirmation_evaluated': len(confirmation_results),
            'strong_contexts': len(strong),
            'watch_contexts': len(watch),
            'no_trade_contexts': len(no_trade),
        },
        'strong_contexts': strong,
        'watch_contexts': watch,
        'no_trade_contexts': no_trade,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('HIERARCHICAL_CONTEXT_VALIDATION_COMPLETED=true')
    print('DISCOVERY_CANDIDATES=', len(discovery_candidates))
    print('CONFIRMATION_EVALUATED=', len(confirmation_results))
    print('STRONG_CONTEXTS=', len(strong))
    print('WATCH_CONTEXTS=', len(watch))
    print('NO_TRADE_CONTEXTS=', len(no_trade))
    print('INPUT_SHA256=', source_digest)

if __name__ == '__main__':
    main()
