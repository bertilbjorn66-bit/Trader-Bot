# Multi-Asset Operating Model

## Purpose

The Trader Bot supports multiple market classes through one calm orchestration path and separate domain intelligence. A market class must understand its own structure before it can contribute a trade decision.

## Universal flow

`observe -> validate -> understand -> estimate edge -> model costs -> check risk -> allocate portfolio budget -> decide -> audit`

Every stage has one owner. A downstream stage cannot compensate for a failed upstream stage.

## Domain intelligence

- **Forex:** session structure, spread, trend/regime, momentum, carry and cross-currency context.
- **Crypto:** 24/7 market state, liquidity, volume, funding, venue microstructure, volatility and crypto cross-market context.
- **Metals:** session behavior, volatility, USD/rates context, liquidity and macro/event sensitivity.
- **Commodities:** session/calendar behavior, inventory/event sensitivity, volume, volatility and related-market context.
- **Equities:** exchange calendar, regular/extended sessions, gaps, liquidity, volume, corporate events and sector/index context.
- **Indices:** exchange calendar, session structure, liquidity, volume, gaps and macro/cross-market context.

These are requirements for research, not assumptions that a trade exists.

## Calm operation rules

1. No trade quotas.
2. No timers that force activity.
3. No retries that turn uncertainty into action.
4. Unknown context is BLOCKED.
5. Insufficient evidence is WAIT.
6. Portfolio saturation is WAIT.
7. Research-only instruments remain non-operational.
8. Live execution is disabled until independent promotion and safety gates pass.

## Research independence

Each asset class has its own empirical research contract. Confirmation is frozen and cannot teach the candidate. Transaction costs and liquidity constraints are mandatory. A positive result in one domain does not promote another domain.

## Portfolio independence

The portfolio allocator is deliberately downstream of domain research. It does not improve or reinterpret a domain signal. It only decides whether a ready opportunity can receive bounded risk under portfolio limits.

## Verification checkpoints

At minimum, every decision path must have these checks:

`data integrity -> domain contract -> evidence sufficiency -> cost viability -> risk eligibility -> portfolio budget -> final decision`

Failures are explicit and auditable; there is no silent fallback into another asset model.
